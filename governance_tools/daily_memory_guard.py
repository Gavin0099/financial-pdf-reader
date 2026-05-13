#!/usr/bin/env python3
"""
Advisory-only daily memory guard for pre-push surfaces.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def _local_today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _latest_runtime_summary(project_root: Path) -> dict | None:
    summaries_dir = project_root / "artifacts" / "runtime" / "summaries"
    if not summaries_dir.is_dir():
        return None

    latest_path: Path | None = None
    latest_closed_at = ""
    for path in summaries_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        closed_at = str(payload.get("closed_at") or "")
        if closed_at >= latest_closed_at:
            latest_closed_at = closed_at
            latest_path = path

    if latest_path is None:
        return None
    return json.loads(latest_path.read_text(encoding="utf-8"))


def evaluate_daily_memory_warning(project_root: Path) -> dict:
    today_path = project_root / "memory" / f"{_local_today()}.md"
    latest_summary = _latest_runtime_summary(project_root)

    if latest_summary is None:
        return {
            "warn": False,
            "warning_code": None,
            "reason": "no_runtime_summary",
            "today_memory_path": str(today_path),
            "latest_session_id": None,
        }

    memory_mode = str(latest_summary.get("memory_mode") or "")
    if memory_mode == "stateless":
        return {
            "warn": False,
            "warning_code": None,
            "reason": "stateless_session",
            "today_memory_path": str(today_path),
            "latest_session_id": latest_summary.get("session_id"),
        }

    daily_memory_path = latest_summary.get("daily_memory_path")
    if daily_memory_path and Path(daily_memory_path).exists():
        return {
            "warn": False,
            "warning_code": None,
            "reason": "summary_daily_memory_present",
            "today_memory_path": str(today_path),
            "latest_session_id": latest_summary.get("session_id"),
        }

    daily_memory_record = latest_summary.get("daily_memory_record") or {}
    governance_relevant = any(
        str(daily_memory_record.get(field) or "").strip()
        for field in ("commit", "test_evidence", "what_changed", "next_step")
    )

    if governance_relevant:
        return {
            "warn": True,
            "warning": "daily_memory_missing_warning",
            "warning_code": "daily_memory_missing_warning",
            "scope": "latest_session",
            "push_allowed": True,
            "reason": "session_level_daily_memory_missing",
            "machine_reason": "governance_relevant_session_missing_daily_memory_path",
            "today_memory_path": str(today_path),
            "latest_session_id": latest_summary.get("session_id"),
            "memory_mode": memory_mode,
            "decision": latest_summary.get("decision"),
        }

    if today_path.exists():
        return {
            "warn": False,
            "warning_code": None,
            "reason": "legacy_today_daily_memory_present",
            "today_memory_path": str(today_path),
            "latest_session_id": latest_summary.get("session_id"),
        }

    return {
        "warn": False,
        "warning_code": None,
        "reason": "non_governance_relevant_session_without_daily_memory",
        "today_memory_path": str(today_path),
        "latest_session_id": latest_summary.get("session_id"),
    }


def format_human(result: dict) -> str:
    if not result["warn"]:
        return ""
    return (
        "[daily_memory_guard] daily_memory_missing_warning: "
        "latest non-stateless governance-relevant session has no daily_memory_path. "
        "push allowed; review whether session_end failed to append daily memory. "
        f"latest_session_id={result.get('latest_session_id')} "
        f"today_memory_path={result.get('today_memory_path')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Advisory-only daily memory guard.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = evaluate_daily_memory_warning(Path(args.project_root).resolve())
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        output = format_human(result)
        if output:
            print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
