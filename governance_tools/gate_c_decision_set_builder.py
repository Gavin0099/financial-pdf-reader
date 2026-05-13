#!/usr/bin/env python3
"""
Build Gate C decision-set artifacts from canonical logs.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANES = ("copilot", "claude", "chatgpt")


@dataclass
class BuildResult:
    window_id: str
    canonical_review_count: dict[str, int]
    canonical_rework_count: dict[str, int]
    canonical_stability_count: dict[str, int]
    decision_review_count: dict[str, int]
    decision_rework_count: dict[str, int]
    decision_stability_count: dict[str, int]
    filtered_reason_counts: dict[str, int]
    output_review_log_path: str
    output_manifest_path: str
    output_report_path: str


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            records.append(json.loads(stripped))
    return records


def _lane(value: Any) -> str | None:
    if value is None:
        return None
    lane = str(value).strip().lower()
    return lane if lane in LANES else None


def _is_iso8601(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _review_validity(row: dict[str, Any], window_id: str) -> str | None:
    if row.get("window_id") != window_id:
        return "window_mismatch"
    lane = _lane(row.get("lane"))
    if lane is None:
        return "invalid_lane"
    start = row.get("review_start_utc")
    end = row.get("review_end_utc")
    if not _is_iso8601(start):
        return "missing_or_invalid_review_start"
    if not _is_iso8601(end):
        return "missing_or_invalid_review_end"
    start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    if end_dt < start_dt:
        return "invalid_review_time_order"
    mins = row.get("review_minutes")
    if mins is None:
        return "missing_review_minutes"
    try:
        if float(mins) < 0:
            return "negative_review_minutes"
    except (TypeError, ValueError):
        return "invalid_review_minutes"
    return None


def _rework_validity(row: dict[str, Any], window_id: str) -> str | None:
    if row.get("window_id") != window_id:
        return "window_mismatch"
    if _lane(row.get("lane")) is None:
        return "invalid_lane"
    try:
        total = int(row.get("total_changes"))
    except (TypeError, ValueError):
        return "missing_or_invalid_total_changes"
    if total <= 0:
        return "missing_rework_denominator"
    try:
        reopen = int(row.get("reopen_count", 0))
        revert = int(row.get("revert_count", 0))
    except (TypeError, ValueError):
        return "invalid_rework_counts"
    if reopen < 0 or revert < 0:
        return "invalid_rework_counts"
    return None


def _stability_validity(row: dict[str, Any], window_id: str) -> str | None:
    if row.get("window_id") != window_id:
        return "window_mismatch"
    if _lane(row.get("lane")) is None:
        return "invalid_lane"
    state = str(row.get("integration_stability", "")).strip().lower()
    if state not in {"stable", "degraded"}:
        return "unknown_stability_state"
    note = str(row.get("stability_note", "")).strip()
    if not note:
        return "empty_stability_note"
    return None


def _count_by_lane(rows: list[dict[str, Any]], window_id: str) -> dict[str, int]:
    out = {k: 0 for k in LANES}
    for row in rows:
        if row.get("window_id") != window_id:
            continue
        lane = _lane(row.get("lane"))
        if lane:
            out[lane] += 1
    return out


def _markdown_report(result: BuildResult) -> str:
    return (
        f"# Gate C Decision-Set Report {result.window_id}\n\n"
        f"- decision_contract_version: gate-c-decision-set-v0.1\n"
        f"- decision_builder_version: gate-c-decision-set-builder-v0.1\n"
        f"- output_review_log_path: {result.output_review_log_path}\n"
        f"- output_manifest_path: {result.output_manifest_path}\n\n"
        f"## Counts\n\n"
        f"- canonical_review_count: {result.canonical_review_count}\n"
        f"- canonical_rework_count: {result.canonical_rework_count}\n"
        f"- canonical_stability_count: {result.canonical_stability_count}\n"
        f"- decision_review_count: {result.decision_review_count}\n"
        f"- decision_rework_count: {result.decision_rework_count}\n"
        f"- decision_stability_count: {result.decision_stability_count}\n\n"
        f"## Filtered Reasons\n\n"
        f"- filtered_reason_counts: {result.filtered_reason_counts}\n"
    )


def build_decision_set(
    project_root: Path,
    window_id: str,
    review_log: Path | None = None,
    rework_log: Path | None = None,
    stability_log: Path | None = None,
    output_dir: Path | None = None,
) -> BuildResult:
    project_root = project_root.resolve()
    review_log = (review_log or (project_root / "docs" / "status" / "gate-c-review-log.ndjson")).resolve()
    rework_log = (rework_log or (project_root / "docs" / "status" / "gate-c-rework-log.ndjson")).resolve()
    stability_log = (stability_log or (project_root / "docs" / "status" / "gate-c-stability-log.ndjson")).resolve()
    output_dir = (output_dir or (project_root / "docs" / "status" / "decision-set")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    review_rows = _read_ndjson(review_log)
    rework_rows = _read_ndjson(rework_log)
    stability_rows = _read_ndjson(stability_log)

    canonical_review_count = _count_by_lane(review_rows, window_id)
    canonical_rework_count = _count_by_lane(rework_rows, window_id)
    canonical_stability_count = _count_by_lane(stability_rows, window_id)

    filtered = Counter()
    decision_reviews: list[dict[str, Any]] = []
    for row in review_rows:
        reason = _review_validity(row, window_id)
        if reason is None:
            decision_reviews.append(row)
        else:
            filtered[reason] += 1

    decision_reworks: list[dict[str, Any]] = []
    for row in rework_rows:
        reason = _rework_validity(row, window_id)
        if reason is None:
            decision_reworks.append(row)
        else:
            filtered[reason] += 1

    decision_stability: list[dict[str, Any]] = []
    for row in stability_rows:
        reason = _stability_validity(row, window_id)
        if reason is None:
            decision_stability.append(row)
        else:
            filtered[reason] += 1

    decision_reviews.sort(key=lambda r: (str(r.get("lane", "")), str(r.get("run_id", ""))))
    decision_reworks.sort(key=lambda r: (str(r.get("lane", "")), str(r.get("run_id", ""))))
    decision_stability.sort(key=lambda r: (str(r.get("lane", "")), str(r.get("run_id", ""))))

    decision_review_count = _count_by_lane(decision_reviews, window_id)
    decision_rework_count = _count_by_lane(decision_reworks, window_id)
    decision_stability_count = _count_by_lane(decision_stability, window_id)

    safe_window = window_id.replace("/", "-")
    out_review = output_dir / f"{safe_window}-review-log.valid.ndjson"
    out_manifest = output_dir / f"{safe_window}-decision-derivation-manifest.json"
    out_report = output_dir / f"{safe_window}-decision-set-report.md"

    with out_review.open("w", encoding="utf-8") as fh:
        for row in decision_reviews:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "window_id": window_id,
        "decision_contract_version": "gate-c-decision-set-v0.1",
        "decision_builder_version": "gate-c-decision-set-builder-v0.1",
        "projection_policy_version": "gate-c-projection-policy-v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "canonical_count": {
            "review": canonical_review_count,
            "rework": canonical_rework_count,
            "stability": canonical_stability_count,
        },
        "decision_count": {
            "review": decision_review_count,
            "rework": decision_rework_count,
            "stability": decision_stability_count,
        },
        "filtered_reason_counts": dict(filtered),
        "inputs": {
            "review_log": str(review_log),
            "rework_log": str(rework_log),
            "stability_log": str(stability_log),
        },
        "outputs": {
            "decision_review_log": str(out_review),
            "decision_report": str(out_report),
            "derivation_manifest": str(out_manifest),
        },
    }
    out_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = BuildResult(
        window_id=window_id,
        canonical_review_count=canonical_review_count,
        canonical_rework_count=canonical_rework_count,
        canonical_stability_count=canonical_stability_count,
        decision_review_count=decision_review_count,
        decision_rework_count=decision_rework_count,
        decision_stability_count=decision_stability_count,
        filtered_reason_counts=dict(filtered),
        output_review_log_path=str(out_review),
        output_manifest_path=str(out_manifest),
        output_report_path=str(out_report),
    )
    out_report.write_text(_markdown_report(result), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Gate C decision-set artifacts from canonical logs.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--review-log")
    parser.add_argument("--rework-log")
    parser.add_argument("--stability-log")
    parser.add_argument("--output-dir")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    result = build_decision_set(
        project_root=Path(args.project_root),
        window_id=args.window_id,
        review_log=Path(args.review_log) if args.review_log else None,
        rework_log=Path(args.rework_log) if args.rework_log else None,
        stability_log=Path(args.stability_log) if args.stability_log else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )

    if args.format == "json":
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        print(
            f"summary=gate_c_decision_set | OK | window={result.window_id}; "
            f"decision_review={sum(result.decision_review_count.values())}; "
            f"decision_rework={sum(result.decision_rework_count.values())}; "
            f"decision_stability={sum(result.decision_stability_count.values())}"
        )
        print(
            f"outputs: review={result.output_review_log_path} "
            f"manifest={result.output_manifest_path} report={result.output_report_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
