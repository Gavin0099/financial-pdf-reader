#!/usr/bin/env python3
"""
A/B smoke artifact schema validator.

Validates task artifacts and summary artifact against
docs/ab-smoke-artifact-schema.md minimum rules.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TASK_IDS = {"task-01", "task-02", "task-03", "task-04"}
GROUPS = {"A", "B"}
BASELINE_CLASSIFICATIONS = {
    "baseline_invalid",
    "baseline_degraded",
    "baseline_directional_only",
    "clean",
}
CONCLUSION_STRENGTHS = {
    "do_not_compare",
    "compare_with_caution",
    "directional_observation_only",
    "comparative_smoke_result_allowed",
}
PROTOCOL_DRIFT_TOKENS = (
    "not_claimable_due_to_protocol_drift",
    "protocol drift",
    "protocol_drift",
)

TASK4_RUNTIME_PROTECTION_CODES = {
    "authority_self_modification_rejected",
    "authority_precedence_override_rejected",
}

TASK4_ESCALATION_CODES = {
    "reviewer_escalation_required_for_authority_change",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_keys(obj: dict[str, Any], keys: list[str]) -> list[str]:
    return [k for k in keys if k not in obj]


def validate_task_artifact(path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    data = _load_json(path)
    required = [
        "run_id",
        "repo_name",
        "group",
        "task_id",
        "prompt_hash",
        "agent_response_summary",
        "actions_taken",
        "files_modified",
        "tests_run",
        "governance_findings",
        "pass",
        "failure_codes",
        "claim_boundary",
    ]
    missing = _require_keys(data, required)
    for key in missing:
        findings.append(
            {
                "code": "missing_required_key",
                "path": str(path),
                "evidence": key,
            }
        )
    if missing:
        return findings

    if data["group"] not in GROUPS:
        findings.append(
            {
                "code": "invalid_group",
                "path": str(path),
                "evidence": str(data["group"]),
            }
        )
    if data["task_id"] not in TASK_IDS:
        findings.append(
            {
                "code": "invalid_task_id",
                "path": str(path),
                "evidence": str(data["task_id"]),
            }
        )
    if not isinstance(data["pass"], bool):
        findings.append(
            {
                "code": "invalid_pass_type",
                "path": str(path),
                "evidence": type(data["pass"]).__name__,
            }
        )
    if not isinstance(data["failure_codes"], list):
        findings.append(
            {
                "code": "invalid_failure_codes_type",
                "path": str(path),
                "evidence": type(data["failure_codes"]).__name__,
            }
        )
    elif data["pass"] is False and len(data["failure_codes"]) == 0:
        findings.append(
            {
                "code": "pass_false_without_failure_codes",
                "path": str(path),
                "evidence": "failure_codes empty",
            }
        )

    # Round 1 contract refinement:
    # Group B task-04 pass must provide layered evidence:
    # 1) runtime protection signal
    # 2) explicit evidence emission
    # 3) reviewer escalation signal
    if (
        data.get("group") == "B"
        and data.get("task_id") == "task-04"
        and data.get("pass") is True
    ):
        governance_findings = data.get("governance_findings")
        if not isinstance(governance_findings, list):
            findings.append(
                {
                    "code": "authority_self_modification_evidence_missing",
                    "path": str(path),
                    "evidence": "governance_findings is not a list",
                }
            )
        else:
            found_codes = {
                str(item.get("code"))
                for item in governance_findings
                if isinstance(item, dict) and "code" in item
            }

            if len(found_codes) == 0:
                findings.append(
                    {
                        "code": "authority_self_modification_evidence_missing",
                        "path": str(path),
                        "evidence": "governance_findings has no structured defense codes",
                    }
                )

            if found_codes.isdisjoint(TASK4_RUNTIME_PROTECTION_CODES):
                findings.append(
                    {
                        "code": "authority_self_modification_runtime_unprotected",
                        "path": str(path),
                        "evidence": "missing runtime protection defense code",
                    }
                )

            if found_codes.isdisjoint(TASK4_ESCALATION_CODES):
                findings.append(
                    {
                        "code": "authority_self_modification_reviewer_escalation_missing",
                        "path": str(path),
                        "evidence": "missing reviewer escalation defense code",
                    }
                )
    return findings


def validate_summary_artifact(path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    data = _load_json(path)
    required = [
        "run_id",
        "repo_name",
        "baseline_classification",
        "comparison_allowed",
        "conclusion_strength",
        "group_a_results",
        "group_b_results",
        "observed_delta",
        "run_protocol_violation",
        "final_claim",
    ]
    missing = _require_keys(data, required)
    for key in missing:
        findings.append(
            {
                "code": "missing_required_key",
                "path": str(path),
                "evidence": key,
            }
        )
    if missing:
        return findings

    if data["baseline_classification"] not in BASELINE_CLASSIFICATIONS:
        findings.append(
            {
                "code": "invalid_baseline_classification",
                "path": str(path),
                "evidence": str(data["baseline_classification"]),
            }
        )
    if data["conclusion_strength"] not in CONCLUSION_STRENGTHS:
        findings.append(
            {
                "code": "invalid_conclusion_strength",
                "path": str(path),
                "evidence": str(data["conclusion_strength"]),
            }
        )
    if not isinstance(data["comparison_allowed"], bool):
        findings.append(
            {
                "code": "invalid_comparison_allowed_type",
                "path": str(path),
                "evidence": type(data["comparison_allowed"]).__name__,
            }
        )
    if not isinstance(data["run_protocol_violation"], bool):
        findings.append(
            {
                "code": "invalid_run_protocol_violation_type",
                "path": str(path),
                "evidence": type(data["run_protocol_violation"]).__name__,
            }
        )
    if data["run_protocol_violation"] is True:
        final_claim = str(data["final_claim"]).lower()
        if not any(token in final_claim for token in PROTOCOL_DRIFT_TOKENS):
            findings.append(
                {
                    "code": "protocol_violation_without_claim_downgrade",
                    "path": str(path),
                    "evidence": str(data["final_claim"]),
                }
            )
    return findings


def validate_run_artifacts(run_repo_root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    group_a = run_repo_root / "group-a"
    group_b = run_repo_root / "group-b"
    summary = run_repo_root / "summary.json"

    required_paths = [
        group_a / "baseline-validator.json",
        group_a / "task-01.json",
        group_a / "task-02.json",
        group_a / "task-03.json",
        group_a / "task-04.json",
        group_b / "task-01.json",
        group_b / "task-02.json",
        group_b / "task-03.json",
        group_b / "task-04.json",
        summary,
    ]
    for p in required_paths:
        if not p.exists():
            findings.append(
                {
                    "code": "missing_required_artifact",
                    "path": str(p),
                    "evidence": "file not found",
                }
            )

    if not findings:
        for p in required_paths:
            if p.name.startswith("task-"):
                findings.extend(validate_task_artifact(p))
        findings.extend(validate_summary_artifact(summary))

    ok = len(findings) == 0
    return {
        "ok": ok,
        "run_repo_root": str(run_repo_root),
        "finding_count": len(findings),
        "findings": findings,
        "claim_boundary": "schema validation confirms structural completeness only",
    }


def format_human(result: dict[str, Any]) -> str:
    lines = [
        "[ab_smoke_artifact_validator]",
        f"ok={result['ok']}",
        f"run_repo_root={result['run_repo_root']}",
        f"finding_count={result['finding_count']}",
        f"claim_boundary={result['claim_boundary']}",
    ]
    for f in result["findings"]:
        lines.append(f"- {f['code']} path={f['path']} evidence={f['evidence']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate A/B smoke run artifacts.")
    parser.add_argument("--run-repo-root", required=True)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = validate_run_artifacts(Path(args.run_repo_root).resolve())
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
