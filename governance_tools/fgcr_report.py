#!/usr/bin/env python3
"""
FGCR v0.1 reporter.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_LANES = {"chatgpt", "claude", "copilot"}
VALID_CONFIDENCE_MARKS = {"PASS", "READY", "SAFE", "COMPLETE"}
VALID_FAILURE_TYPES = {
    "hidden_omission",
    "invalid_projection",
    "stale_evidence_dependency",
    "contradictory_runtime_state",
    "unauthorized_inference",
}
VALID_DISCOVERY_SCOPE = {"same_session", "same_window", "next_window", "post_release"}
VALID_EVIDENCE_LAYER = {"framework_supported", "run_observed", "hypothesis"}


@dataclass
class FgcrLaneResult:
    confidence_marked_events: int
    false_confidence_events: int
    fgcr: float | None
    status: str
    by_failure_type: dict[str, int]


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            items.append(json.loads(s))
    return items


def _validate_event(event: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "event_id",
        "window_id",
        "lane",
        "confidence_mark",
        "later_failure_type",
        "discovery_scope",
        "artifact_anchor",
        "evidence_layer",
    }
    for key in required:
        if key not in event:
            errors.append(f"missing:{key}")
    if errors:
        return errors

    if not str(event.get("event_id", "")).strip():
        errors.append("invalid:event_id")
    if not str(event.get("window_id", "")).strip():
        errors.append("invalid:window_id")
    if not str(event.get("artifact_anchor", "")).strip():
        errors.append("invalid:artifact_anchor")

    if event.get("lane") not in VALID_LANES:
        errors.append("invalid:lane")
    if event.get("confidence_mark") not in VALID_CONFIDENCE_MARKS:
        errors.append("invalid:confidence_mark")
    if event.get("later_failure_type") not in VALID_FAILURE_TYPES:
        errors.append("invalid:later_failure_type")
    if event.get("discovery_scope") not in VALID_DISCOVERY_SCOPE:
        errors.append("invalid:discovery_scope")
    if event.get("evidence_layer") not in VALID_EVIDENCE_LAYER:
        errors.append("invalid:evidence_layer")
    return errors


def build_fgcr_report(events: list[dict[str, Any]], window_id: str, *, min_sample: int = 3) -> dict[str, Any]:
    invalid_events: list[dict[str, Any]] = []
    valid_events: list[dict[str, Any]] = []

    for e in events:
        errs = _validate_event(e)
        if errs:
            invalid_events.append({"event": e, "errors": errs})
            continue
        if e["window_id"] != window_id:
            continue
        valid_events.append(e)

    lane_marked_counts: dict[str, int] = defaultdict(int)
    lane_false_counts: dict[str, int] = defaultdict(int)
    lane_failure_type: dict[str, Counter[str]] = defaultdict(Counter)
    by_window_failure_type: Counter[str] = Counter()

    for e in valid_events:
        lane = e["lane"]
        lane_marked_counts[lane] += 1
        # protection: hypothesis does not enter numerator
        if e["evidence_layer"] != "hypothesis":
            lane_false_counts[lane] += 1
            lane_failure_type[lane][e["later_failure_type"]] += 1
            by_window_failure_type[e["later_failure_type"]] += 1

    by_lane: dict[str, FgcrLaneResult] = {}
    for lane in sorted(VALID_LANES):
        marked = lane_marked_counts.get(lane, 0)
        false = lane_false_counts.get(lane, 0)
        if marked < min_sample:
            by_lane[lane] = FgcrLaneResult(
                confidence_marked_events=marked,
                false_confidence_events=false,
                fgcr=None,
                status="insufficient_sample",
                by_failure_type=dict(lane_failure_type.get(lane, Counter())),
            )
        else:
            by_lane[lane] = FgcrLaneResult(
                confidence_marked_events=marked,
                false_confidence_events=false,
                fgcr=round(false / marked, 6),
                status="ok",
                by_failure_type=dict(lane_failure_type.get(lane, Counter())),
            )

    total_marked = sum(x.confidence_marked_events for x in by_lane.values())
    total_false = sum(x.false_confidence_events for x in by_lane.values())
    if total_marked < min_sample:
        by_window = {
            "confidence_marked_events": total_marked,
            "false_confidence_events": total_false,
            "fgcr": None,
            "status": "insufficient_sample",
            "by_failure_type": dict(by_window_failure_type),
        }
    else:
        by_window = {
            "confidence_marked_events": total_marked,
            "false_confidence_events": total_false,
            "fgcr": round(total_false / total_marked, 6),
            "status": "ok",
            "by_failure_type": dict(by_window_failure_type),
        }

    return {
        "window_id": window_id,
        "min_sample": min_sample,
        "valid_event_count": len(valid_events),
        "invalid_event_count": len(invalid_events),
        "invalid_events": invalid_events,
        "by_lane": {k: v.__dict__ for k, v in by_lane.items()},
        "by_window": by_window,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate FGCR v0.1 report from events.")
    parser.add_argument("--events", required=True, help="FGCR event NDJSON path")
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--min-sample", type=int, default=3)
    parser.add_argument("--format", choices=["human", "json"], default="human")
    parser.add_argument("--output")
    args = parser.parse_args()

    events = _read_ndjson(Path(args.events))
    report = build_fgcr_report(events, args.window_id, min_sample=args.min_sample)

    if args.format == "json":
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        by_window = report["by_window"]
        fgcr_label = by_window["fgcr"] if by_window["fgcr"] is not None else "insufficient_sample"
        rendered = (
            f"summary=fgcr | window={report['window_id']} | "
            f"marked={by_window['confidence_marked_events']} | "
            f"false={by_window['false_confidence_events']} | fgcr={fgcr_label}"
        )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + ("\n" if not rendered.endswith("\n") else ""), encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

