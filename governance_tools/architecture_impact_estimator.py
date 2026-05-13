#!/usr/bin/env python3
"""
Estimate proposal-time architecture impact from before/after files and active rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.architecture_drift_checker import check_architecture_drift
from governance_tools.public_api_diff_checker import check_public_api_diff


LAYER_PATTERNS = {
    "domain": ("domain", "model", "entity", "entities"),
    "application": ("application", "app", "service", "services", "usecase", "usecases"),
    "interface": ("interface", "interfaces", "api", "controller", "controllers", "adapter", "adapters"),
    "infrastructure": ("infrastructure", "infra", "repository", "repositories", "persistence", "storage"),
    "ui": ("ui", "view", "views", "viewmodel", "viewmodels", "screen", "screens"),
    "platform": ("kernel", "driver", "kmdf", "wdm", "umdf", "native", "interop"),
}


def _detect_layers(paths: list[Path]) -> list[str]:
    detected = []
    for path in paths:
        normalized = path.as_posix().lower()
        parts = tuple(part for part in normalized.split("/") if part)
        for layer, markers in LAYER_PATTERNS.items():
            if any(marker in parts or f"/{marker}/" in normalized for marker in markers):
                if layer not in detected:
                    detected.append(layer)
    return detected


def _boundary_risk(active_rules: list[str], touched_layers: list[str], drift_result: dict) -> str:
    if drift_result.get("errors"):
        return "high"
    if "kernel-driver" in active_rules:
        return "high"
    if len(touched_layers) >= 3:
        return "medium"
    if len(touched_layers) >= 2 or drift_result.get("warnings"):
        return "medium"
    return "low"


def _expected_validators(active_rules: list[str], drift_result: dict, api_result: dict | None) -> list[str]:
    validators = ["architecture_drift_checker"]

    if api_result is not None:
        validators.append("public_api_diff_checker")
    if "refactor" in active_rules:
        validators.append("refactor_evidence_validator")
    if "kernel-driver" in active_rules:
        validators.extend(
            [
                "driver_evidence_validator",
                "test_result_ingestor",
            ]
        )
    if drift_result.get("errors") or drift_result.get("warnings"):
        validators.append("architecture_review")

    deduped = []
    for item in validators:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _required_evidence(active_rules: list[str], drift_result: dict, api_result: dict | None) -> list[str]:
    evidence = ["architecture-review"]

    if "refactor" in active_rules:
        evidence.extend(
            [
                "regression-evidence",
                "interface-stability-evidence",
                "cleanup-or-rollback-evidence",
                "error-path-inventory",
                "error-behavior-diff",
            ]
        )

    if api_result and (api_result.get("removed") or api_result.get("added")):
        evidence.append("public-api-review")

    if "kernel-driver" in active_rules:
        evidence.extend(
            [
                "driver-static-analysis",
                "irql-verification",
                "ioctl-boundary-verification",
            ]
        )

    if drift_result.get("errors") or drift_result.get("warnings"):
        evidence.append("architecture-drift-review")

    deduped = []
    for item in evidence:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _recommended_controls(active_rules: list[str], drift_result: dict, api_result: dict | None) -> dict:
    risk = "medium"
    oversight = "review-required"

    if "kernel-driver" in active_rules:
        risk = "high"
        oversight = "human-approval"
    elif "refactor" in active_rules:
        risk = "medium"
        oversight = "review-required"

    if drift_result.get("errors") or (api_result and api_result.get("removed")):
        risk = "high"
        oversight = "human-approval"

    return {
        "recommended_risk": risk,
        "recommended_oversight": oversight,
    }


def _impact_report(
    *,
    scope: str,
    active_rules: list[str],
    touched_layers: list[str],
    drift_result: dict,
    api_result: dict | None,
    required_evidence: list[str],
    expected_validators: list[str],
    recommended_risk: str,
    recommended_oversight: str,
    concerns: list[str],
) -> dict:
    return {
        "scope": scope,
        "active_rules": active_rules,
        "touched_layers": touched_layers,
        "boundary_risk": _boundary_risk(active_rules, touched_layers, drift_result),
        "concerns": concerns,
        "required_evidence": required_evidence,
        "expected_validators": expected_validators,
        "recommended_risk": recommended_risk,
        "recommended_oversight": recommended_oversight,
        "public_api_diff_present": api_result is not None,
    }


def estimate_architecture_impact(
    before_files: list[Path],
    after_files: list[Path],
    *,
    scope: str = "feature",
    active_rules: list[str] | None = None,
) -> dict:
    active_rules = active_rules or []
    all_files = before_files + after_files
    drift_result = check_architecture_drift(before_files=before_files, after_files=after_files, scope=scope)
    api_result = check_public_api_diff(before_files, after_files) if any(
        path.suffix.lower() in {".cs", ".h", ".hpp", ".hh", ".hxx", ".cpp", ".cc", ".cxx", ".swift"}
        for path in all_files
    ) else None
    touched_layers = _detect_layers(all_files)

    controls = _recommended_controls(active_rules, drift_result, api_result)
    required_evidence = _required_evidence(active_rules, drift_result, api_result)
    expected_validators = _expected_validators(active_rules, drift_result, api_result)

    concerns = []
    if drift_result.get("errors"):
        concerns.append("structural-drift-risk")
    if drift_result.get("warnings"):
        concerns.append("boundary-change-risk")
    if api_result and api_result.get("removed"):
        concerns.append("public-api-break-risk")
    elif api_result and api_result.get("added"):
        concerns.append("public-api-expansion-risk")
    if "refactor" in active_rules:
        concerns.append("error-path-coverage-required")
    if "kernel-driver" in active_rules:
        concerns.append("high-privilege-platform-risk")
    if len(touched_layers) >= 2:
        concerns.append("cross-layer-change-risk")

    impact_report = _impact_report(
        scope=scope,
        active_rules=active_rules,
        touched_layers=touched_layers,
        drift_result=drift_result,
        api_result=api_result,
        required_evidence=required_evidence,
        expected_validators=expected_validators,
        concerns=concerns,
        **controls,
    )

    return {
        "ok": len(drift_result.get("errors", [])) == 0 and not (api_result and api_result.get("removed")),
        "scope": scope,
        "active_rules": active_rules,
        "touched_layers": touched_layers,
        "expected_validators": expected_validators,
        "drift_result": drift_result,
        "public_api_diff": api_result,
        "required_evidence": required_evidence,
        "concerns": concerns,
        "impact_report": impact_report,
        **controls,
    }


def format_human_result(result: dict) -> str:
    lines = [
        f"ok={result['ok']}",
        f"scope={result['scope']}",
        f"recommended_risk={result['recommended_risk']}",
        f"recommended_oversight={result['recommended_oversight']}",
    ]
    touched_layers = result.get("touched_layers") or []
    if touched_layers:
        lines.append(f"touched_layers={','.join(touched_layers)}")
    concerns = result.get("concerns") or []
    if concerns:
        lines.append(f"concerns={','.join(concerns)}")
    validators = result.get("expected_validators") or []
    if validators:
        lines.append(f"expected_validators={','.join(validators)}")
    evidence = result.get("required_evidence") or []
    if evidence:
        lines.append(f"required_evidence={','.join(evidence)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate architecture impact before code is merged.")
    parser.add_argument("--before", action="append", default=[])
    parser.add_argument("--after", action="append", default=[])
    parser.add_argument("--scope", default="feature")
    parser.add_argument("--rules", default="")
    parser.add_argument("--format", choices=["human", "json"], default="json")
    args = parser.parse_args()

    active_rules = [item.strip() for item in args.rules.split(",") if item.strip()]
    result = estimate_architecture_impact(
        [Path(path) for path in args.before],
        [Path(path) for path in args.after],
        scope=args.scope,
        active_rules=active_rules,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
