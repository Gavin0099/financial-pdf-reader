#!/usr/bin/env python3
"""
Normalize test runner output into runtime-governance check payloads.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.failure_test_validator import validate_failure_test_coverage
from governance_tools.failure_disposition import classify_batch


def _base_result(source: str, passed: int = 0, failed: int = 0, skipped: int = 0) -> dict:
    return {
        "source": source,
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        "test_names": [],
        "failure_test_validation": None,
        "failure_disposition": None,
        "diagnostics": [],
        "warnings": [],
        "errors": [],
        "ok": failed == 0,
    }


def _apply_failure_disposition(result: dict) -> dict:
    """
    Classify all failing test IDs through the failure_disposition pipeline.

    Failing tests are derived from result["errors"] (lines starting with
    FAILED/ERROR) plus any names already in result["test_names"].

    The disposition result is stored in result["failure_disposition"].
    If any failure has action=production_fix_required, a governance warning
    is promoted to result["warnings"] so it surfaces without blocking the
    ingestor's ok flag (Slice 3 gate is in session_end_hook).
    """
    # Collect failing test IDs from errors list
    failing_ids: list[str] = []
    extra_signals_map: dict[str, list[str]] = {}

    for err_line in result.get("errors", []):
        # Only consume lines that are actual test failure records.
        # "FAILED tests/foo.py::bar - message" or "ERROR tests/foo.py::bar"
        # Governance/validator error messages (e.g. "failure_path_missing: …")
        # must not be treated as test IDs.
        if not (err_line.startswith("FAILED ") or err_line.startswith("ERROR ")):
            continue
        cleaned = err_line[7:] if err_line.startswith("FAILED ") else err_line[6:]
        parts = cleaned.split(" - ", 1)
        test_id = parts[0].strip()
        extra = [parts[1].strip()] if len(parts) > 1 else []
        if test_id and test_id not in failing_ids:
            failing_ids.append(test_id)
            if extra:
                extra_signals_map[test_id] = extra

    if not failing_ids:
        result["failure_disposition"] = None
        return result

    disposition = classify_batch(failing_ids, extra_signals_map=extra_signals_map)
    result["failure_disposition"] = disposition.to_dict()

    # Promote production_fix_required to advisory warning (not a hard block here)
    if disposition.by_action.get("production_fix_required", 0) > 0:
        result["warnings"].append(
            f"[failure_disposition] {disposition.by_action['production_fix_required']} failure(s) "
            f"classified as production_fix_required — verdict_blocked={disposition.verdict_blocked}"
        )

    # Promote taxonomy_expansion_signal
    if disposition.taxonomy_expansion_signal:
        result["warnings"].append(
            f"[failure_disposition] taxonomy_expansion_signal: "
            f"{disposition.unknown_count} unknown failures >= threshold ({disposition.unknown_threshold})"
        )

    return result


def _finalize_result(result: dict, require_rollback: bool = False, validate_failure_tests: bool = True) -> dict:
    if validate_failure_tests:
        failure_validation = validate_failure_test_coverage(
            result.get("test_names", []),
            require_rollback=require_rollback,
        )
        result["failure_test_validation"] = failure_validation
        result["warnings"].extend(failure_validation["warnings"])
        result["errors"].extend(failure_validation["errors"])
    else:
        result["failure_test_validation"] = None

    # Always apply failure disposition — raw pytest result must not be
    # the final decision input. Disposition runs on all failed test IDs.
    _apply_failure_disposition(result)

    result["ok"] = result["summary"]["failed"] == 0 and len(result["errors"]) == 0
    return result


def ingest_pytest_text(text: str, require_rollback: bool = False) -> dict:
    result = _base_result("pytest-text")
    normalized = text.replace("\r\n", "\n")

    passed_match = re.search(r"(\d+)\s+passed\b", normalized, re.IGNORECASE)
    failed_match = re.search(r"(\d+)\s+failed\b", normalized, re.IGNORECASE)
    skipped_match = re.search(r"(\d+)\s+skipped\b", normalized, re.IGNORECASE)
    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0
    skipped = int(skipped_match.group(1)) if skipped_match else 0
    result["summary"] = {"passed": passed, "failed": failed, "skipped": skipped}
    result["ok"] = failed == 0

    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("FAILED ") or stripped.startswith("ERROR "):
            result["errors"].append(stripped)
            case_id = stripped.split(" ", 1)[1].split(" - ", 1)[0].strip()
            if case_id not in result["test_names"]:
                result["test_names"].append(case_id)
        elif "PytestCacheWarning" in stripped or stripped.startswith("warning:"):
            result["warnings"].append(stripped)
        elif stripped.startswith("tests/") and "::" in stripped:
            case_id = stripped.split()[0].strip()
            if case_id not in result["test_names"]:
                result["test_names"].append(case_id)

    if result["summary"]["failed"] > 0 and not result["errors"]:
        result["errors"].append(f"pytest reported {result['summary']['failed']} failing test(s)")

    return _finalize_result(result, require_rollback=require_rollback)


def ingest_junit_xml(text: str, require_rollback: bool = False) -> dict:
    root = ET.fromstring(text)
    suites = [root] if root.tag == "testsuite" else list(root.findall(".//testsuite"))
    if not suites and root.tag == "testsuites":
        suites = list(root)

    passed = 0
    failed = 0
    skipped = 0
    errors = []

    for suite in suites:
        tests = int(suite.attrib.get("tests", "0") or 0)
        failures = int(suite.attrib.get("failures", "0") or 0)
        suite_errors = int(suite.attrib.get("errors", "0") or 0)
        suite_skipped = int(
            suite.attrib.get("skipped", suite.attrib.get("skip", "0")) or 0
        )
        passed += max(tests - failures - suite_errors - suite_skipped, 0)
        failed += failures + suite_errors
        skipped += suite_skipped

        for testcase in suite.findall(".//testcase"):
            name = testcase.attrib.get("name", "unnamed-test")
            classname = testcase.attrib.get("classname", "").strip()
            label = f"{classname}::{name}" if classname else name
            for node in list(testcase.findall("failure")) + list(testcase.findall("error")):
                message = (node.attrib.get("message") or node.text or "").strip()
                errors.append(f"{label} - {message}" if message else label)

    result = _base_result("junit-xml", passed=passed, failed=failed, skipped=skipped)
    # test names are collected from every testcase label for downstream failure-path validation
    for suite in suites:
        for testcase in suite.findall(".//testcase"):
            name = testcase.attrib.get("name", "unnamed-test")
            classname = testcase.attrib.get("classname", "").strip()
            label = f"{classname}::{name}" if classname else name
            if label not in result["test_names"]:
                result["test_names"].append(label)
    result["errors"] = errors
    return _finalize_result(result, require_rollback=require_rollback)


def ingest_sdv_text(text: str, require_rollback: bool = False) -> dict:
    result = _base_result("sdv-text", passed=1, failed=0, skipped=0)
    normalized = text.replace("\r\n", "\n")

    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        result["diagnostics"].append(stripped)
        if any(token in lower for token in ("error", "defect", "violat", "failed")):
            result["errors"].append(stripped)
        elif any(token in lower for token in ("warning", "caution")):
            result["warnings"].append(stripped)

    if result["errors"]:
        result["summary"]["failed"] = len(result["errors"])
        result["summary"]["passed"] = 0

    result["sdv_verified"] = len(result["errors"]) == 0
    result["driver_analysis_verified"] = len(result["errors"]) == 0
    result["ok"] = len(result["errors"]) == 0
    return _finalize_result(result, require_rollback=require_rollback, validate_failure_tests=False)


def ingest_msbuild_warning_text(text: str, require_rollback: bool = False) -> dict:
    result = _base_result("msbuild-warning-text", passed=1, failed=0, skipped=0)
    normalized = text.replace("\r\n", "\n")

    warning_lines = []
    error_lines = []
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if ": warning " in lower or lower.startswith("warning "):
            warning_lines.append(stripped)
            result["diagnostics"].append(stripped)
        elif ": error " in lower or lower.startswith("error "):
            error_lines.append(stripped)
            result["diagnostics"].append(stripped)

    result["warnings"].extend(warning_lines)
    result["errors"].extend(error_lines)
    if error_lines:
        result["summary"]["failed"] = len(error_lines)
        result["summary"]["passed"] = 0

    diagnostic_blob = "\n".join(result["diagnostics"]).lower()
    result["sdv_verified"] = "static driver verifier" in diagnostic_blob or " sdv" in diagnostic_blob
    result["driver_analysis_verified"] = any(
        token in diagnostic_blob for token in ("sal", "prefast", "wdk analysis", "static driver verifier", " sdv")
    )
    result["irql_verified"] = any(token in diagnostic_blob for token in ("irql", "passive_level", "dispatch_level", "pageable"))
    result["ioctl_boundary_verified"] = any(
        token in diagnostic_blob for token in ("ioctl", "user buffer", "buffer length", "malformed input")
    )
    result["ok"] = len(result["errors"]) == 0
    return _finalize_result(result, require_rollback=require_rollback, validate_failure_tests=False)


def ingest_sarif(text: str, require_rollback: bool = False) -> dict:
    data = json.loads(text)
    result = _base_result("sarif", passed=1, failed=0, skipped=0)

    warning_lines = []
    error_lines = []

    for run in data.get("runs", []):
        for entry in run.get("results", []):
            level = str(entry.get("level", "warning")).lower()
            rule_id = entry.get("ruleId", "unknown-rule")
            message = ((entry.get("message") or {}).get("text") or "").strip()
            line = f"{rule_id}: {message}".strip()
            result["diagnostics"].append(line)
            if level == "error":
                error_lines.append(line)
            else:
                warning_lines.append(line)

    result["warnings"].extend(warning_lines)
    result["errors"].extend(error_lines)
    if error_lines:
        result["summary"]["failed"] = len(error_lines)
        result["summary"]["passed"] = 0

    diagnostic_blob = "\n".join(result["diagnostics"]).lower()
    result["sdv_verified"] = "static driver verifier" in diagnostic_blob or " sdv" in diagnostic_blob
    result["driver_analysis_verified"] = any(
        token in diagnostic_blob for token in ("sal", "prefast", "wdk analysis", "static driver verifier", " sdv", "driver verifier")
    )
    result["irql_verified"] = any(token in diagnostic_blob for token in ("irql", "passive_level", "dispatch_level", "pageable"))
    result["ioctl_boundary_verified"] = any(
        token in diagnostic_blob for token in ("ioctl", "user buffer", "buffer length", "malformed input", "invalid input")
    )
    result["ok"] = len(result["errors"]) == 0
    return _finalize_result(result, require_rollback=require_rollback, validate_failure_tests=False)


def ingest_wdk_analysis_text(text: str, require_rollback: bool = False) -> dict:
    result = _base_result("wdk-analysis-text", passed=1, failed=0, skipped=0)
    normalized = text.replace("\r\n", "\n")

    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(token in lower for token in ("warning", "error", "analysis", "sal", "sdv", "irql", "ioctl", "buffer")):
            result["diagnostics"].append(stripped)
        if ": error " in lower or lower.startswith("error "):
            result["errors"].append(stripped)
        elif ": warning " in lower or lower.startswith("warning "):
            result["warnings"].append(stripped)

    if result["errors"]:
        result["summary"]["failed"] = len(result["errors"])
        result["summary"]["passed"] = 0

    diagnostic_blob = "\n".join(result["diagnostics"]).lower()
    result["sdv_verified"] = "static driver verifier" in diagnostic_blob or " sdv" in diagnostic_blob
    result["driver_analysis_verified"] = any(
        token in diagnostic_blob for token in ("sal", "prefast", "wdk analysis", "static driver verifier", " sdv", "driver verifier")
    )
    result["irql_verified"] = any(token in diagnostic_blob for token in ("irql", "passive_level", "dispatch_level", "pageable"))
    result["ioctl_boundary_verified"] = any(
        token in diagnostic_blob for token in ("ioctl", "user buffer", "buffer length", "malformed input", "invalid input")
    )
    result["ok"] = len(result["errors"]) == 0
    return _finalize_result(result, require_rollback=require_rollback, validate_failure_tests=False)


def ingest_test_results(path: Path, kind: str, require_rollback: bool = False) -> dict:
    text = path.read_text(encoding="utf-8")
    if kind == "pytest-text":
        return ingest_pytest_text(text, require_rollback=require_rollback)
    if kind == "junit-xml":
        return ingest_junit_xml(text, require_rollback=require_rollback)
    if kind == "sdv-text":
        return ingest_sdv_text(text, require_rollback=require_rollback)
    if kind == "msbuild-warning-text":
        return ingest_msbuild_warning_text(text, require_rollback=require_rollback)
    if kind == "sarif":
        return ingest_sarif(text, require_rollback=require_rollback)
    if kind == "wdk-analysis-text":
        return ingest_wdk_analysis_text(text, require_rollback=require_rollback)
    raise ValueError(f"Unsupported test result kind: {kind}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize test results for runtime governance.")
    parser.add_argument("--file", required=True)
    parser.add_argument("--kind", choices=["pytest-text", "junit-xml", "sdv-text", "msbuild-warning-text", "sarif", "wdk-analysis-text"], required=True)
    parser.add_argument("--require-rollback", action="store_true")
    parser.add_argument(
        "--out",
        default=None,
        help="Write result JSON to this path (parent dirs are created automatically). "
             "Standard artifact path: artifacts/runtime/test-results/latest.json",
    )
    args = parser.parse_args()

    result = ingest_test_results(Path(args.file), args.kind, require_rollback=args.require_rollback)
    out_str = json.dumps(result, ensure_ascii=False, indent=2)
    print(out_str)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_str, encoding="utf-8")

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
