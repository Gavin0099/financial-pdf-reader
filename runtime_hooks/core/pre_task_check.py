#!/usr/bin/env python3
"""
Runtime pre-task governance checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from governance_tools.plan_freshness import check_freshness
from governance_tools.architecture_impact_estimator import estimate_architecture_impact
from governance_tools.contract_resolver import resolve_contract
from governance_tools.domain_governance_metadata import domain_risk_tier
from governance_tools.domain_contract_loader import load_domain_contract
from governance_tools.output_tier import (
    OutputTier,
    TieredOutput,
    generate_trace_id,
    get_default_tier,
)
from governance_tools.reasoning_compressor import compress_fragments
from governance_tools.rule_pack_loader import describe_rule_selection, load_rule_content, parse_rule_list
from governance_tools.rule_pack_suggester import suggest_rule_packs
from governance_tools.rule_classifier import classify_task_topic, filter_rules_by_topic
from governance_tools.domain_summary_loader import load_domain_summary
from governance_tools.runtime_injection_observation import observe_full_read_requirement
from governance_tools.runtime_injection_snapshot import load_runtime_injection_snapshot
from runtime_hooks.core.human_summary import build_summary_line, format_contract_summary_label


RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
OVERSIGHT_ORDER = {"auto": 0, "review-required": 1, "human-approval": 2}
PRECONDITION_ACTIONS = {
    "L0": "analysis_only",
    "L1": "restrict_code_generation_and_escalate",
    "L2": "stop",
}
PRECONDITION_SIGNAL_KEYS = {
    "missing_sample": (
        "sample",
        "sample file",
        "sample files",
        "samples/",
        "fixture",
        "fixtures/",
        ".pdf",
        ".bin",
        ".hex",
    ),
    "missing_spec": (
        "spec",
        "specification",
        "protocol doc",
        "design doc",
        "requirements",
        "contract",
        ".md",
        ".pdf",
    ),
    "missing_fixture": (
        "fixture",
        "fixtures/",
        "repro",
        "regression case",
        "test case",
        ".json",
        ".txt",
    ),
}
PRECONDITION_TASK_SIGNALS = {
    "pdf_parser": ("pdf parser", "parse pdf", "pdf parsing"),
    "parser_implementation": ("parser", "parsing", "parse "),
    "protocol_implementation": ("protocol", "wire format", "packet", "message format"),
    "bugfix": ("bugfix", "fix bug", "fix regression", "regression"),
    "regression_fix": ("regression", "repro", "fix failing case"),
}
BOUNDARY_EFFECT_ORDER = {"pass": 0, "warn": 1, "escalate": 2, "stop": 3}
ADVISORY_SIGNAL_METADATA = {
    "context_degraded": {
        "signal_class": "degradation_advisory",
        "decision_distance": "enforced_elsewhere",
        "summary": "runtime visibility dropped before execution",
        "non_proof": "not proof of compliance or violation",
        "usage": "already handled by an escalation path",
    },
    "required_evidence_missing": {
        "signal_class": "evidence_advisory",
        "decision_distance": "enforced_elsewhere",
        "summary": "required evidence is incomplete for this decision surface",
        "non_proof": "not behavioral compliance proof",
        "usage": "already handled by evidence-driven escalation or stop logic",
    },
    "require_full_read_for_large_files": {
        "signal_class": "degradation_advisory",
        "decision_distance": "far",
        "summary": "large-file visibility is partial, which raises review risk",
        "non_proof": "not proof of compliance or violation",
        "usage": "reviewer-visible advisory only; not verdict-bearing",
    },
}


def _strip_rule_content(active_rules_result: dict, tier: OutputTier) -> dict:
    """
    Strip full rule file content from active_rules for TIER1/TIER2.

    TIER1: pack name, category, and file count only; no titles or paths.
    TIER2: pack name, category, file titles and paths; no content.
    TIER3: full content (unchanged).

    The stripped result includes 'content_stripped=True' so downstream
    tooling can detect when full content is not present.
    """
    if tier >= OutputTier.TIER3:
        return active_rules_result

    stripped_packs = []
    for pack in active_rules_result.get("active_rules", []):
        if tier == OutputTier.TIER1:
            stripped_packs.append({
                "name": pack["name"],
                "category": pack.get("category", ""),
                "file_count": len(pack.get("files", [])),
            })
        else:  # TIER2
            stripped_packs.append({
                "name": pack["name"],
                "category": pack.get("category", ""),
                "files": [
                    {"path": f["path"], "title": f["title"]}
                    for f in pack.get("files", [])
                ],
            })

    return {
        **active_rules_result,
        "active_rules": stripped_packs,
        "content_stripped": True,
        "content_tier": int(tier),
    }


def _append_suggestion_warnings(warnings: list[str], requested_rules: list[str], suggestions: dict) -> None:
    active = set(requested_rules)

    for item in suggestions.get("language_packs", []):
        if item["name"] not in active and item.get("confidence") == "high":
            reason = ", ".join(item.get("reasons", [])[:2])
            warnings.append(f"Suggested language pack '{item['name']}' is not active; repo signals: {reason}")

    for item in suggestions.get("framework_packs", []):
        if item["name"] not in active and item.get("confidence") in {"high", "medium"}:
            reason = ", ".join(item.get("reasons", [])[:2])
            warnings.append(f"Suggested framework pack '{item['name']}' is not active; repo signals: {reason}")

    for item in suggestions.get("scope_packs", []):
        if item["name"] not in active:
            reason = ", ".join(item.get("reasons", [])[:2])
            warnings.append(f"Advisory scope pack '{item['name']}' is suggested by task text but not active; signals: {reason}")


def _infer_scope(requested_rules: list[str], suggestions: dict) -> str:
    if "refactor" in requested_rules:
        return "refactor"
    for item in suggestions.get("scope_packs", []):
        if item.get("name") == "refactor":
            return "refactor"
    return "feature"


def _append_impact_warnings(warnings: list[str], impact_preview: dict | None, risk: str, oversight: str) -> None:
    if not impact_preview:
        return

    preview_risk = impact_preview.get("recommended_risk")
    preview_oversight = impact_preview.get("recommended_oversight")

    if preview_risk and RISK_ORDER.get(preview_risk, 0) > RISK_ORDER.get(risk, 0):
        warnings.append(
            f"Architecture impact preview recommends risk '{preview_risk}' but contract risk is '{risk}'"
        )

    if preview_oversight and OVERSIGHT_ORDER.get(preview_oversight, 0) > OVERSIGHT_ORDER.get(oversight, 0):
        warnings.append(
            "Architecture impact preview recommends "
            f"oversight '{preview_oversight}' but contract oversight is '{oversight}'"
        )


def _task_matches_precondition(task_text: str, applies_to: list[str]) -> bool:
    lowered = task_text.lower()
    for item in applies_to:
        signals = PRECONDITION_TASK_SIGNALS.get(item, (item.replace("_", " "),))
        if any(signal in lowered for signal in signals):
            return True
    return False


def _precondition_present(task_text: str, precondition_type: str) -> bool:
    lowered = task_text.lower()
    return any(signal in lowered for signal in PRECONDITION_SIGNAL_KEYS.get(precondition_type, ()))


def _evaluate_preconditions(domain_contract: dict | None, task_text: str, task_level: str) -> dict:
    raw = (domain_contract or {}).get("raw") or {}
    normalized_level = task_level if task_level in PRECONDITION_ACTIONS else "L1"
    checks: list[dict] = []
    effect = "pass"

    for precondition_type in ("missing_sample", "missing_spec", "missing_fixture"):
        applies_to = [
            str(item).strip()
            for item in raw.get(f"preconditions_{precondition_type}", []) or []
            if str(item).strip()
        ]
        if not applies_to:
            continue

        applies = _task_matches_precondition(task_text, applies_to)
        present = _precondition_present(task_text, precondition_type) if applies else False
        action = PRECONDITION_ACTIONS[normalized_level] if applies and not present else "pass"

        if action == "stop":
            effect = "stop"
        elif action == "restrict_code_generation_and_escalate" and effect != "stop":
            effect = "escalate"
        elif action == "analysis_only" and effect == "pass":
            effect = "warn"

        reason = None
        if applies and not present:
            label = precondition_type.replace("missing_", "")
            reason = f"task matched {applies_to!r} but no explicit {label} signal was found in task_text"

        checks.append({
            "type": precondition_type,
            "applies_to": applies_to,
            "applies": applies,
            "present": present,
            "task_level": normalized_level,
            "action": action,
            "reason": reason,
        })

    return {
        "preconditions_checked": checks,
        "boundary_effect": effect,
    }

def _merge_boundary_effect(current: str, candidate: str) -> str:
    if BOUNDARY_EFFECT_ORDER.get(candidate, 0) > BOUNDARY_EFFECT_ORDER.get(current, 0):
        return candidate
    return current


def _evaluate_runtime_injection_snapshot(
    snapshot: dict,
    *,
    task_level: str,
    summary_first_active: bool,
    decision_boundary: dict,
) -> dict:
    normalized_level = task_level if task_level in PRECONDITION_ACTIONS else "L1"
    task_level_scope = snapshot.get("task_level_scope") or []
    checks: list[dict] = []
    effect = "pass"
    action_to_effect = {
        "analysis_only": "warn",
        "restrict_code_generation_and_escalate": "escalate",
        "stop": "stop",
    }

    if task_level_scope and normalized_level not in task_level_scope:
        return {
            "snapshot": snapshot,
            "signals_checked": checks,
            "effect": effect,
        }

    triggers = set(snapshot.get("escalation_triggers") or [])

    if "escalate_if_context_degraded" in triggers:
        triggered = bool(summary_first_active)
        action = PRECONDITION_ACTIONS[normalized_level] if triggered else "pass"
        if action != "pass":
            effect = _merge_boundary_effect(effect, action_to_effect[action])
        checks.append({
            "signal": "context_degraded",
            "triggered": triggered,
            "action": action,
            "reason": (
                "summary-first loading reduced inline contract document content before execution"
                if triggered
                else None
            ),
        })

    if "escalate_if_required_evidence_missing" in triggers:
        boundary_checks = decision_boundary.get("preconditions_checked") or []
        triggered = any(item.get("applies") and not item.get("present") for item in boundary_checks)
        action = PRECONDITION_ACTIONS[normalized_level] if triggered else "pass"
        if action != "pass":
            effect = _merge_boundary_effect(effect, action_to_effect[action])
        checks.append({
            "signal": "required_evidence_missing",
            "triggered": triggered,
            "action": action,
            "reason": (
                "decision boundary detected missing explicit precondition evidence in task_text"
                if triggered
                else None
            ),
        })

    return {
        "snapshot": snapshot,
        "signals_checked": checks,
        "effect": effect,
    }


def _build_consumption_observations(
    snapshot: dict,
    *,
    domain_contract: dict | None,
    summary_first_active: bool,
) -> dict:
    observations: list[dict] = []
    requirements = set(snapshot.get("consumption_requirements") or [])

    if "require_full_read_for_large_files" in requirements:
        observations.append(
            observe_full_read_requirement(
                (domain_contract or {}).get("documents"),
                summary_first_active=summary_first_active,
            )
        )

    return {
        "snapshot": snapshot.get("name"),
        "observations": observations,
    }


def _render_advisory_signal_line(signal_name: str) -> str | None:
    metadata = ADVISORY_SIGNAL_METADATA.get(signal_name)
    if not metadata:
        return None
    return (
        f"advisory_signal: {signal_name} -> "
        f"{metadata['signal_class']}; "
        f"{metadata['summary']}; "
        f"decision distance={metadata['decision_distance']}; "
        f"{metadata['non_proof']}; "
        f"{metadata['usage']}"
    )


def run_pre_task_check(
    project_root: Path,
    rules: str,
    risk: str,
    oversight: str,
    memory_mode: str,
    task_text: str = "",
    impact_before_files: list[Path] | None = None,
    impact_after_files: list[Path] | None = None,
    contract_file: Path | None = None,
    skip_domain_contract: bool = False,
    task_level: str = "L1",
    output_tier: "OutputTier | None" = None,
    task_topic: str | None = None,
    disable_summary_first: bool = False,
) -> dict:
    plan_path = project_root / "PLAN.md"
    freshness = check_freshness(plan_path)
    requested_rules = parse_rule_list(rules)

    # Topic-based rule filtering
    # Infer task topic from task_text + requested_rules unless explicitly given.
    # topic='general' disables filtering (safe default).
    effective_topic = task_topic or classify_task_topic(task_text, requested_rules)
    filtered_rules, topic_filtered_out = filter_rules_by_topic(requested_rules, effective_topic)
    # Always load at minimum the originally requested rules (filtering is advisory
    # for L0/L1; skip filtering if topic is 'general' or unknown).
    rules_to_load = filtered_rules if filtered_rules else requested_rules
    if skip_domain_contract:
        from governance_tools.contract_resolver import ContractResolution
        contract_resolution = ContractResolution(path=None, source="skipped")
        resolved_contract_file = None
        domain_contract = None
        summary_first_active = False
    else:
        contract_resolution = resolve_contract(contract_file, project_root=project_root)
        resolved_contract_file = contract_resolution.path
        # Summary-first gate
        # For L1 and below, if a domain adapter summary exists, load the contract
        # metadata (rule_roots, validators) but skip loading document file content.
        # The domain summary will replace inline document content in session_start.
        # L2 always gets full content for reviewer/human-approval paths.
        summary_first_active = False
        if resolved_contract_file and task_level != "L2" and not disable_summary_first:
            summary = load_domain_summary(resolved_contract_file)
            summary_first_active = summary is not None
        domain_contract = (
            load_domain_contract(resolved_contract_file, skip_document_content=summary_first_active)
            if resolved_contract_file
            else None
        )    framework_root = Path(__file__).resolve().parents[2]
    runtime_injection_snapshot = load_runtime_injection_snapshot(framework_root)
    rules_roots = [Path(path) for path in (domain_contract or {}).get("rule_roots", [])] + [framework_root / "governance" / "rules"]
    rule_packs = describe_rule_selection(rules_to_load, rules_roots)
    active_rules = load_rule_content(rules_to_load, rules_roots)
    rule_pack_suggestions = suggest_rule_packs(project_root, task_text=task_text)
    impact_before_files = impact_before_files or []
    impact_after_files = impact_after_files or []
    impact_preview = None

    errors = []
    warnings = []

    if freshness.status in {"CRITICAL", "ERROR"}:
        errors.append(f"PLAN.md freshness is {freshness.status}")
    elif freshness.status == "STALE":
        warnings.append("PLAN.md is STALE")

    if not rule_packs["valid"]:
        errors.append(f"Unknown rule packs: {rule_packs['missing']}")

    if risk == "high" and oversight == "auto":
        errors.append("High-risk tasks require oversight != auto")

    warnings.extend(contract_resolution.warnings)
    if contract_resolution.error:
        errors.append(contract_resolution.error)

    _append_suggestion_warnings(warnings, requested_rules, rule_pack_suggestions)
    if impact_before_files or impact_after_files:
        impact_preview = estimate_architecture_impact(
            impact_before_files,
            impact_after_files,
            scope=_infer_scope(requested_rules, rule_pack_suggestions),
            active_rules=requested_rules,
        )
        _append_impact_warnings(warnings, impact_preview, risk, oversight)

    decision_boundary = _evaluate_preconditions(domain_contract, task_text, task_level)
    for check in decision_boundary["preconditions_checked"]:
        if not check["applies"] or check["action"] == "pass":
            continue
        if check["action"] == "analysis_only":
            warnings.append(f"Decision boundary degraded to analysis_only: {check['reason']}")
        elif check["action"] == "restrict_code_generation_and_escalate":
            warnings.append(
                "Decision boundary requires code-generation restriction and escalation: "
                f"{check['reason']}"
            )
        elif check["action"] == "stop":
            errors.append(f"Decision boundary stop: {check['reason']}")    runtime_injection = _evaluate_runtime_injection_snapshot(
        runtime_injection_snapshot,
        task_level=task_level,
        summary_first_active=summary_first_active,
        decision_boundary=decision_boundary,
    )
    consumption_observations = _build_consumption_observations(
        runtime_injection_snapshot,
        domain_contract=domain_contract,
        summary_first_active=summary_first_active,
    )
    for check in runtime_injection["signals_checked"]:
        if not check["triggered"] or check["action"] == "pass":
            continue
        if check["action"] == "analysis_only":
            warnings.append(
                "Runtime injection snapshot degraded to analysis_only: "
                f"{check['reason']}"
            )
        elif check["action"] == "restrict_code_generation_and_escalate":
            warnings.append(
                "Runtime injection snapshot requires escalation: "
                f"{check['reason']}"
            )
        elif check["action"] == "stop":
            errors.append(f"Runtime injection snapshot stop: {check['reason']}")

    for observation in consumption_observations["observations"]:
        if observation.get("observation_status") == "partial":
            warnings.append(
                "Advisory consumption observation: "
                f"{observation['requirement']} is partial via {observation['observable_proxy']}"
            )

    # Tier-aware output
    trace_id = generate_trace_id(task_text, task_level)
    effective_tier = output_tier or get_default_tier(task_level)

    reasoning_fragments: list[dict] = []
    if effective_tier >= OutputTier.TIER2:
        reasoning_fragments = compress_fragments([*errors, *warnings])

    tier3_artifact_ref: str | None = None
    if effective_tier >= OutputTier.TIER3:
        verdict = "fail" if errors else ("warn" if warnings else "pass")
        tiered = TieredOutput(
            verdict=verdict,
            violations=[{"rule_id": "UNKNOWN", "severity": "high", "evidence": e} for e in errors],
            evidence_ids=[],
            trace_id=trace_id,
            task_level=task_level,
            repo_type=str(project_root),
            reasoning_fragments=reasoning_fragments,
            policy_refs=[],
            decision_path=[f"risk={risk}", f"oversight={oversight}", f"rules={rules}"],
        )
        rendered = tiered.render(OutputTier.TIER3)
        tier3_artifact_ref = rendered.get("full_trace_ref")

    result: dict = {
        "ok": len(errors) == 0,
        "project_root": str(project_root),
        "plan_path": str(plan_path),
        "freshness": {
            "status": freshness.status,
            "days_since_update": freshness.days_since_update,
            "threshold_days": freshness.threshold_days,
        },
        "runtime_contract": {
            "rules": requested_rules,
            "risk": risk,
            "oversight": oversight,
            "memory_mode": memory_mode,
        },
        "suggested_rules_preview": rule_pack_suggestions.get("suggested_rules_preview", []),
        "suggested_skills": rule_pack_suggestions.get("suggested_skills", []),
        "suggested_agent": rule_pack_suggestions.get("suggested_agent"),
        "rule_pack_suggestions": rule_pack_suggestions,
        "architecture_impact_preview": impact_preview,
        "rule_packs": rule_packs,
        "active_rules": _strip_rule_content(active_rules, effective_tier),
        "topic_filter": {
            "task_topic": effective_topic,
            "filtered_out": topic_filtered_out,
            "rules_loaded": rules_to_load,
        },
        "contract_resolution": {
            "source": contract_resolution.source,
            "path": str(resolved_contract_file) if resolved_contract_file else None,
            "warnings": contract_resolution.warnings,
            "error": contract_resolution.error,
        },
        "domain_contract": domain_contract,
        "resolved_contract_file": str(resolved_contract_file) if resolved_contract_file else None,
        "summary_first": {
            "active": summary_first_active,
            "task_level": task_level,
            "note": (
                "domain document content skipped; summary will be injected by caller"
                if summary_first_active
                else "full domain contract loaded"
            ),
        },
        "decision_boundary": decision_boundary,
        "runtime_injection": runtime_injection,
        "consumption_observations": consumption_observations,
        "errors": errors,
        "warnings": warnings,
        # Tier-aware fields
        "trace_id": trace_id,
        "output_tier": int(effective_tier),
        "reasoning_fragments": reasoning_fragments,
    }
    if tier3_artifact_ref is not None:
        result["tier3_artifact_ref"] = tier3_artifact_ref
    return result


def format_human_result(result: dict) -> str:
    domain_contract = result.get("domain_contract") or {}
    domain_raw = domain_contract.get("raw") or {}
    contract_label = domain_raw.get("domain") or domain_contract.get("name")
    contract_risk = domain_risk_tier(domain_raw.get("domain") or domain_contract.get("name"))
    lines = [
        "[pre_task_check]",
        f"ok={result['ok']}",
        f"freshness={result['freshness']['status']}",
        f"rules={', '.join(result['runtime_contract']['rules'])}",
    ]
    lines.append(
        build_summary_line(
            f"ok={result['ok']}",
            f"freshness={result['freshness']['status']}",
            f"rules={','.join(result['runtime_contract']['rules'])}",
            (
                f"contract={format_contract_summary_label(contract_label, contract_risk)}"
                if contract_label
                else None
            ),
        )
    )
    preview = result.get("suggested_rules_preview") or []
    if preview:
        lines.append(f"suggested_rules_preview={','.join(preview)}")
    suggested_skills = result.get("suggested_skills") or []
    if suggested_skills:
        lines.append(f"suggested_skills={','.join(suggested_skills)}")
    suggested_agent = result.get("suggested_agent")
    if suggested_agent:
        lines.append(f"suggested_agent={suggested_agent}")
    contract_resolution = result.get("contract_resolution") or {}
    if contract_resolution.get("source"):
        lines.append(f"contract_source={contract_resolution['source']}")
    if contract_resolution.get("path"):
        lines.append(f"contract_path={contract_resolution['path']}")
    if contract_label:
        lines.append(f"contract={contract_label}")
        lines.append(f"contract_risk_tier={contract_risk}")
    impact_preview = result.get("architecture_impact_preview") or {}
    if impact_preview:
        lines.append(f"impact_risk={impact_preview.get('recommended_risk')}")
        lines.append(f"impact_oversight={impact_preview.get('recommended_oversight')}")
        concerns = impact_preview.get("concerns") or []
        if concerns:
            lines.append(f"impact_concerns={','.join(concerns)}")
        validators = impact_preview.get("expected_validators") or []
        if validators:
            lines.append(f"impact_validators={','.join(validators)}")
        evidence = impact_preview.get("required_evidence") or []
        if evidence:
            lines.append(f"impact_evidence={','.join(evidence)}")
    decision_boundary = result.get("decision_boundary") or {}
    if decision_boundary.get("boundary_effect") not in {None, "pass"}:
        lines.append(f"decision_boundary_effect={decision_boundary['boundary_effect']}")
    for check in decision_boundary.get("preconditions_checked", []):
        if check.get("action") != "pass":
            lines.append(
                "precondition: "
                f"{check['type']} action={check['action']} applies={check['applies']} present={check['present']}"
            )    runtime_injection = result.get("runtime_injection") or {}
    snapshot = runtime_injection.get("snapshot") or {}
    if snapshot.get("name"):
        lines.append(f"runtime_injection_snapshot={snapshot['name']}")
    if runtime_injection.get("effect") not in {None, "pass"}:
        lines.append(f"runtime_injection_effect={runtime_injection['effect']}")
    for check in runtime_injection.get("signals_checked", []):
        if check.get("action") != "pass":
            lines.append(
                "runtime_injection: "
                f"{check['signal']} action={check['action']} triggered={check['triggered']}"
            )
            advisory_line = _render_advisory_signal_line(check["signal"])
            if advisory_line:
                lines.append(advisory_line)
    consumption_observations = result.get("consumption_observations") or {}
    for observation in consumption_observations.get("observations", []):
        lines.append(
            "consumption_observation: "
            f"{observation['requirement']} status={observation['observation_status']} "
            f"role={observation['decision_role']} confidence={observation['observation_confidence']}"
        )
        advisory_line = _render_advisory_signal_line(observation["requirement"])
        if advisory_line:
            lines.append(advisory_line)
    for warning in result["warnings"]:
        lines.append(f"warning: {warning}")
    for error in result["errors"]:
        lines.append(f"error: {error}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pre-task governance checks.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--rules", default="common")
    parser.add_argument("--risk", default="medium")
    parser.add_argument("--oversight", default="auto")
    parser.add_argument("--memory-mode", default="candidate")
    parser.add_argument("--task-text", default="")
    parser.add_argument("--impact-before", action="append", default=[])
    parser.add_argument("--impact-after", action="append", default=[])
    parser.add_argument("--contract")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    result = run_pre_task_check(
        Path(args.project_root).resolve(),
        rules=args.rules,
        risk=args.risk,
        oversight=args.oversight,
        memory_mode=args.memory_mode,
        task_text=args.task_text,
        impact_before_files=[Path(path) for path in args.impact_before],
        impact_after_files=[Path(path) for path in args.impact_after],
        contract_file=Path(args.contract).resolve() if args.contract else None,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()











