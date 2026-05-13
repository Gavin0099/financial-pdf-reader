#!/usr/bin/env python3
"""
Validate whether test evidence covers required failure-path categories.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable


CATEGORY_PATTERNS = {
    "invalid_input": [
        r"invalid",
        r"bad[_\- ]?input",
        r"malformed",
        r"null",
        r"none",
        r"empty",
    ],
    "boundary": [
        r"boundary",
        r"limit",
        r"min(?:imum)?",
        r"max(?:imum)?",
        r"overflow",
        r"underflow",
        r"edge",
    ],
    "failure_path": [
        r"fail(?:ure|ing|ed)?",
        r"error",
        r"exception",
        r"timeout",
        r"denied",
        r"unavailable",
    ],
    "rollback_cleanup": [
        r"rollback",
        r"cleanup",
        r"clean[_\- ]?up",
        r"dispose",
        r"release",
        r"revert",
    ],
}


def _normalize_names(names: Iterable[str]) -> list[str]:
    normalized = []
    for name in names:
        text = str(name).strip()
        if text:
            normalized.append(text.lower())
    return normalized


def classify_test_names(test_names: Iterable[str]) -> dict[str, list[str]]:
    normalized = _normalize_names(test_names)
    matched: dict[str, list[str]] = {category: [] for category in CATEGORY_PATTERNS}

    for test_name in normalized:
        for category, patterns in CATEGORY_PATTERNS.items():
            if any(re.search(pattern, test_name, re.IGNORECASE) for pattern in patterns):
                matched[category].append(test_name)

    return matched


def validate_failure_test_coverage(
    test_names: Iterable[str],
    require_rollback: bool = False,
) -> dict:
    matched = classify_test_names(test_names)
    warnings: list[str] = []
    errors: list[str] = []

    required_categories = ["invalid_input", "boundary", "failure_path"]
    if require_rollback:
        required_categories.append("rollback_cleanup")

    for category in required_categories:
        if not matched[category]:
            errors.append(f"Missing required failure-test coverage: {category}")

    if not matched["rollback_cleanup"]:
        warnings.append("Rollback / cleanup coverage was not detected.")

    coverage = {
        category: {
            "count": len(names),
            "matches": names,
        }
        for category, names in matched.items()
    }

    return {
        "ok": len(errors) == 0,
        "required_categories": required_categories,
        "coverage": coverage,
        "warnings": warnings,
        "errors": errors,
    }


def _load_test_names(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [str(item) for item in payload]
    if isinstance(payload, dict):
        if isinstance(payload.get("tests"), list):
            return [str(item) for item in payload["tests"]]
        if isinstance(payload.get("test_names"), list):
            return [str(item) for item in payload["test_names"]]
    raise ValueError("Expected a JSON array or an object with 'tests' / 'test_names'.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate failure-path test coverage from test names.")
    parser.add_argument("--file", required=True, help="JSON file containing test names")
    parser.add_argument("--require-rollback", action="store_true")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    result = validate_failure_test_coverage(
        _load_test_names(Path(args.file)),
        require_rollback=args.require_rollback,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ok={result['ok']}")
        for category, payload in result["coverage"].items():
            print(f"{category}={payload['count']}")
        for warning in result["warnings"]:
            print(f"warning: {warning}")
        for error in result["errors"]:
            print(f"error: {error}")

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
