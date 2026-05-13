#!/usr/bin/env python3
"""
Generate Gate C dual-report artifacts:
1) canonical report (full evidence surface)
2) decision-set report + derivation manifest
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.gate_c_decision_set_builder import (
    LANES,
    _read_ndjson,
    _lane,
    build_decision_set,
)
from governance_tools.fgcr_report import _read_ndjson as _read_fgcr_events
from governance_tools.fgcr_report import build_fgcr_report


@dataclass
class DualReportResult:
    window_id: str
    canonical_report_path: str
    decision_report_path: str
    decision_manifest_path: str
    decision_review_log_path: str
    fgcr_summary_path: str


def _count_by_lane(rows: list[dict[str, Any]], window_id: str) -> dict[str, int]:
    out = {k: 0 for k in LANES}
    for row in rows:
        if row.get("window_id") != window_id:
            continue
        lane = _lane(row.get("lane"))
        if lane:
            out[lane] += 1
    return out


def _canonical_markdown(
    *,
    window_id: str,
    review_log_path: Path,
    rework_log_path: Path,
    stability_log_path: Path,
    canonical_review_count: dict[str, int],
    canonical_rework_count: dict[str, int],
    canonical_stability_count: dict[str, int],
    decision_review_count: dict[str, int],
    decision_rework_count: dict[str, int],
    decision_stability_count: dict[str, int],
    filtered_reason_counts: dict[str, int],
    fgcr_summary: dict[str, Any],
    fgcr_events_path: Path,
    fgcr_summary_path: Path,
) -> str:
    fgcr_window = fgcr_summary["by_window"]
    fgcr_lines = [
        "## FGCR v0.1 Summary",
        "",
        f"- fgcr_events_path: {fgcr_events_path}",
        f"- fgcr_summary_path: {fgcr_summary_path}",
        "- detector_role: false-confidence detector (not quality uplift proof)",
        f"- status: {fgcr_window['status']}",
        f"- confidence_marked_events: {fgcr_window['confidence_marked_events']}",
        f"- false_confidence_events: {fgcr_window['false_confidence_events']}",
        f"- by_failure_type: {fgcr_window['by_failure_type']}",
    ]
    if fgcr_window["status"] != "insufficient_sample":
        fgcr_lines.append(f"- fgcr: {fgcr_window['fgcr']}")
    fgcr_block = "\n".join(fgcr_lines)

    return (
        f"# Gate C Canonical Report {window_id}\n\n"
        f"- review_log_path: {review_log_path}\n"
        f"- rework_log_path: {rework_log_path}\n"
        f"- stability_log_path: {stability_log_path}\n\n"
        f"## Counts\n\n"
        f"- canonical_count:\n"
        f"  - review: {canonical_review_count}\n"
        f"  - rework: {canonical_rework_count}\n"
        f"  - stability: {canonical_stability_count}\n"
        f"- decision_count:\n"
        f"  - review: {decision_review_count}\n"
        f"  - rework: {decision_rework_count}\n"
        f"  - stability: {decision_stability_count}\n\n"
        f"## Filtered Reasons\n\n"
        f"- filtered_reason_counts: {filtered_reason_counts}\n\n"
        f"{fgcr_block}\n"
    )


def generate_dual_report(
    *,
    project_root: Path,
    window_id: str,
    review_log: Path | None = None,
    rework_log: Path | None = None,
    stability_log: Path | None = None,
    output_dir: Path | None = None,
    fgcr_events: Path | None = None,
) -> DualReportResult:
    project_root = project_root.resolve()
    review_log_path = (review_log or (project_root / "docs" / "status" / "gate-c-review-log.ndjson")).resolve()
    rework_log_path = (rework_log or (project_root / "docs" / "status" / "gate-c-rework-log.ndjson")).resolve()
    stability_log_path = (stability_log or (project_root / "docs" / "status" / "gate-c-stability-log.ndjson")).resolve()
    output_dir = (output_dir or (project_root / "docs" / "status" / "decision-set")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fgcr_events_path = (fgcr_events or (project_root / "docs" / "status" / "fgcr-events.ndjson")).resolve()

    # Build decision artifacts first.
    decision = build_decision_set(
        project_root=project_root,
        window_id=window_id,
        review_log=review_log_path,
        rework_log=rework_log_path,
        stability_log=stability_log_path,
        output_dir=output_dir,
    )

    # Canonical counts are computed from full logs for the same window.
    review_rows = _read_ndjson(review_log_path)
    rework_rows = _read_ndjson(rework_log_path)
    stability_rows = _read_ndjson(stability_log_path)
    canonical_review_count = _count_by_lane(review_rows, window_id)
    canonical_rework_count = _count_by_lane(rework_rows, window_id)
    canonical_stability_count = _count_by_lane(stability_rows, window_id)

    safe_window = window_id.replace("/", "-")
    canonical_report_path = output_dir / f"{safe_window}-canonical-report.md"
    fgcr_summary_path = output_dir / f"{safe_window}-fgcr-summary.json"
    fgcr_events_rows = _read_fgcr_events(fgcr_events_path)
    fgcr_summary = build_fgcr_report(fgcr_events_rows, window_id)
    fgcr_summary_path.write_text(json.dumps(fgcr_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    canonical_report_path.write_text(
        _canonical_markdown(
            window_id=window_id,
            review_log_path=review_log_path,
            rework_log_path=rework_log_path,
            stability_log_path=stability_log_path,
            canonical_review_count=canonical_review_count,
            canonical_rework_count=canonical_rework_count,
            canonical_stability_count=canonical_stability_count,
            decision_review_count=decision.decision_review_count,
            decision_rework_count=decision.decision_rework_count,
            decision_stability_count=decision.decision_stability_count,
            filtered_reason_counts=decision.filtered_reason_counts,
            fgcr_summary=fgcr_summary,
            fgcr_events_path=fgcr_events_path,
            fgcr_summary_path=fgcr_summary_path,
        ),
        encoding="utf-8",
    )

    return DualReportResult(
        window_id=window_id,
        canonical_report_path=str(canonical_report_path),
        decision_report_path=decision.output_report_path,
        decision_manifest_path=decision.output_manifest_path,
        decision_review_log_path=decision.output_review_log_path,
        fgcr_summary_path=str(fgcr_summary_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Gate C canonical + decision-set dual reports.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--review-log")
    parser.add_argument("--rework-log")
    parser.add_argument("--stability-log")
    parser.add_argument("--output-dir")
    parser.add_argument("--fgcr-events")
    parser.add_argument("--format", choices=["human", "json"], default="human")
    args = parser.parse_args()

    result = generate_dual_report(
        project_root=Path(args.project_root),
        window_id=args.window_id,
        review_log=Path(args.review_log) if args.review_log else None,
        rework_log=Path(args.rework_log) if args.rework_log else None,
        stability_log=Path(args.stability_log) if args.stability_log else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        fgcr_events=Path(args.fgcr_events) if args.fgcr_events else None,
    )

    if args.format == "json":
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    else:
        print(
            f"summary=gate_c_dual_report | OK | window={result.window_id}; "
            f"canonical={result.canonical_report_path}; "
            f"decision={result.decision_report_path}; "
            f"manifest={result.decision_manifest_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
