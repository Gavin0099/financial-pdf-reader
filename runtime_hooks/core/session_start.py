#!/usr/bin/env python3
"""
Build a session-start governance context from state generation plus pre-task checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from governance_tools.authority_loader import (
    filter_for_session,
    load_authority_table,
    validate_session_payload,
)
from governance_tools.payload_audit_logger import (
    build_audit_record,
    is_audit_enabled,
    write_audit_record,
)
from governance_tools.change_proposal_builder import build_change_proposal
from governance_tools.domain_governance_metadata import domain_risk_tier
from governance_tools.domain_summary_loader import inject_domain_summary
from governance_tools.domain_validator_loader import preflight_domain_validators
from governance_tools.framework_risk_signal import compute_overrides, read_risk_signal
from governance_tools.framework_versioning import repo_root_from_tooling
from governance_tools.l0_domain_gate import get_l0_domain_skip_reason, should_load_domain_contract
from governance_tools.rule_pack_loader import get_context_aware_rule_packs
from governance_tools.state_generator import generate_state
from governance_tools.task_level_detector import (
    apply_upgrade_triggers,
    detect_task_level,
    get_l0_context_limits,
)
from runtime_hooks.core.human_summary import build_summary_line, format_contract_summary_label
from runtime_hooks.core.payload_audit_logger import log_session_payload
from runtime_hooks.core.pre_task_check import run_pre_task_check
from runtime_hooks.core._canonical_closeout_context import load_closeout_context


def _emit_rendered_output(rendered: str) -> None:
    """
    Print rendered output without crashing on Windows terminals that cannot
    encode some Unicode characters under code pages such as cp950.
    """
    try:
        print(rendered)
    except UnicodeEncodeError:
        stream = getattr(sys.stdout, "buffer", None)
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        if stream is None:
            safe = rendered.encode(encoding, errors="replace").decode(encoding, errors="replace")
            sys.stdout.write(safe)
            sys.stdout.write("\n")
            return
        stream.write(rendered.encode(encoding, errors="replace") + b"\n")


_PLAN_CONTEXT_PROVENANCE_SIDECAR = Path("artifacts") / "runtime" / "plan-context-provenance.json"
_PLAN_PROVENANCE_MARKER_PREFIX = "<!-- plan_context_provenance "


def _detect_plan_context_provenance(plan_path: Path) -> dict:
    """
    Detect whether the plan file is a compressed summary (plan_summary.py output)
    or the full PLAN.md, by reading only the first line.

    Full PLAN.md:       fidelity=full, no summary_kind
    plan_summary.py:    fidelity=summarized, summary_kind=deterministic_extract
    """
    try:
        first_line = plan_path.read_text(encoding="utf-8").split("\n", 1)[0]
        if first_line.startswith(_PLAN_PROVENANCE_MARKER_PREFIX):
            return {
                "fidelity": "summarized",
                "origin": "plan_summary.py",
                "summary_kind": "deterministic_extract",
            }
    except OSError:
        pass
    return {
        "fidelity": "full",
        "origin": plan_path.name,
        "summary_kind": None,
    }


def build_session_start_context(
    *,
    project_root: Path,
    plan_path: Path,
    rules: str,
    risk: str,
    oversight: str,
    memory_mode: str,
    task_text: str = "",
    impact_before_files: list[Path] | None = None,
    impact_after_files: list[Path] | None = None,
    contract_file: Path | None = None,
    task_level: str | None = None,
    force_domain: bool = False,
    task_type: str = "general",
) -> dict:
    impact_before_files = impact_before_files or []
    impact_after_files = impact_after_files or []

    # ── Task level detection ─────────────────────────────────────────────────
    # Explicit task_level takes priority; None triggers keyword-based auto-detection.
    detected_level = detect_task_level(task_description=task_text, explicit_level=task_level)
    final_level, additional_loads = apply_upgrade_triggers(
        task_level=detected_level,
        task_description=task_text,
        risk_level=risk,
    )
    level_decision = {
        "requested": task_level,
        "detected": detected_level,
        "final": final_level,
        "upgraded": final_level != detected_level,
        "additional_loads": additional_loads,
    }

    # ── Framework risk signal ─────────────────────────────────────────────
    # A prior drift check may have written a signal recording a critical failure.
    # When active, defensively upgrade task_level to at least the required minimum.
    # Signal only upgrades defense — never changes rules or overrides policy.
    _fw_root = repo_root_from_tooling()
    _active_signal = read_risk_signal(_fw_root)
    _sig_overrides = compute_overrides(_active_signal)
    if _sig_overrides.get("min_task_level"):
        _level_order = {"L0": 0, "L1": 1, "L2": 2}
        _min = _sig_overrides["min_task_level"]
        if _level_order.get(_min, 0) > _level_order.get(final_level, 0):
            final_level = _min
            level_decision["upgraded"] = True
            level_decision["upgrade_reason"] = f"risk_signal:min_task_level={_min}"
    level_decision["final"] = final_level
    # Skip domain contract for L0 unless force_domain is set or task description
    # contains domain keywords.
    load_domain, _load_mode = should_load_domain_contract(
        task_level=final_level,
        force_domain=force_domain,
        task_description=task_text,
    )
    domain_skip_reason: str | None = None
    if not load_domain:
        domain_skip_reason = get_l0_domain_skip_reason(task_text)
        contract_file = None  # prevent pre_task_check from loading domain contract

    # Authority filter: determine allowed governance files for this session.
    # L0 → always-load only; L1/L2 → always + on-demand.
    governance_dir = project_root / "governance"
    authority_table = load_authority_table(governance_dir)
    include_on_demand = final_level != "L0"
    allowed_governance_files = filter_for_session(authority_table, include_on_demand=include_on_demand)

    # ── L0 forbidden load guard ──────────────────────────────────────────────
    # Belt-and-suspenders: ensure forbidden files are not in allowed set.
    if final_level == "L0":
        limits = get_l0_context_limits()
        forbidden = limits["forbidden_load"]
        allowed_governance_files = [
            f for f in allowed_governance_files
            if not any(fb.replace("governance/", "") in f for fb in forbidden)
        ]

    authority_validation = validate_session_payload(allowed_governance_files, authority_table)

    state = generate_state(
        plan_path=plan_path,
        rules=rules,
        risk=risk,
        oversight=oversight,
        memory_mode=memory_mode,
        project_root=project_root,
        task_text=task_text or None,
        impact_before_files=impact_before_files,
        impact_after_files=impact_after_files,
    )

    pre_task = run_pre_task_check(
        project_root=project_root,
        rules=rules,
        risk=risk,
        oversight=oversight,
        memory_mode=memory_mode,
        task_text=task_text,
        impact_before_files=impact_before_files,
        impact_after_files=impact_after_files,
        contract_file=contract_file,
        skip_domain_contract=not load_domain,
        task_level=final_level,
        disable_summary_first=bool(_sig_overrides.get("disable_summary_first")),
    )

    proposal = build_change_proposal(
        project_root=project_root,
        task_text=task_text,
        rules=rules,
        impact_before_files=impact_before_files,
        impact_after_files=impact_after_files,
    )
    resolved_contract_file = Path(pre_task["resolved_contract_file"]) if pre_task.get("resolved_contract_file") else None

    # ── Context-aware rule pack classification ─────────────────────────────
    # Detects repo_type from project structure and filters rule packs accordingly.
    context_rule_info = get_context_aware_rule_packs(
        project_root=project_root,
        task_type=task_type,
    )

    # ── Domain summary loader ──────────────────────────────────────────────
    # Replaces full inline documents with slim summary when available,
    # reducing domain_contract token usage by ≥ 50% for rich contracts.
    domain_contract = pre_task.get("domain_contract")
    if domain_contract and resolved_contract_file:
        domain_contract = inject_domain_summary(domain_contract, resolved_contract_file)

    validator_preflight = preflight_domain_validators(resolved_contract_file) if resolved_contract_file else None

    # ── Governance strategy classification (session-init first pass) ─────────
    # Evidence is conservative: classify down when uncertain.
    # See docs/governance-strategy-runtime.md for decision rules.
    _instruction_candidates = [
        project_root / "CLAUDE.md",
        project_root / "AGENTS.md",
        Path(__file__).resolve().parents[2] / "CLAUDE.md",
    ]
    _instruction_found = any(f.exists() for f in _instruction_candidates)
    _instruction_loaded = "true" if _instruction_found else "unknown"
    _session_classification_evidence = {
        "has_file_access": {"value": True, "source": "observed"},
        "instruction_loaded": {"value": _instruction_loaded, "source": "observed" if _instruction_found else "assumed"},
        "context_integrity": {"value": "unknown", "source": "assumed"},  # no signals yet at session init
        "tool_gate": {"value": "active", "source": "observed"},  # this hook is executing
    }
    _pre_task_warnings = pre_task.get("warnings") or []
    if any("truncat" in w.lower() or "token_budget" in w.lower() for w in _pre_task_warnings):
        _session_classification_evidence["context_integrity"] = {"value": "degraded", "source": "observed"}
    _ctx = _session_classification_evidence["context_integrity"]["value"]
    if _ctx == "degraded" or _instruction_loaded == "false":
        _effective_agent_class = "instruction_limited"
    elif _instruction_loaded in ("true", "unknown") and _ctx in ("unknown", "full"):
        _effective_agent_class = "instruction_capable"
    else:
        _effective_agent_class = "instruction_limited"
    _strategy_map = {
        "instruction_capable": "injection+enforcement",
        "instruction_limited": "minimal_injection+enforcement",
        "wrapper_only": "no_injection+strict_enforcement",
    }
    session_governance_classification = {
        "classification_evidence": _session_classification_evidence,
        "initial_agent_class": None,       # not applicable: this IS the initial classification
        "effective_agent_class": _effective_agent_class,
        "classification_changed": None,    # not applicable at session_start
        "reclassification_reason": None,   # not applicable at session_start
        "governance_strategy": _strategy_map[_effective_agent_class],
        "injection_reliance": "none",
    }

    # ── Canonical closeout context injection (Slice 5) ────────────────────────
    # Reads the most recent canonical closeout artifact to provide continuity
    # context from the previous session. Gracefully degrades on any failure.
    # Only canonical closeouts are read — candidates and session-index are never
    # consulted here. See docs/closeout-schema.md — Downstream Consumer Rules.
    closeout_context = load_closeout_context(project_root)

    # Payload audit hook — zero overhead when disabled (env var not set)
    if is_audit_enabled():
        _audit_contracts = [str(resolved_contract_file)] if resolved_contract_file else []
        _audit_record = build_audit_record(
            task_level=final_level,
            task_type=task_type,
            files_loaded=allowed_governance_files,
            domain_contracts=_audit_contracts,
            memory_files=[],  # session_start does not directly load memory files
            extra_context={
                "rules": rules,
                "risk": risk,
                "has_domain_contract": domain_contract is not None,
                "rule_pack_suggestions_count": len(pre_task.get("rule_pack_suggestions", {})),
                **({"domain_skip_reason": domain_skip_reason} if domain_skip_reason else {}),
            },
        )
        write_audit_record(_audit_record)

    return {
        "ok": state.get("error") is None and pre_task["ok"] and authority_validation["ok"],
        "project_root": str(project_root),
        "task_level": final_level,
        "level_decision": level_decision,
        "repo_type": context_rule_info["repo_type"],
        "context_aware_rules": context_rule_info["active_packs"],
        "authority_filter": {
            "allowed_count": len(allowed_governance_files),
            "include_on_demand": include_on_demand,
            "validation_ok": authority_validation["ok"],
            "violations": authority_validation["violations"],
        },
        "task_text": task_text,
        "runtime_contract": pre_task["runtime_contract"],
        "suggested_rules_preview": pre_task.get("suggested_rules_preview", []),
        "suggested_skills": pre_task.get("suggested_skills", []),
        "suggested_agent": pre_task.get("suggested_agent"),
        "rule_pack_suggestions": pre_task.get("rule_pack_suggestions", {}),
        "architecture_impact_preview": pre_task.get("architecture_impact_preview"),
        "proposal_guidance": state.get("proposal_guidance"),
        "change_proposal": proposal,
        "proposal_summary": proposal.get("proposal_summary"),
        "resolved_contract_file": str(resolved_contract_file) if resolved_contract_file else None,
        "contract_resolution": pre_task.get("contract_resolution"),
        "domain_contract": domain_contract,
        "domain_skip_reason": domain_skip_reason,
        "validator_preflight": validator_preflight,
        "risk_signal": {
            "active": _active_signal is not None,
            "overrides": _sig_overrides,
        },
        "state": state,
        "pre_task_check": pre_task,
        "governance_classification": session_governance_classification,
        "closeout_context": closeout_context,
        # Compression provenance — decision precondition metadata.
        # Records whether this session was started with the full PLAN.md or a
        # compressed summary (plan_summary.py output).  Lets session_end and
        # replay_verification know under what fidelity a decision was made.
        "plan_context_provenance": _detect_plan_context_provenance(plan_path),
    }


def format_human_result(result: dict) -> str:
    def _first_line(text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return ""

    lines = [
        "[session_start]",
        f"ok={result['ok']}",
        f"rules={','.join(result['runtime_contract'].get('rules', []))}",
    ]
    # Risk signal banner — placed before all other output so AI reads it first.
    _risk_sig = result.get("risk_signal") or {}
    if _risk_sig.get("active"):
        from datetime import datetime, timezone
        from governance_tools.framework_risk_signal import read_risk_signal
        from governance_tools.framework_versioning import repo_root_from_tooling as _fw_root_fn
        _raw_sig = read_risk_signal(_fw_root_fn())
        _age_str = ""
        if _raw_sig and _raw_sig.get("generated_at"):
            try:
                _gen = datetime.fromisoformat(_raw_sig["generated_at"])
                if _gen.tzinfo is None:
                    _gen = _gen.replace(tzinfo=timezone.utc)
                _age_h = (datetime.now(timezone.utc) - _gen).total_seconds() / 3600
                _age_str = f", age={_age_h:.1f}h"
            except ValueError:
                pass
        _comps = ", ".join((_raw_sig or {}).get("affected_components", []))
        _src = (_raw_sig or {}).get("source", "unknown")
        _sev = (_raw_sig or {}).get("severity", "unknown")
        _applied = ", ".join(
            f"{k}={v}" for k, v in _risk_sig.get("overrides", {}).items()
        )
        lines.insert(0, "[FRAMEWORK RISK SIGNAL ACTIVE]")
        lines.insert(1, f"  severity={_sev}, source={_src}{_age_str}")
        lines.insert(2, f"  affected={_comps or '<none>'}")
        lines.insert(3, f"  applied_overrides={_applied or '<none>'}")
        lines.insert(4, "")
    domain_contract = result.get("domain_contract") or {}
    domain_raw = domain_contract.get("raw") or {}
    contract_label = domain_raw.get("domain") or domain_contract.get("name")
    contract_risk = domain_risk_tier(domain_raw.get("domain") or domain_contract.get("name"))
    proposal_summary = result.get("proposal_summary") or {}
    lines.append(
        build_summary_line(
            f"ok={result['ok']}",
            f"rules={','.join(result['runtime_contract'].get('rules', []))}",
            (
                f"contract={format_contract_summary_label(contract_label, contract_risk)}"
                if contract_label
                else None
            ),
            (
                f"proposal_risk={proposal_summary.get('recommended_risk')}"
                if proposal_summary.get("recommended_risk")
                else None
            ),
        )
    )
    if result.get("suggested_rules_preview"):
        lines.append(f"suggested_rules_preview={','.join(result['suggested_rules_preview'])}")
    if result.get("suggested_skills"):
        lines.append(f"suggested_skills={','.join(result['suggested_skills'])}")
    if result.get("suggested_agent"):
        lines.append(f"suggested_agent={result['suggested_agent']}")
    contract_resolution = result.get("contract_resolution") or {}
    if contract_resolution.get("source"):
        lines.append(f"contract_source={contract_resolution['source']}")
    if contract_resolution.get("path"):
        lines.append(f"contract_path={contract_resolution['path']}")
    if contract_label:
        lines.append(f"contract={contract_label}")
        lines.append(f"contract_risk_tier={contract_risk}")
    if domain_contract:
        lines.append(f"domain_contract={domain_contract.get('name')}")
        if domain_contract.get("rule_roots"):
            lines.append(f"domain_rule_roots={len(domain_contract['rule_roots'])}")
        validators = domain_contract.get("validators") or []
        if validators:
            lines.append(f"domain_validators={','.join(item['name'] for item in validators)}")
        validator_preflight = result.get("validator_preflight") or {}
        if validator_preflight:
            lines.append(f"validator_preflight_ok={validator_preflight.get('ok')}")
            lines.append(f"validator_preflight_count={validator_preflight.get('count')}")
        documents = domain_contract.get("documents") or []
        if documents:
            lines.append(f"domain_documents={','.join(Path(item['path']).name for item in documents)}")
            for item in documents:
                preview = _first_line(item.get("content", ""))
                if preview:
                    lines.append(f"document_preview[{Path(item['path']).name}]={preview}")
        overrides = domain_contract.get("ai_behavior_override") or []
        if overrides:
            lines.append(f"domain_behavior_overrides={','.join(Path(item['path']).name for item in overrides)}")
            for item in overrides:
                preview = _first_line(item.get("content", ""))
                if preview:
                    lines.append(f"behavior_preview[{Path(item['path']).name}]={preview}")
        for item in (validator_preflight or {}).get("validators", []):
            lines.append(f"validator_preflight[{item['name']}]={item['ok']}")

    summary = proposal_summary
    guidance = result.get("proposal_guidance") or {}
    if guidance:
        lines.append("[proposal_guidance]")
        lines.append(f"recommended_risk={summary.get('recommended_risk')}")
        lines.append(f"recommended_oversight={summary.get('recommended_oversight')}")
        validators = summary.get("expected_validators") or []
        if validators:
            lines.append(f"expected_validators={','.join(validators)}")
        evidence = summary.get("required_evidence") or []
        if evidence:
            lines.append(f"required_evidence={','.join(evidence)}")
        concerns = summary.get("concerns") or []
        if concerns:
            lines.append(f"concerns={','.join(concerns)}")

    proposal = result.get("change_proposal") or {}
    requested_rules = proposal.get("requested_rules") or []
    if requested_rules:
        lines.append("[change_proposal]")
        lines.append(f"proposal_rules={','.join(requested_rules)}")

    for warning in result["pre_task_check"].get("warnings", []):
        lines.append(f"warning: {warning}")
    for error in result["pre_task_check"].get("errors", []):
        lines.append(f"error: {error}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a session-start governance context.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--plan", default="PLAN.md")
    parser.add_argument("--rules", default="common")
    parser.add_argument("--risk", default="medium")
    parser.add_argument("--oversight", default="auto")
    parser.add_argument("--memory-mode", default="candidate")
    parser.add_argument("--task-text", default="")
    parser.add_argument("--impact-before", action="append", default=[])
    parser.add_argument("--impact-after", action="append", default=[])
    parser.add_argument("--contract")
    parser.add_argument("--task-level", choices=["L0", "L1", "L2"], default=None,
                        help="Task level for authority filter and audit (auto-detected from task text if omitted)")
    parser.add_argument("--task-type", default="general",
                        help="Task type for audit log (ui/schema/api/domain/test/general)")
    parser.add_argument("--force-domain", action="store_true", default=False,
                        help="Force domain contract loading for L0 (summary only)")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    parser.add_argument("--output")
    args = parser.parse_args()

    result = build_session_start_context(
        project_root=Path(args.project_root).resolve(),
        plan_path=Path(args.plan),
        rules=args.rules,
        risk=args.risk,
        oversight=args.oversight,
        memory_mode=args.memory_mode,
        task_text=args.task_text,
        impact_before_files=[Path(path) for path in args.impact_before],
        impact_after_files=[Path(path) for path in args.impact_after],
        contract_file=Path(args.contract).resolve() if args.contract else None,
        task_level=args.task_level,
        force_domain=args.force_domain,
        task_type=args.task_type,
    )

    rendered = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else format_human_result(result)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")

    # ── Payload audit logging ──────────────────────────────────────────────
    try:
        log_file = log_session_payload(
            result,
            project_root=Path(args.project_root).resolve(),
            task_type=args.task_type,
            risk=args.risk,
            rules=args.rules,
            task_text=args.task_text,
            format_mode=args.format,
            rendered_output=rendered,
        )
        print(f"[audit] logged → {log_file}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] warning: could not write audit log: {exc}", file=sys.stderr)

    # ── Plan context provenance sidecar ────────────────────────────────────
    # Written so session_end_hook can read the provenance even when the agent
    # does not pass it explicitly. Non-blocking: failure must not abort session.
    try:
        provenance = result.get("plan_context_provenance") or {}
        sidecar = Path(args.project_root).resolve() / _PLAN_CONTEXT_PROVENANCE_SIDECAR
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(
            json.dumps(provenance, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass
    # ──────────────────────────────────────────────────────────────────────

    _emit_rendered_output(rendered)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
