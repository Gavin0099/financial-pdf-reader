#!/usr/bin/env python3
"""
Summarize whether an external repo is ready to participate in AI Governance runtime flows.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.agents_calibration_maturity import assess_agents_calibration_maturity
from governance_tools.contract_resolver import resolve_contract
from governance_tools.domain_contract_loader import load_domain_contract
from governance_tools.external_project_facts_intake import build_external_project_facts_intake, default_output_path
from governance_tools.adopt_governance import _discover_plan_path
from governance_tools.framework_versioning import assess_framework_version_status
from governance_tools.governance_drift_checker import check_governance_drift
from governance_tools.hook_install_validator import validate_hook_install
from governance_tools.plan_freshness import check_freshness


@dataclass
class ExternalRepoReadiness:
    ready: bool
    repo_root: str
    checks: dict[str, bool] = field(default_factory=dict)
    contract: dict[str, object] | None = None
    framework_version: dict[str, object] | None = None
    plan: dict[str, object] | None = None
    hooks: dict[str, object] | None = None
    project_facts: dict[str, object] | None = None
    governance_drift: dict[str, object] | None = None
    agents_calibration: dict[str, object] | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _project_facts_remediation_hint(repo_root: Path, status: str) -> str | None:
    base = f"python governance_tools/external_project_facts_intake.py --repo {repo_root}"
    if status in {"missing", "drifted", "intake-error"}:
        return base
    return None


def _project_facts_summary(project_facts: dict | None) -> str | None:
    if not project_facts:
        return None
    return " | ".join(
        [
            f"status={project_facts.get('status')}",
            f"artifact_exists={project_facts.get('artifact_exists')}",
            f"artifact_drift={project_facts.get('artifact_drift')}",
            f"source={project_facts.get('source_filename')}",
        ]
    )


def assess_external_repo(
    repo_root: Path,
    contract_path: str | Path | None = None,
    framework_root: Path | None = None,
) -> ExternalRepoReadiness:
    repo_root = repo_root.resolve()
    checks: dict[str, bool] = {}
    warnings: list[str] = []
    errors: list[str] = []

    checks["git_repo_present"] = (repo_root / ".git").exists()
    if not checks["git_repo_present"]:
        errors.append(f"not a git repo: {repo_root}")
        return ExternalRepoReadiness(
            ready=False,
            repo_root=str(repo_root),
            checks=checks,
            warnings=warnings,
            errors=errors,
        )

    hook_result = validate_hook_install(repo_root, framework_root=framework_root)
    hooks = {
        "valid": hook_result.valid,
        "framework_root": hook_result.framework_root,
        "checks": hook_result.checks,
        "errors": hook_result.errors,
        "warnings": hook_result.warnings,
    }
    # hooks_ready is informational only — hooks are a deployment convenience,
    # not a governance requirement. Missing hooks do NOT block readiness_ready.
    checks["hooks_ready"] = hook_result.valid
    if not hook_result.valid:
        warnings.extend(f"hooks (optional): {item}" for item in hook_result.errors)
    warnings.extend(f"hooks (optional): {item}" for item in hook_result.warnings)

    plan_path = _discover_plan_path(repo_root) or (repo_root / "PLAN.md")
    plan: dict[str, object] | None = None
    if plan_path.exists():
        plan_result = check_freshness(plan_path)
        plan = {
            "path": str(plan_path),
            "status": plan_result.status,
            "days_since_update": plan_result.days_since_update,
            "threshold_days": plan_result.threshold_days,
            "errors": plan_result.errors,
            "warnings": plan_result.warnings,
        }
        checks["plan_present"] = True
        checks["plan_fresh_enough"] = plan_result.status in {"FRESH", "STALE"}
        warnings.extend(f"plan: {item}" for item in plan_result.warnings)
        errors.extend(f"plan: {item}" for item in plan_result.errors)
    else:
        checks["plan_present"] = False
        checks["plan_fresh_enough"] = False
        warnings.append("plan: PLAN.md not found in standard locations (root, governance/, memory/, docs/)")

    resolution = resolve_contract(contract_path, project_root=repo_root)
    contract: dict[str, object] | None = None
    contract_raw: dict[str, object] | None = None
    checks["contract_resolved"] = resolution.path is not None
    if resolution.error:
        errors.append(f"contract: {resolution.error}")
    warnings.extend(f"contract: {item}" for item in resolution.warnings)

    if resolution.path is not None:
        loaded = load_domain_contract(resolution.path)
        missing_docs = [item["path"] for item in loaded["documents"] if not item["exists"]]
        missing_overrides = [item["path"] for item in loaded["ai_behavior_override"] if not item["exists"]]
        missing_validators = [item["path"] for item in loaded["validators"] if not item["exists"]]
        contract_raw = loaded["raw"]
        contract = {
            "source": resolution.source,
            "path": str(resolution.path),
            "name": loaded["name"],
            "domain": contract_raw.get("domain"),
            "plugin_version": contract_raw.get("plugin_version"),
            "documents": len(loaded["documents"]),
            "rule_roots": len(loaded["rule_roots"]),
            "validators": len(loaded["validators"]),
            "missing_documents": missing_docs,
            "missing_behavior_overrides": missing_overrides,
            "missing_validators": missing_validators,
        }
        checks["contract_files_complete"] = not (missing_docs or missing_overrides or missing_validators)
        if missing_docs:
            errors.extend(f"contract: missing document {item}" for item in missing_docs)
        if missing_overrides:
            errors.extend(f"contract: missing behavior override {item}" for item in missing_overrides)
        if missing_validators:
            errors.extend(f"contract: missing validator {item}" for item in missing_validators)
    else:
        checks["contract_files_complete"] = False
        warnings.append("contract: contract.yaml not resolved")

    project_facts: dict[str, object] | None = None
    try:
        facts_payload = build_external_project_facts_intake(repo_root)
        artifact_path = default_output_path(Path(__file__).resolve().parent.parent, repo_root).resolve()
        artifact_exists = artifact_path.exists()
        artifact_sha256 = None
        drift_detected = False
        if artifact_exists:
            try:
                artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                artifact_sha256 = ((artifact_payload.get("fact_source") or {}).get("content_sha256"))
                drift_detected = artifact_sha256 not in (None, facts_payload["fact_source"]["content_sha256"])
                if drift_detected:
                    warnings.append(
                        f"project-facts: intake artifact drift detected ({artifact_path})"
                    )
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"project-facts: unable to read existing intake artifact ({exc})")
        project_facts = {
            "status": "drifted" if drift_detected else "available",
            "available": True,
            "source_file": facts_payload["fact_source"]["source_file"],
            "source_filename": facts_payload["fact_source"]["source_filename"],
            "content_sha256": facts_payload["fact_source"]["content_sha256"],
            "memory_schema_status": facts_payload["memory_schema_status"],
            "missing_logical_names": facts_payload["missing_logical_names"],
            "sync_direction": facts_payload["provenance"]["sync_direction"],
            "artifact_path": str(artifact_path),
            "artifact_exists": artifact_exists,
            "artifact_content_sha256": artifact_sha256,
            "artifact_drift": drift_detected,
            "reason": None,
            "remediation_hint": _project_facts_remediation_hint(repo_root, "drifted" if drift_detected else "available"),
        }
        checks["project_facts_present"] = True
        checks["project_facts_intakeable"] = True
        checks["project_facts_schema_complete"] = facts_payload["memory_schema_status"] == "complete"
        checks["project_facts_drift_free"] = not drift_detected
        if facts_payload["memory_schema_status"] == "partial":
            warnings.append(
                "project-facts: intake succeeded with partial memory schema; missing logical file(s): "
                + ", ".join(facts_payload["missing_logical_names"])
            )
    except FileNotFoundError as exc:
        checks["project_facts_present"] = False
        checks["project_facts_intakeable"] = False
        checks["project_facts_schema_complete"] = False
        checks["project_facts_drift_free"] = False
        project_facts = {
            "status": "missing",
            "available": False,
            "reason": str(exc),
            "remediation_hint": _project_facts_remediation_hint(repo_root, "missing"),
        }
        warnings.append(f"project-facts: {exc}")
    except Exception as exc:
        checks["project_facts_present"] = True
        checks["project_facts_intakeable"] = False
        checks["project_facts_schema_complete"] = False
        checks["project_facts_drift_free"] = False
        project_facts = {
            "status": "intake-error",
            "available": False,
            "reason": str(exc),
            "remediation_hint": _project_facts_remediation_hint(repo_root, "missing"),
        }
        warnings.append(f"project-facts: intake failed ({exc})")

    drift_result = check_governance_drift(repo_root, framework_root=framework_root, skip_hash=False)
    governance_drift: dict[str, object] = {
        "severity": drift_result.severity,
        "baseline_version": drift_result.baseline_version,
        "framework_version": drift_result.framework_version,
        "checks": drift_result.checks,
        "findings": drift_result.findings,
        "remediation_hints": drift_result.remediation_hints,
    }
    checks["governance_baseline_present"] = drift_result.checks.get("baseline_yaml_present", False)
    checks["governance_drift_clean"] = drift_result.severity == "ok"
    for item in drift_result.errors:
        warnings.append(f"governance-drift: {item}")
    for item in drift_result.warnings:
        warnings.append(f"governance-drift: {item}")

    agents_calibration_result = assess_agents_calibration_maturity(repo_root)
    agents_calibration = agents_calibration_result.to_dict()
    if agents_calibration_result.status in {"scaffold_only", "generic_filled"}:
        warnings.append(
            "agents-calibration: "
            f"AGENTS.md maturity is {agents_calibration_result.status}"
            f" ({agents_calibration_result.reason})"
        )

    version_status = assess_framework_version_status(repo_root, contract_raw=contract_raw)
    framework_version = {
        "current_release": version_status.current_release,
        "adopted_release": version_status.adopted_release,
        "adopted_commit": version_status.adopted_commit,
        "framework_repo": version_status.framework_repo,
        "canonical_framework_repo": version_status.canonical_framework_repo,
        "framework_interface_version": version_status.framework_interface_version,
        "compatibility_range": version_status.compatibility_range,
        "lock_file": version_status.lock_file,
        "state": version_status.state,
        "reasons": version_status.reasons,
    }
    checks["framework_version_known"] = version_status.adopted_release is not None
    checks["framework_version_current"] = version_status.state in {"current", "ahead"}
    checks["framework_release_compatible"] = version_status.state != "incompatible"
    checks["framework_source_canonical"] = (
        version_status.framework_repo is not None
        and version_status.framework_repo.rstrip("/") == version_status.canonical_framework_repo.rstrip("/")
    )
    if version_status.state == "incompatible":
        errors.extend(
            f"framework-version: {item}" for item in (version_status.reasons or ["framework release is incompatible"])
        )
    elif version_status.reasons:
        warnings.extend(f"framework-version: {item}" for item in version_status.reasons)

    ready = (
        checks["git_repo_present"]
        and checks["plan_fresh_enough"]
        and checks["contract_resolved"]
        and checks["contract_files_complete"]
        and checks["framework_release_compatible"]
        # hooks_ready intentionally excluded: hooks are a deployment convenience,
        # not a governance gate. A repo with clean governance but no hooks installed
        # is governance-ready. Use checks["hooks_ready"] for hook-specific reporting.
    )

    return ExternalRepoReadiness(
        ready=ready,
        repo_root=str(repo_root),
        checks=checks,
        contract=contract,
        framework_version=framework_version,
        plan=plan,
        hooks=hooks,
        project_facts=project_facts,
        governance_drift=governance_drift,
        agents_calibration=agents_calibration,
        warnings=warnings,
        errors=errors,
    )


def format_human(result: ExternalRepoReadiness) -> str:
    lines = [
        "External Repo Readiness",
        "",
        f"ready              = {result.ready}",
        f"repo_root          = {result.repo_root}",
        f"project_facts      = {_project_facts_summary(result.project_facts)}",
        "",
        "[checks]",
    ]
    for key in sorted(result.checks):
        lines.append(f"{key:<24} = {result.checks[key]}")

    # governance_drift is the authoritative compliance check — surface it before
    # per-tool details so users see drift findings immediately after the check list.
    if result.governance_drift:
        lines.extend(
            [
                "",
                "[governance_drift]  ← authoritative governance compliance check",
                f"severity           = {result.governance_drift.get('severity')}",
                f"baseline_version   = {result.governance_drift.get('baseline_version')}",
            ]
        )
        for finding in result.governance_drift.get("findings") or []:
            lines.append(f"  [{finding['severity']}] {finding['check']}: {finding['detail']}")
        for hint in result.governance_drift.get("remediation_hints") or []:
            lines.append(f"  hint: {hint}")

    if result.contract:
        lines.extend(
            [
                "",
                "[contract]",
                f"source             = {result.contract.get('source')}",
                f"path               = {result.contract.get('path')}",
                f"name               = {result.contract.get('name')}",
                f"domain             = {result.contract.get('domain')}",
                f"plugin_version     = {result.contract.get('plugin_version')}",
                f"documents          = {result.contract.get('documents')}",
                f"rule_roots         = {result.contract.get('rule_roots')}",
                f"validators         = {result.contract.get('validators')}",
            ]
        )

    if result.framework_version:
        lines.extend(
            [
                "",
                "[framework_version]",
                f"state              = {result.framework_version.get('state')}",
                f"current_release    = {result.framework_version.get('current_release')}",
                f"adopted_release    = {result.framework_version.get('adopted_release')}",
                f"adopted_commit     = {result.framework_version.get('adopted_commit')}",
                f"framework_repo     = {result.framework_version.get('framework_repo')}",
                f"canonical_repo     = {result.framework_version.get('canonical_framework_repo')}",
                f"interface_version  = {result.framework_version.get('framework_interface_version')}",
                f"compatible_range   = {result.framework_version.get('compatibility_range')}",
                f"lock_file          = {result.framework_version.get('lock_file')}",
            ]
        )

    if result.plan:
        lines.extend(
            [
                "",
                "[plan]",
                f"status             = {result.plan.get('status')}",
                f"days_since_update  = {result.plan.get('days_since_update')}",
                f"threshold_days     = {result.plan.get('threshold_days')}",
            ]
        )

    if result.hooks:
        lines.extend(
            [
                "",
                "[hooks]",
                f"valid              = {result.hooks.get('valid')}",
                f"framework_root     = {result.hooks.get('framework_root')}",
            ]
        )

    if result.project_facts:
        lines.extend(
            [
                "",
                "[project_facts]",
                f"status             = {result.project_facts.get('status')}",
                f"available          = {result.project_facts.get('available')}",
                f"source_file        = {result.project_facts.get('source_file')}",
                f"source_filename    = {result.project_facts.get('source_filename')}",
                f"schema_status      = {result.project_facts.get('memory_schema_status')}",
                f"missing_logical    = {result.project_facts.get('missing_logical_names')}",
                f"sync_direction     = {result.project_facts.get('sync_direction')}",
                f"artifact_path      = {result.project_facts.get('artifact_path')}",
                f"artifact_exists    = {result.project_facts.get('artifact_exists')}",
                f"artifact_drift     = {result.project_facts.get('artifact_drift')}",
                f"reason             = {result.project_facts.get('reason')}",
                f"remediation_hint   = {result.project_facts.get('remediation_hint')}",
            ]
        )

    if result.agents_calibration:
        lines.extend(
            [
                "",
                "[agents_calibration]",
                f"status             = {result.agents_calibration.get('status')}",
                f"reason             = {result.agents_calibration.get('reason')}",
                f"path               = {result.agents_calibration.get('path')}",
                f"reviewer_signal    = {result.agents_calibration.get('reviewer_signal')}",
            ]
        )
        repo_specific_signals = result.agents_calibration.get("repo_specific_signals") or []
        if repo_specific_signals:
            lines.append(f"repo_specific_signals = {repo_specific_signals}")
        next_questions = result.agents_calibration.get("next_questions") or []
        if next_questions:
            lines.append("next_questions:")
            for item in next_questions:
                lines.append(f"- {item}")

    if result.errors:
        lines.append("")
        lines.append(f"errors: {len(result.errors)}")
        for item in result.errors:
            lines.append(f"- {item}")

    if result.warnings:
        lines.append("")
        lines.append(f"warnings: {len(result.warnings)}")
        for item in result.warnings:
            lines.append(f"- {item}")

    # Surface schema reference when contract or plan schema errors are present
    schema_items = [
        e for e in (result.errors or []) + (result.warnings or [])
        if e.startswith(("contract:", "plan:"))
    ]
    if schema_items:
        lines.extend([
            "",
            "reference: docs/minimum-legal-schema.md",
            "  — minimum valid form of each governance file, field semantics,",
            "    and which False states are non-blocking by design",
        ])

    return "\n".join(lines)


def format_json(result: ExternalRepoReadiness) -> str:
    return json.dumps(
        {
            "ready": result.ready,
            "repo_root": result.repo_root,
            "checks": result.checks,
            "contract": result.contract,
            "framework_version": result.framework_version,
            "plan": result.plan,
            "hooks": result.hooks,
            "project_facts": result.project_facts,
            "governance_drift": result.governance_drift,
            "agents_calibration": result.agents_calibration,
            "errors": result.errors,
            "warnings": result.warnings,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assess whether an external repo is ready for AI Governance integration."
    )
    parser.add_argument("--repo", default=".", help="Target repo root.")
    parser.add_argument("--contract", help="Optional explicit contract.yaml path.")
    parser.add_argument("--framework-root", help="Optional explicit framework root for hook validation.")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = assess_external_repo(
        Path(args.repo),
        contract_path=args.contract,
        framework_root=Path(args.framework_root) if args.framework_root else None,
    )
    if args.format == "json":
        print(format_json(result))
    else:
        print(format_human(result))
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
