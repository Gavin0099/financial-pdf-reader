#!/usr/bin/env python3
"""
Advisory-only observation helpers for runtime injection requirements.
"""

from __future__ import annotations

from pathlib import Path


LARGE_FILE_LINE_THRESHOLD = 200


def _safe_line_count(path: Path) -> int | None:
    try:
        return len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        return None


def observe_full_read_requirement(
    documents: list[dict] | None,
    *,
    summary_first_active: bool,
) -> dict:
    docs = documents or []
    existing_paths = [Path(item["path"]) for item in docs if item.get("exists") and item.get("path")]
    line_counts = {str(path): _safe_line_count(path) for path in existing_paths}
    large_docs = [
        str(path)
        for path, line_count in line_counts.items()
        if line_count is not None and line_count > LARGE_FILE_LINE_THRESHOLD
    ]
    unreadable_docs = [path for path, line_count in line_counts.items() if line_count is None]

    if not existing_paths or not large_docs:
        return {
            "requirement": "require_full_read_for_large_files",
            "applicable": False,
            "observation_status": "not_applicable",
            "observation_confidence": "low",
            "decision_role": "advisory_only",
            "observable_proxy": "no_large_contract_documents_detected",
            "matched_paths": [],
            "line_threshold": LARGE_FILE_LINE_THRESHOLD,
            "caveat": "absence of a large document means the requirement was not triggered",
        }

    if unreadable_docs:
        return {
            "requirement": "require_full_read_for_large_files",
            "applicable": True,
            "observation_status": "unknown",
            "observation_confidence": "low",
            "decision_role": "advisory_only",
            "observable_proxy": "large_file_presence_detected_but_line_count_unavailable",
            "matched_paths": large_docs or unreadable_docs,
            "line_threshold": LARGE_FILE_LINE_THRESHOLD,
            "caveat": "this does not prove non-compliance; observation could not be completed",
        }

    if summary_first_active:
        return {
            "requirement": "require_full_read_for_large_files",
            "applicable": True,
            "observation_status": "partial",
            "observation_confidence": "low",
            "decision_role": "advisory_only",
            "observable_proxy": "large_file_detected_with_summary_first_context",
            "matched_paths": large_docs,
            "line_threshold": LARGE_FILE_LINE_THRESHOLD,
            "caveat": "summary-first degradation is compatible with partial read coverage, not proof of violation",
        }

    return {
        "requirement": "require_full_read_for_large_files",
        "applicable": True,
        "observation_status": "compatible",
        "observation_confidence": "low",
        "decision_role": "advisory_only",
        "observable_proxy": "large_file_detected_without_summary_first_degradation",
        "matched_paths": large_docs,
        "line_threshold": LARGE_FILE_LINE_THRESHOLD,
        "caveat": "compatible observation is not proof that the file was semantically understood",
    }
