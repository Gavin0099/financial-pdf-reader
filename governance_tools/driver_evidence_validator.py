#!/usr/bin/env python3
"""
Validate kernel-driver evidence from normalized runtime checks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from governance_tools.validator_interface import DomainValidator, ValidatorResult

IRQL_PATTERNS = [
    r"\birql\b",
    r"passive_level",
    r"dispatch_level",
    r"pageable",
    r"nonpageable",
]

IOCTL_PATTERNS = [
    r"\bioctl\b",
    r"malformed[_\- ]?input",
    r"invalid[_\- ]?input",
    r"buffer[_\- ]?length",
    r"user[_\- ]?buffer",
]

CLEANUP_PATTERNS = [
    r"cleanup",
    r"rollback",
    r"unwind",
    r"unload",
    r"cancel",
    r"remove",
]

HIGH_SIGNAL_DRIVER_DIAGNOSTICS = [
    r"static driver verifier",
    r"\bsdv\b",
    r"\bsal\b",
    r"driver verifier",
    r"wdk.*analysis",
    r"prefast",
]


def _normalize_strings(values: list[str] | None) -> list[str]:
    return [str(value).strip().lower() for value in (values or []) if str(value).strip()]


def _has_pattern(values: list[str], patterns: list[str]) -> bool:
    return any(re.search(pattern, value, re.IGNORECASE) for value in values for pattern in patterns)


def _diagnostic_values(checks: dict) -> list[str]:
    values = []
    for key in ("warnings", "errors", "diagnostics", "analysis_notes"):
        values.extend(_normalize_strings(checks.get(key)))
    return values


def validate_driver_evidence(checks: dict | None) -> dict:
    checks = checks or {}
    test_names = _normalize_strings(checks.get("test_names"))
    diagnostics = _diagnostic_values(checks)

    signals_detected = {
        "static_analysis_evidence": bool(checks.get("sdv_verified"))
        or bool(checks.get("driver_analysis_verified"))
        or _has_pattern(diagnostics, HIGH_SIGNAL_DRIVER_DIAGNOSTICS),
        "irql_evidence": bool(checks.get("irql_verified"))
        or _has_pattern(test_names, IRQL_PATTERNS)
        or _has_pattern(diagnostics, IRQL_PATTERNS),
        "ioctl_boundary_evidence": bool(checks.get("ioctl_boundary_verified"))
        or _has_pattern(test_names, IOCTL_PATTERNS),
        "cleanup_unwind_evidence": bool(checks.get("cleanup_verified"))
        or bool(checks.get("rollback_verified"))
        or _has_pattern(test_names, CLEANUP_PATTERNS),
    }

    warnings: list[str] = []
    errors: list[str] = []

    if not signals_detected["static_analysis_evidence"]:
        errors.append("Missing kernel-driver evidence: static analysis result (SDV / SAL / WDK)")

    if not signals_detected["irql_evidence"]:
        errors.append("Missing kernel-driver evidence: IRQL / pageable-context verification")

    if not signals_detected["ioctl_boundary_evidence"]:
        errors.append("Missing kernel-driver evidence: IOCTL / user-buffer boundary verification")

    if not signals_detected["cleanup_unwind_evidence"]:
        warnings.append("Kernel-driver cleanup / unwind evidence was not detected.")

    if checks.get("summary", {}).get("failed", 0) > 0:
        errors.append("Kernel-driver evidence contains failing test or analysis results.")

    return {
        "ok": len(errors) == 0,
        "evidence_required": [
            "static_analysis_evidence",
            "irql_evidence",
            "ioctl_boundary_evidence",
            "cleanup_unwind_evidence",
        ],
        "signals_detected": signals_detected,
        "warnings": warnings,
        "errors": errors,
        "evidence_summary": {
            "test_names_count": len(test_names),
            "diagnostic_count": len(diagnostics),
        },
    }


class DriverEvidenceValidator(DomainValidator):
    @property
    def rule_ids(self) -> list[str]:
        return ["kernel-driver"]

    def validate(self, payload: dict) -> ValidatorResult:
        checks = payload.get("checks", {})
        result_dict = validate_driver_evidence(checks)
        return ValidatorResult(
            ok=result_dict["ok"],
            rule_ids=self.rule_ids,
            violations=result_dict["errors"],
            warnings=result_dict["warnings"],
            evidence_summary=str(result_dict["evidence_summary"]),
            metadata={
                "evidence_required": result_dict["evidence_required"],
                "signals_detected": result_dict["signals_detected"],
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate kernel-driver evidence from runtime checks.")
    parser.add_argument("--file", required=True, help="JSON checks file")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    checks = json.loads(Path(args.file).read_text(encoding="utf-8"))
    result = validate_driver_evidence(checks)

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
