#!/usr/bin/env python3
"""
Validate evidence required by refactor governance rules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from governance_tools.validator_interface import DomainValidator, ValidatorResult


REGRESSION_PATTERNS = [
    r"regression",
    r"characterization",
    r"behavior[_\- ]?lock",
    r"contract",
    r"compat",
]

INTERFACE_STABILITY_PATTERNS = [
    r"interface",
    r"signature",
    r"contract",
    r"public[_\- ]?api",
    r"compat",
    r"callback",
]

CLEANUP_PATTERNS = [
    r"rollback",
    r"cleanup",
    r"clean[_\- ]?up",
    r"dispose",
    r"release",
    r"revert",
]


def _normalize_names(test_names: list[str] | None) -> list[str]:
    return [str(name).strip().lower() for name in (test_names or []) if str(name).strip()]


def _has_pattern(values: list[str], patterns: list[str]) -> bool:
    return any(re.search(pattern, value, re.IGNORECASE) for value in values for pattern in patterns)


def _get_check_value(checks: dict, *names: str):
    for name in names:
        if name in checks:
            return checks[name]
    return None


def _is_missing_text(value: object) -> bool:
    if value is None:
        return True
    return not str(value).strip()


def check_error_path_inventory(checks: dict | None) -> dict:
    """
    Validate that refactor tasks provide a structured error-path inventory.

    This validates format only. Reviewers are still responsible for assessing
    whether the inventory actually covers every real error path.
    """

    checks = checks or {}
    inventory = _get_check_value(checks, "error_path_inventory", "error-path-inventory")
    if not inventory:
        return {
            "ok": False,
            "rule": "REF-ERROR-001",
            "violations": ["error_path_inventory missing - hard stop"],
            "inventory": [],
        }

    if not isinstance(inventory, list):
        return {
            "ok": False,
            "rule": "REF-ERROR-001",
            "violations": ["error_path_inventory must be a list"],
            "inventory": [],
        }

    violations: list[str] = []
    required_fields = [
        "error_id",
        "trigger",
        "pre_refactor_behavior",
        "affected_by_refactor",
    ]

    for index, item in enumerate(inventory):
        if not isinstance(item, dict):
            violations.append(f"error_path_inventory[{index}] must be an object")
            continue

        missing = []
        for field in required_fields:
            if field == "affected_by_refactor":
                if field not in item or not isinstance(item.get(field), bool):
                    missing.append(field)
            elif _is_missing_text(item.get(field)):
                missing.append(field)

        if missing:
            violations.append(
                f"error_id={item.get('error_id', '?')} missing fields: {missing}"
            )

    return {
        "ok": len(violations) == 0,
        "rule": "REF-ERROR-001",
        "violations": violations,
        "inventory": inventory,
    }


def check_error_behavior_diff(checks: dict | None) -> dict:
    """
    Validate that refactor tasks explain before/after behavior for affected
    error paths. This checks structure and coverage only, not logical accuracy.
    """

    checks = checks or {}
    inventory = _get_check_value(checks, "error_path_inventory", "error-path-inventory")
    if not isinstance(inventory, list) or not inventory:
        return {
            "ok": True,
            "rule": "REF-ERROR-001",
            "violations": [],
            "affected_ids": [],
            "diff": [],
        }

    affected_ids = {
        str(item.get("error_id"))
        for item in inventory
        if isinstance(item, dict)
        and str(item.get("error_id", "")).strip()
        and item.get("affected_by_refactor") is True
    }
    diff = _get_check_value(checks, "error_behavior_diff", "error-behavior-diff")

    if not affected_ids:
        return {
            "ok": True,
            "rule": "REF-ERROR-001",
            "violations": [],
            "affected_ids": sorted(affected_ids),
            "diff": diff if isinstance(diff, list) else [],
        }

    if not diff:
        return {
            "ok": False,
            "rule": "REF-ERROR-001",
            "violations": [
                "error_behavior_diff missing entries for affected error cases: "
                + ", ".join(sorted(affected_ids))
            ],
            "affected_ids": sorted(affected_ids),
            "diff": [],
        }

    if not isinstance(diff, list):
        return {
            "ok": False,
            "rule": "REF-ERROR-001",
            "violations": ["error_behavior_diff must be a list"],
            "affected_ids": sorted(affected_ids),
            "diff": [],
        }

    required_fields = ["error_id", "pre_behavior", "post_behavior", "status", "reviewer_note"]
    allowed_statuses = {"unchanged", "changed", "removed"}
    violations: list[str] = []
    diff_ids: set[str] = set()

    for index, item in enumerate(diff):
        if not isinstance(item, dict):
            violations.append(f"error_behavior_diff[{index}] must be an object")
            continue

        missing = [
            field
            for field in required_fields
            if field not in item or (field != "reviewer_note" and _is_missing_text(item.get(field)))
        ]
        if missing:
            violations.append(
                f"error_id={item.get('error_id', '?')} missing fields: {missing}"
            )
            continue

        error_id = str(item.get("error_id")).strip()
        if error_id:
            diff_ids.add(error_id)

        status = str(item.get("status", "")).strip().lower()
        if status not in allowed_statuses:
            violations.append(
                f"error_id={item.get('error_id', '?')} has invalid status: {item.get('status')}"
            )
            continue

        if status in {"changed", "removed"} and _is_missing_text(item.get("reviewer_note")):
            violations.append(
                f"error_id={item.get('error_id', '?')} status={status} but reviewer_note is empty"
            )

    missing_diff = affected_ids - diff_ids
    if missing_diff:
        violations.append(
            "error_behavior_diff missing entries for affected error cases: "
            + ", ".join(sorted(missing_diff))
        )

    return {
        "ok": len(violations) == 0,
        "rule": "REF-ERROR-001",
        "violations": violations,
        "affected_ids": sorted(affected_ids),
        "diff": diff,
    }


def validate_refactor_evidence(checks: dict | None) -> dict:
    checks = checks or {}
    test_names = _normalize_names(checks.get("test_names"))
    failure_validation = checks.get("failure_test_validation") or {}
    error_path_inventory = _get_check_value(checks, "error_path_inventory", "error-path-inventory")
    error_behavior_diff = _get_check_value(checks, "error_behavior_diff", "error-behavior-diff")
    inventory_check = check_error_path_inventory(checks)
    diff_check = check_error_behavior_diff(checks)

    signals_detected = {
        "regression_evidence": _has_pattern(test_names, REGRESSION_PATTERNS),
        "interface_stability_evidence": _has_pattern(test_names, INTERFACE_STABILITY_PATTERNS)
        or bool(checks.get("interface_stability_verified")),
        "cleanup_evidence": _has_pattern(test_names, CLEANUP_PATTERNS)
        or bool(checks.get("cleanup_verified"))
        or (
            (failure_validation.get("coverage") or {}).get("rollback_cleanup", {}).get("count", 0) > 0
        ),
        "error_path_inventory_evidence": isinstance(error_path_inventory, list) and len(error_path_inventory) > 0,
        "error_behavior_diff_evidence": (
            isinstance(error_behavior_diff, list)
            and len(error_behavior_diff) > 0
        )
        or len(diff_check.get("affected_ids", [])) == 0,
    }

    warnings: list[str] = []
    errors: list[str] = []

    if not signals_detected["regression_evidence"]:
        errors.append("Missing refactor evidence: regression-oriented test signal")

    if not signals_detected["interface_stability_evidence"]:
        errors.append("Missing refactor evidence: interface stability signal")

    if not signals_detected["cleanup_evidence"]:
        warnings.append("Refactor cleanup / rollback evidence was not detected.")

    for violation in inventory_check["violations"]:
        if "missing - hard stop" in violation:
            errors.append(f"Missing refactor evidence: {violation}")
        else:
            errors.append(f"Invalid refactor evidence: {violation}")

    for violation in diff_check["violations"]:
        if "missing entries" in violation or "must be a list" in violation:
            errors.append(f"Missing refactor evidence: {violation}")
        else:
            errors.append(f"Invalid refactor evidence: {violation}")

    return {
        "ok": len(errors) == 0,
        "evidence_required": [
            "regression_evidence",
            "interface_stability_evidence",
            "cleanup_evidence",
            "error_path_inventory_evidence",
            "error_behavior_diff_evidence",
        ],
        "signals_detected": signals_detected,
        "warnings": warnings,
        "errors": errors,
        "evidence_summary": {
            "test_names_count": len(test_names),
            "failure_validation_present": bool(failure_validation),
            "error_path_inventory_count": len(error_path_inventory) if isinstance(error_path_inventory, list) else 0,
            "affected_error_case_count": len(diff_check.get("affected_ids", [])),
            "error_behavior_diff_count": len(error_behavior_diff) if isinstance(error_behavior_diff, list) else 0,
        },
    }


class RefactorEvidenceValidator(DomainValidator):
    @property
    def rule_ids(self) -> list[str]:
        return ["refactor"]

    def validate(self, payload: dict) -> ValidatorResult:
        checks = payload.get("checks", {})
        result_dict = validate_refactor_evidence(checks)
        return ValidatorResult(
            ok=result_dict.get("ok", False),
            rule_ids=self.rule_ids,
            violations=result_dict.get("errors", []),
            warnings=result_dict.get("warnings", []),
            evidence_summary=str(result_dict.get("evidence_summary", "")),
            metadata={
                "evidence_required": result_dict.get("evidence_required", []),
                "signals_detected": result_dict.get("signals_detected", {}),
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate refactor evidence from runtime checks.")
    parser.add_argument("--file", required=True, help="JSON checks file")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    checks = json.loads(Path(args.file).read_text(encoding="utf-8"))
    result = validate_refactor_evidence(checks)

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ok={result['ok']}")
        for key, value in result["signals_detected"].items():
            print(f"{key}={str(value).lower()}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
        for error in result["errors"]:
            print(f"error: {error}")

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
