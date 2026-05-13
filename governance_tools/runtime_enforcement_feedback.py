#!/usr/bin/env python3
"""
Runtime enforcement feedback loop.

Records each shared runtime enforcement run as a small history entry, computes a
rolling quality-only trend over the last 7 days, and emits an advisory
framework risk signal when sustained degradation is detected.

Important metric boundary:
    - quality_score: derived only from enforcement execution outcomes
    - workflow_score: intentionally not measured here
    - system_risk: derived from sustained quality trend, not from a single run

This avoids mixing workflow completeness with enforcement quality in one score.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from governance_tools.framework_risk_signal import (
    clear_risk_signal_for_source,
    write_risk_signal,
)

_HISTORY_RELPATH = Path("artifacts") / "runtime" / "enforcement_feedback.jsonl"
_SIGNAL_SOURCE = "runtime_enforcement_feedback"
_AFFECTED_COMPONENT = "runtime_enforcement_quality_trend"
_WINDOW_DAYS = 7
_MIN_SAMPLES = 3
_ADVISORY_THRESHOLD = 4.0
_CRITICAL_THRESHOLD = 6.0


def _history_path(framework_root: Path) -> Path:
    return framework_root / _HISTORY_RELPATH


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _score_for_status(smoke_status: str, pytest_status: str) -> int:
    score = 0
    if smoke_status == "fail":
        score += 4
    if pytest_status == "fail":
        score += 2
    return score


def build_feedback_record(*, mode: str, smoke_status: str, pytest_status: str) -> dict[str, Any]:
    quality_score = _score_for_status(smoke_status, pytest_status)
    return {
        "schema_version": 1,
        "timestamp": _now().isoformat(),
        "mode": mode,
        "quality_metrics": {
            "score": quality_score,
            "smoke_status": smoke_status,
            "pytest_status": pytest_status,
            "smoke_failure": smoke_status == "fail",
            "pytest_failure": pytest_status == "fail",
        },
        "workflow_metrics": {
            "score": None,
            "status": "not_measured",
        },
        "system_risk": {
            "derived_from": "quality_trend_only",
        },
    }


def append_feedback_record(framework_root: Path, record: dict[str, Any]) -> Path:
    path = _history_path(framework_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_feedback_history(framework_root: Path, *, window_days: int = _WINDOW_DAYS) -> list[dict[str, Any]]:
    path = _history_path(framework_root)
    if not path.exists():
        return []

    min_time = _now() - timedelta(days=window_days)
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_timestamp(record.get("timestamp", ""))
            if ts is None or ts < min_time:
                continue
            records.append(record)
    return records


def summarize_feedback_trend(records: list[dict[str, Any]]) -> dict[str, Any]:
    quality_scores = [
        (record.get("quality_metrics") or {}).get("score", 0)
        for record in records
    ]
    sample_count = len(quality_scores)
    average_score = (sum(quality_scores) / sample_count) if sample_count else 0.0
    latest_score = quality_scores[-1] if quality_scores else 0

    if sample_count < _MIN_SAMPLES:
        threshold_state = "insufficient_data"
    elif average_score >= _CRITICAL_THRESHOLD:
        threshold_state = "critical"
    elif average_score >= _ADVISORY_THRESHOLD:
        threshold_state = "advisory"
    else:
        threshold_state = "ok"

    return {
        "window_days": _WINDOW_DAYS,
        "sample_count": sample_count,
        "minimum_samples": _MIN_SAMPLES,
        "average_quality_score": round(average_score, 2),
        "latest_quality_score": latest_score,
        "max_quality_score": max(quality_scores) if quality_scores else 0,
        "threshold_state": threshold_state,
        "quality_thresholds": {
            "advisory": _ADVISORY_THRESHOLD,
            "critical": _CRITICAL_THRESHOLD,
        },
        "metric_boundary": {
            "quality_score": "measured",
            "workflow_score": "not_measured",
            "system_risk": "derived_from_quality_trend",
        },
    }


def record_feedback(
    framework_root: Path,
    *,
    mode: str,
    smoke_status: str,
    pytest_status: str,
    emit_risk_signal: bool = False,
) -> dict[str, Any]:
    record = build_feedback_record(
        mode=mode,
        smoke_status=smoke_status,
        pytest_status=pytest_status,
    )
    append_feedback_record(framework_root, record)
    trend = summarize_feedback_trend(read_feedback_history(framework_root))

    signal_written = False
    signal_cleared = False
    if emit_risk_signal:
        state = trend["threshold_state"]
        if state in {"advisory", "critical"}:
            severity = "warning" if state == "advisory" else "critical"
            write_risk_signal(
                framework_root,
                affected_components=[_AFFECTED_COMPONENT],
                severity=severity,
                source=_SIGNAL_SOURCE,
            )
            signal_written = True
        elif state == "ok":
            signal_cleared = clear_risk_signal_for_source(framework_root, _SIGNAL_SOURCE)

    return {
        "record": record,
        "trend": trend,
        "signal_written": signal_written,
        "signal_cleared": signal_cleared,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record runtime enforcement history and emit advisory trend signals.")
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Append one enforcement result and optionally emit a signal.")
    record.add_argument("--framework-root", default=".")
    record.add_argument("--mode", required=True)
    record.add_argument("--smoke-status", choices=("pass", "fail", "skipped"), required=True)
    record.add_argument("--pytest-status", choices=("pass", "fail", "skipped"), required=True)
    record.add_argument("--emit-signal", action="store_true")
    record.add_argument("--format", choices=("human", "json"), default="human")

    show = sub.add_parser("show", help="Show the current 7-day trend summary.")
    show.add_argument("--framework-root", default=".")
    show.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def _format_human(payload: dict[str, Any]) -> str:
    trend = payload["trend"]
    lines = [
        "[runtime_enforcement_feedback]",
        f"average_quality_score={trend['average_quality_score']}",
        f"latest_quality_score={trend['latest_quality_score']}",
        f"sample_count={trend['sample_count']}",
        f"threshold_state={trend['threshold_state']}",
        "metric_boundary=quality-only; workflow-score-not-measured",
    ]
    if "record" in payload:
        qm = payload["record"]["quality_metrics"]
        lines.append(f"smoke_status={qm['smoke_status']}")
        lines.append(f"pytest_status={qm['pytest_status']}")
    if payload.get("signal_written"):
        lines.append(f"signal_written=True source={_SIGNAL_SOURCE}")
    if payload.get("signal_cleared"):
        lines.append(f"signal_cleared=True source={_SIGNAL_SOURCE}")
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    framework_root = Path(args.framework_root).resolve()
    if args.command == "record":
        result = record_feedback(
            framework_root,
            mode=args.mode,
            smoke_status=args.smoke_status,
            pytest_status=args.pytest_status,
            emit_risk_signal=args.emit_signal,
        )
    else:
        result = {
            "trend": summarize_feedback_trend(read_feedback_history(framework_root)),
            "signal_written": False,
            "signal_cleared": False,
        }
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_human(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())