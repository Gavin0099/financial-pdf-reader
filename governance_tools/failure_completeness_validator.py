#!/usr/bin/env python3
"""
Validate richer failure-completeness evidence from runtime checks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from governance_tools.validator_interface import DomainValidator, ValidatorResult



EXCEPTION_PATTERNS = [
    r"exception",
    r"error",
    r"throws?",
    r"raise[sd]?",
    r"panic",
    r"fail",
]

ROLLBACK_PATTERNS = [
    r"rollback",
    r"cleanup",
    r"clean[_\- ]?up",
    r"dispose",
    r"release",
    r"revert",
]


def _normalize_test_names(checks: dict) -> list[str]:
    return [str(name).strip().lower() for name in checks.get("test_names", []) if str(name).strip()]


def _has_pattern(values: list[str], patterns: list[str]) -> bool:
    return any(re.search(pattern, value, re.IGNORECASE) for value in values for pattern in patterns)


def _metadata_signal_count(checks: dict) -> int:
    count = 0
    for key in ("exception_assertions", "failure_cases", "cleanup_verified", "rollback_verified", "exception_verified"):
        value = checks.get(key)
        if isinstance(value, bool) and value:
            count += 1
        elif isinstance(value, int) and value > 0:
            count += 1
        elif isinstance(value, list) and value:
            count += 1
    return count


def validate_failure_completeness(checks: dict | None, require_cleanup: bool = False) -> dict:
    checks = checks or {}
    test_names = _normalize_test_names(checks)
    failure_validation = checks.get("failure_test_validation") or {}
    coverage = failure_validation.get("coverage") or {}

    failure_path_signal = (
        coverage.get("failure_path", {}).get("count", 0) > 0
        or _has_pattern(test_names, EXCEPTION_PATTERNS)
    )
    exception_evidence = (
        bool(checks.get("exception_verified"))
        or bool(checks.get("exception_assertions"))
        or _has_pattern(test_names, EXCEPTION_PATTERNS)
    )
    rollback_evidence = (
        bool(checks.get("cleanup_verified"))
        or bool(checks.get("rollback_verified"))
        or coverage.get("rollback_cleanup", {}).get("count", 0) > 0
        or _has_pattern(test_names, ROLLBACK_PATTERNS)
    )
    metadata_depth = _metadata_signal_count(checks) > 0

    warnings: list[str] = []
    errors: list[str] = []

    if not failure_path_signal:
        errors.append("Missing failure completeness evidence: failure-path signal")

    if not exception_evidence:
        warnings.append("Explicit exception-path evidence was not detected.")

    if require_cleanup and not rollback_evidence:
        errors.append("Missing failure completeness evidence: rollback/cleanup verification")
    elif not rollback_evidence:
        warnings.append("Explicit rollback / cleanup verification was not detected.")

    if not metadata_depth:
        warnings.append("Richer test metadata was not provided; failure completeness remains heuristic.")

    return {
        "ok": len(errors) == 0,
        "signals_detected": {
            "failure_path_signal": failure_path_signal,
            "exception_evidence": exception_evidence,
            "rollback_evidence": rollback_evidence,
            "metadata_depth": metadata_depth,
        },
        "warnings": warnings,
        "errors": errors,
    }


class FailureCompletenessValidator(DomainValidator):
    @property
    def rule_ids(self) -> list[str]:
        return ["feature", "refactor"]

    def validate(self, payload: dict) -> ValidatorResult:
        checks = payload.get("checks", {})
        result_dict = validate_failure_completeness(checks)
        return ValidatorResult(
            ok=result_dict.get("ok", False),
            rule_ids=self.rule_ids,
            violations=result_dict.get("errors", []),
            warnings=result_dict.get("warnings", []),
            evidence_summary=str(result_dict.get("signals_detected", {})),
            metadata={"signals_detected": result_dict.get("signals_detected", {})}
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate richer failure-completeness evidence from runtime checks.")
    parser.add_argument("--file", required=True, help="JSON checks file")
    parser.add_argument("--require-cleanup", action="store_true")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    checks = json.loads(Path(args.file).read_text(encoding="utf-8"))
    result = validate_failure_completeness(checks, require_cleanup=args.require_cleanup)

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
