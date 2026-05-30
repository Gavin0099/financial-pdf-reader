#!/usr/bin/env python3
"""
Runtime post-task governance checks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from governance_tools.contract_validator import validate_contract
from governance_tools.decision_model_loader import policy_precedence_rows, required_evidence_kinds, violation_verdict_impact
from governance_tools.contract_resolver import resolve_contract
from governance_tools.domain_governance_metadata import domain_risk_tier
from governance_tools.domain_contract_loader import load_domain_contract
from governance_tools.domain_validator_loader import build_domain_validation_payload, run_domain_validators
from governance_tools.driver_evidence_validator import validate_driver_evidence
from governance_tools.failure_completeness_validator import validate_failure_completeness
from governance_tools.public_api_diff_checker import check_public_api_diff
from governance_tools.refactor_evidence_validator import validate_refactor_evidence
from governance_tools.rule_pack_loader import available_rule_packs, describe_rule_selection, parse_rule_list
from memory_pipeline.session_snapshot import create_session_snapshot
from runtime_hooks.core.human_summary import build_summary_line, format_contract_summary_label

PUBLIC_API_DIFF_REQUIRED_KEYS = {
    "ok",
    "removed",
    "added",
    "compatibility_risk",
    "breaking_changes",
    "non_breaking_changes",
    "warnings",
    "errors",
}

ADVISORY_SIGNAL_METADATA = {
    "missing_required_evidence": {
        "signal_name": "required_evidence_missing",
        "signal_class": "evidence_advisory",
        "decision_distance": "enforced_elsewhere",
        "summary": "required evidence is incomplete for this decision surface",
        "non_proof": "not behavioral compliance proof",
        "usage": "already handled by evidence-driven escalation or stop logic",
    }
}


def _merge_runtime_checks(errors: list[str], warnings: list[str], checks: dict | None) -> None:
    if not checks:
        return

    for warning in checks.get("warnings", []):
        warnings.append(f"runtime-check: {warning}")

    for error in checks.get("errors", []):
        errors.append(f"runtime-check: {error}")


def _merge_refactor_evidence_checks(errors: list[str], warnings: list[str], checks: dict | None, rules: list[str]) -> dict | None:
    if "refactor" not in rules:
        return None

    result = validate_refactor_evidence(checks)
    for warning in result["warnings"]:
        warnings.append(f"refactor-evidence: {warning}")
    for error in result["errors"]:
        errors.append(f"refactor-evidence: {error}")
    return result


def _validate_public_api_diff_schema(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return "public-api-diff evidence must be an object"

    missing_keys = sorted(PUBLIC_API_DIFF_REQUIRED_KEYS - set(payload))
    if missing_keys:
        return f"public-api-diff evidence missing keys: {missing_keys}"

    if not isinstance(payload.get("ok"), bool):
        return "public-api-diff evidence field 'ok' must be a boolean"

    for key in ("removed", "added", "breaking_changes", "non_breaking_changes", "warnings", "errors"):
        if not isinstance(payload.get(key), list):
            return f"public-api-diff evidence field '{key}' must be a list"

    if not isinstance(payload.get("compatibility_risk"), str):
        return "public-api-diff evidence field 'compatibility_risk' must be a string"

    return None


def _merge_public_api_diff_checks(
    errors: list[str],
    warnings: list[str],
    checks: dict | None,
    rules: list[str],
    api_before_files: list[Path] | None,
    api_after_files: list[Path] | None,
) -> dict | None:
    if "refactor" not in rules:
        return None

    result = None
    if checks and "public_api_diff" in checks:
        schema_error = _validate_public_api_diff_schema(checks["public_api_diff"])
        if schema_error:
            return None
        result = checks["public_api_diff"]
    elif api_before_files and api_after_files:
        result = check_public_api_diff(api_before_files, api_after_files)
    else:
        return None

    for warning in result.get("warnings", []):
        warnings.append(f"public-api-diff: {warning}")
    for error in result.get("errors", []):
        errors.append(f"public-api-diff: {error}")
    return result


def _merge_failure_completeness_checks(errors: list[str], warnings: list[str], checks: dict | None, rules: list[str]) -> dict | None:
    if not checks:
        return None

    result = validate_failure_completeness(checks, require_cleanup=("refactor" in rules))
    for warning in result["warnings"]:
        warnings.append(f"failure-completeness: {warning}")
    for error in result["errors"]:
        errors.append(f"failure-completeness: {error}")
    return result


def _merge_driver_evidence_checks(errors: list[str], warnings: list[str], checks: dict | None, rules: list[str]) -> dict | None:
    if "kernel-driver" not in rules:
        return None

    result = validate_driver_evidence(checks)
    for warning in result["warnings"]:
        warnings.append(f"driver-evidence: {warning}")
    for error in result["errors"]:
        errors.append(f"driver-evidence: {error}")
    return result


def _observed_runtime_evidence_kinds(
    checks: dict | None,
    *,
    public_api_diff: dict | None,
    driver_evidence: dict | None,
    domain_validator_results: list[dict],
) -> set[str]:
    observed = set(str(kind) for kind in (checks or {}).get("evidence_kinds", []) if str(kind).strip())
    if checks and "public_api_diff" in checks:
        observed.add("public-api-diff")
    elif public_api_diff is not None:
        observed.add("public-api-diff")
    if driver_evidence and driver_evidence.get("ok"):
        observed.add("sdv-text")
    if domain_validator_results:
        observed.add("domain-validator-result")
    return observed


def _classify_invalid_evidence_schema(checks: dict | None) -> list[dict]:
    if not checks or "public_api_diff" not in checks:
        return []

    schema_error = _validate_public_api_diff_schema(checks["public_api_diff"])
    if not schema_error:
        return []

    return [
        {
            "violation_type": "invalid_evidence_schema",
            "evidence_kind": "public-api-diff",
            "detected_by": "runtime evidence validator",
            "verdict_impact": violation_verdict_impact("invalid_evidence_schema", "stop"),
            "message": f"Invalid runtime evidence schema: public-api-diff ({schema_error})",
        }
    ]


def _classify_policy_conflicts(checks: dict | None) -> list[dict]:
    if not checks:
        return []

    policy_conflicts = checks.get("policy_conflicts") or []
    if not isinstance(policy_conflicts, list):
        return []

    precedence_rows = policy_precedence_rows()
    violations = []
    for item in policy_conflicts:
        if not isinstance(item, dict):
            continue
        policy_type = str(item.get("policy_type", "")).strip()
        override_target = str(item.get("override_target", "")).strip()
        scope = str(item.get("scope", "")).strip()
        if not policy_type or not override_target:
            continue

        matched_row = next(
            (
                row
                for row in precedence_rows
                if str(row.get("policy_type")) == policy_type
                and str(row.get("override_target")) == override_target
            ),
            None,
        )

        if matched_row is None:
            violations.append(
                {
                    "violation_type": "policy_conflict",
                    "policy_type": policy_type,
                    "override_target": override_target,
                    "scope": scope,
                    "detected_by": "policy precedence resolver",
                    "verdict_impact": violation_verdict_impact("policy_conflict", "escalate"),
                    "message": f"Unresolved runtime policy conflict: {policy_type} -> {override_target}",
                }
            )
            continue

        if matched_row.get("allowed") is False:
            violations.append(
                {
                    "violation_type": "illegal_override",
                    "policy_type": policy_type,
                    "override_target": override_target,
                    "scope": scope or str(matched_row.get("scope", "")),
                    "detected_by": "ownership and precedence validator",
                    "verdict_impact": violation_verdict_impact("illegal_override", "stop"),
                    "message": f"Illegal runtime policy override: {policy_type} -> {override_target}",
                }
            )
            continue

        violations.append(
            {
                "violation_type": "policy_conflict",
                "policy_type": policy_type,
                "override_target": override_target,
                "scope": scope or str(matched_row.get("scope", "")),
                "detected_by": "policy precedence resolver",
                "verdict_impact": violation_verdict_impact("policy_conflict", "escalate"),
                "message": (
                    f"Runtime policy conflict requires precedence resolution: {policy_type} -> {override_target} "
                    f"({matched_row.get('conflict_resolution')})"
                ),
            }
        )
    return violations


def _classify_domain_policy_inputs(
    results: list[dict],
    *,
    hard_stop_rules: set[str],
) -> list[dict]:
    if not hard_stop_rules:
        return []

    policy_inputs = []
    for item in results:
        matched_rule_ids = sorted(set(str(rule_id) for rule_id in item.get("rule_ids", [])) & hard_stop_rules)
        if not matched_rule_ids:
            continue
        for violation in item.get("violations", []):
            policy_inputs.append(
                {
                    "violation_type": "domain_contract_violation",
                    "policy_type": "domain-contract policy",
                    "override_target": "runtime default verdict",
                    "source": "hard_stop_rules",
                    "validator": item.get("name"),
                    "rule_ids": matched_rule_ids,
                    "detected_by": "domain validator",
                    "verdict_impact": violation_verdict_impact("domain_contract_violation", "stop"),
                    "message": (
                        f"Domain policy stop requested by hard_stop_rules: {item.get('name')} -> {violation} "
                        f"(rules: {','.join(matched_rule_ids)})"
                    ),
                }
            )
    return policy_inputs


def _classify_missing_required_evidence(
    checks: dict | None,
    *,
    public_api_diff: dict | None,
    driver_evidence: dict | None,
    domain_validator_results: list[dict],
) -> list[dict]:
    declared_required = [
        str(kind)
        for kind in (checks or {}).get("required_runtime_evidence", [])
        if str(kind).strip()
    ]
    if not declared_required:
        return []

    known_required = required_evidence_kinds()
    observed = _observed_runtime_evidence_kinds(
        checks,
        public_api_diff=public_api_diff,
        driver_evidence=driver_evidence,
        domain_validator_results=domain_validator_results,
    )
    violations = []
    for evidence_kind in declared_required:
        if evidence_kind not in known_required:
            continue
        if evidence_kind in observed:
            continue
        violations.append(
            {
                "violation_type": "missing_required_evidence",
                "evidence_kind": evidence_kind,
                "detected_by": "runtime evidence validator",
                "verdict_impact": violation_verdict_impact("missing_required_evidence", "escalate"),
                "message": f"Missing required runtime evidence: {evidence_kind}",
            }
        )
    return violations


def _slim_domain_contract(dc: dict | None) -> dict | None:
    """Return domain_contract with document content elided for the return payload.

    Design principle:
        Heavy execution context may be used during validation, but must not be
        echoed back in return payloads unless it remains semantically necessary
        after execution completes.

    Concretely:
        - run_domain_validators() receives the full domain_contract (full content).
        - The return dict does NOT need file content — callers care about
          domain_validator_results, rule_packs, ok/errors/warnings, not the raw
          document text that was already consumed.
        - content_char_count preserves debuggability: callers can still tell
          whether original content was present and how large it was.

    IMPORTANT: Do not pass the return value of this function back into any
    execution path (validators, build_domain_validation_payload, etc.).  It is
    report-only.
    """
    if dc is None:
        return None

    def _slim_entry(entry: dict) -> dict:
        content = entry.get("content", "")
        slim = dict(entry)
        slim["content"] = ""
        slim["content_elided_for_return"] = True
        slim["content_char_count"] = len(content)
        return slim

    slim = dict(dc)
    slim["documents"] = [_slim_entry(d) for d in dc.get("documents", [])]
    slim["ai_behavior_override"] = [_slim_entry(d) for d in dc.get("ai_behavior_override", [])]
    return slim


def _domain_hard_stop_rules(domain_contract: dict | None) -> set[str]:
    raw = (domain_contract or {}).get("raw") or {}
    values = raw.get("hard_stop_rules") or []
    if isinstance(values, list):
        return {str(value) for value in values if str(value).strip()}
    if values:
        return {str(values)}
    return set()


def _merge_domain_validator_results(
    errors: list[str],
    warnings: list[str],
    results: list[dict],
) -> None:
    for item in results:
        for warning in item.get("warnings", []):
            warnings.append(f"domain-validator:{item['name']}: {warning}")
        for violation in item.get("violations", []):
            warnings.append(f"domain-validator:{item['name']}: {violation}")
        for error in item.get("errors", []):
            errors.append(f"domain-validator:{item['name']}: {error}")


def run_post_task_check(
    response_text: str,
    risk: str,
    oversight: str,
    memory_mode: str | None = None,
    memory_root: Path | None = None,
    snapshot_task: str | None = None,
    snapshot_summary: str | None = None,
    create_snapshot: bool = False,
    checks: dict | None = None,
    api_before_files: list[Path] | None = None,
    api_after_files: list[Path] | None = None,
    contract_file: Path | None = None,
    project_root: Path | None = None,
    evidence_paths: list[Path] | None = None,
) -> dict:
    contract_resolution = resolve_contract(
        contract_file,
        project_root=project_root,
        extra_paths=evidence_paths,
    )
    resolved_contract_file = contract_resolution.path
    domain_contract = load_domain_contract(resolved_contract_file) if resolved_contract_file else None
    contract_rules_roots = [Path(path) for path in domain_contract.get("rule_roots", [])] if domain_contract else []
    available_rules = available_rule_packs(contract_rules_roots + [Path(__file__).resolve().parents[2] / "governance" / "rules"])
    validation = validate_contract(response_text, available_rules=available_rules if domain_contract else None)
    errors = list(validation.errors)
    warnings = list(validation.warnings)
    fields = validation.fields
    resolved_memory_mode = memory_mode or fields.get("MEMORY_MODE", "").strip() or "candidate"
    resolved_rules = parse_rule_list(fields.get("RULES", ""))
    snapshot_result = None
    effective_checks = dict(checks or {})

    if not validation.contract_found:
        errors.append("Missing governance contract in task output")

    if risk == "high" and oversight == "auto":
        errors.append("High-risk task completed without required oversight")

    if resolved_memory_mode == "durable" and oversight == "auto":
        errors.append("Durable memory requires oversight != auto")

    if resolved_memory_mode == "durable" and oversight == "review-required":
        warnings.append("Durable memory should typically be promoted after explicit review completion")
    warnings.extend(contract_resolution.warnings)
    if contract_resolution.error:
        errors.append(contract_resolution.error)

    if domain_contract:
        rules_roots = contract_rules_roots + [Path(__file__).resolve().parents[2] / "governance" / "rules"]
        resolved_rule_packs = describe_rule_selection(resolved_rules, rules_roots)
        if not resolved_rule_packs["valid"]:
            errors.append(f"Unknown rule packs: {resolved_rule_packs['missing']}")
    else:
        resolved_rule_packs = None

    _merge_runtime_checks(errors, warnings, effective_checks)
    public_api_diff = _merge_public_api_diff_checks(
        errors,
        warnings,
        effective_checks,
        resolved_rules,
        api_before_files,
        api_after_files,
    )
    if public_api_diff:
        effective_checks["public_api_diff"] = public_api_diff
        effective_checks["interface_stability_verified"] = public_api_diff.get("ok", False)
    failure_completeness = _merge_failure_completeness_checks(errors, warnings, effective_checks, resolved_rules)
    refactor_evidence = _merge_refactor_evidence_checks(errors, warnings, effective_checks, resolved_rules)
    driver_evidence = _merge_driver_evidence_checks(errors, warnings, effective_checks, resolved_rules)
    domain_validator_results = []
    domain_hard_stop_rules = _domain_hard_stop_rules(domain_contract)
    if domain_contract:
        domain_payload = build_domain_validation_payload(
            response_text=response_text,
            checks=effective_checks,
            fields=fields,
            resolved_rules=resolved_rules,
            domain_contract=domain_contract,
            contract_file=resolved_contract_file,
        )
        domain_validator_results = run_domain_validators(
            contract_file=resolved_contract_file,
            payload=domain_payload,
            active_rule_ids=resolved_rules,
        )
        _merge_domain_validator_results(
            errors,
            warnings,
            domain_validator_results,
        )
    evidence_violations = _classify_invalid_evidence_schema(effective_checks)
    evidence_violations.extend(
        _classify_missing_required_evidence(
            effective_checks,
            public_api_diff=public_api_diff,
            driver_evidence=driver_evidence,
            domain_validator_results=domain_validator_results,
        )
    )
    policy_violations = _classify_policy_conflicts(effective_checks)
    policy_violations.extend(
        _classify_domain_policy_inputs(
            domain_validator_results,
            hard_stop_rules=domain_hard_stop_rules,
        )
    )
    for violation in evidence_violations:
        errors.append(f"runtime-evidence: {violation['message']}")
    for violation in policy_violations:
        errors.append(f"runtime-policy: {violation['message']}")

    if create_snapshot and validation.contract_found and validation.compliant and not errors:
        if memory_root is None:
            errors.append("Snapshot creation requested without memory_root")
        else:
            snapshot_result = create_session_snapshot(
                memory_root=memory_root,
                task=snapshot_task or fields.get("PLAN", "unspecified-task"),
                summary=snapshot_summary or "Post-task candidate memory snapshot",
                source_text=response_text,
                risk=risk,
                oversight=oversight,
            )

    return {
        "ok": validation.contract_found and validation.compliant and len(errors) == 0,
        "contract_found": validation.contract_found,
        "compliant": validation.compliant,
        "fields": fields,
        "memory_mode": resolved_memory_mode,
        "rules": resolved_rules,
        "snapshot": snapshot_result,
        "checks": effective_checks if effective_checks else None,
        "resolved_contract_file": str(resolved_contract_file) if resolved_contract_file else None,
        "contract_resolution": {
            "source": contract_resolution.source,
            "path": str(resolved_contract_file) if resolved_contract_file else None,
            "warnings": contract_resolution.warnings,
            "error": contract_resolution.error,
        },
        "public_api_diff": public_api_diff,
        "failure_completeness": failure_completeness,
        "refactor_evidence": refactor_evidence,
        "driver_evidence": driver_evidence,
        "evidence_violations": evidence_violations,
        "policy_violations": policy_violations,
        "domain_validator_results": domain_validator_results,
        "domain_hard_stop_rules": sorted(domain_hard_stop_rules),
        "domain_contract": _slim_domain_contract(domain_contract),
        "rule_packs": resolved_rule_packs,
        "errors": errors,
        "warnings": warnings,
    }


def _render_advisory_violation_line(violation: dict) -> str | None:
    metadata = ADVISORY_SIGNAL_METADATA.get(violation.get("violation_type"))
    if not metadata:
        return None
    return (
        f"advisory_signal: {metadata['signal_name']} -> "
        f"{metadata['signal_class']}; "
        f"{metadata['summary']}; "
        f"decision distance={metadata['decision_distance']}; "
        f"{metadata['non_proof']}; "
        f"{metadata['usage']}"
    )


def format_human_result(result: dict) -> str:
    domain_contract = result.get("domain_contract") or {}
    domain_raw = domain_contract.get("raw") or {}
    contract_label = domain_raw.get("domain") or domain_contract.get("name")
    contract_risk = domain_risk_tier(domain_raw.get("domain") or domain_contract.get("name"))
    lines = [
        "[post_task_check]",
        f"ok={result['ok']}",
        f"contract_found={result['contract_found']}",
        f"compliant={result['compliant']}",
        f"memory_mode={result['memory_mode']}",
    ]
    lines.append(
        build_summary_line(
            f"ok={result['ok']}",
            f"compliant={result['compliant']}",
            f"memory_mode={result['memory_mode']}",
            (
                f"contract={format_contract_summary_label(contract_label, contract_risk)}"
                if contract_label
                else None
            ),
        )
    )
    if result["snapshot"]:
        lines.append(f"snapshot={result['snapshot']['snapshot_path']}")
    if result["public_api_diff"]:
        lines.append(f"public_api_removed={len(result['public_api_diff']['removed'])}")
        lines.append(f"public_api_added={len(result['public_api_diff']['added'])}")
        lines.append(f"public_api_ok={result['public_api_diff']['ok']}")
    if result["failure_completeness"] is not None:
        lines.append(f"failure_completeness_ok={result['failure_completeness']['ok']}")
    if result["refactor_evidence"] is not None:
        lines.append(f"refactor_evidence_ok={result['refactor_evidence']['ok']}")
    if result["driver_evidence"] is not None:
        lines.append(f"driver_evidence_ok={result['driver_evidence']['ok']}")
    if result.get("evidence_violations"):
        lines.append(f"evidence_violation_count={len(result['evidence_violations'])}")
        for violation in result["evidence_violations"]:
            advisory_line = _render_advisory_violation_line(violation)
            if advisory_line:
                lines.append(advisory_line)
    if result.get("policy_violations"):
        lines.append(f"policy_violation_count={len(result['policy_violations'])}")
    if result.get("domain_validator_results"):
        lines.append(f"domain_validator_count={len(result['domain_validator_results'])}")
    if result.get("domain_hard_stop_rules"):
        lines.append(f"domain_hard_stop_rules={','.join(result['domain_hard_stop_rules'])}")
    contract_resolution = result.get("contract_resolution") or {}
    if contract_resolution.get("source"):
        lines.append(f"contract_source={contract_resolution['source']}")
    if contract_resolution.get("path"):
        lines.append(f"contract_path={contract_resolution['path']}")
    if contract_label:
        lines.append(f"contract={contract_label}")
        lines.append(f"contract_risk_tier={contract_risk}")
    if result.get("domain_contract"):
        lines.append(f"domain_contract={result['domain_contract']['name']}")
    for warning in result["warnings"]:
        lines.append(f"warning: {warning}")
    for error in result["errors"]:
        lines.append(f"error: {error}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run post-task governance checks.")
    parser.add_argument("--file", "-f", help="Response file; defaults to stdin")
    parser.add_argument("--risk", default="medium")
    parser.add_argument("--oversight", default="auto")
    parser.add_argument("--memory-mode")
    parser.add_argument("--memory-root")
    parser.add_argument("--snapshot-task")
    parser.add_argument("--snapshot-summary")
    parser.add_argument("--create-snapshot", action="store_true")
    parser.add_argument("--checks-file")
    parser.add_argument("--api-before", action="append", default=[])
    parser.add_argument("--api-after", action="append", default=[])
    parser.add_argument("--project-root")
    parser.add_argument("--contract")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    if args.file:
        response_text = Path(args.file).read_text(encoding="utf-8")
    else:
        response_text = sys.stdin.read()

    checks = json.loads(Path(args.checks_file).read_text(encoding="utf-8")) if args.checks_file else None

    result = run_post_task_check(
        response_text,
        risk=args.risk,
        oversight=args.oversight,
        memory_mode=args.memory_mode,
        memory_root=Path(args.memory_root) if args.memory_root else None,
        snapshot_task=args.snapshot_task,
        snapshot_summary=args.snapshot_summary,
        create_snapshot=args.create_snapshot,
        checks=checks,
        api_before_files=[Path(path) for path in args.api_before],
        api_after_files=[Path(path) for path in args.api_after],
        project_root=Path(args.project_root).resolve() if args.project_root else None,
        evidence_paths=[Path(path).resolve() for path in [args.file, args.checks_file] if path],
        contract_file=Path(args.contract).resolve() if args.contract else None,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
