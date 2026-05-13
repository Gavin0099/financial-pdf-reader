#!/usr/bin/env python3
"""
Evaluate minimal host-agent memory sync signals from policy-level inputs.

This module does not talk to any host memory API. It only turns the sync policy
surface into explicit, reviewable signals.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass


EVENT_LEVELS = frozenset({
    "memory_sync_required",
    "memory_sync_optional",
    "repo_memory_only",
})

SIGNAL_NAMES = frozenset({
    "memory_sync_missing",
    "host_memory_not_applicable",
    "repo_memory_written_only",
})


@dataclass
class MemorySyncSignalResult:
    ok: bool
    event_level: str
    repo_memory_written: bool
    host_memory_applicable: bool
    host_sync_completed: bool
    signal: str | None
    severity: str | None
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_memory_sync_signal(
    *,
    event_level: str,
    repo_memory_written: bool,
    host_memory_applicable: bool,
    host_sync_completed: bool,
) -> MemorySyncSignalResult:
    if event_level not in EVENT_LEVELS:
        raise ValueError(f"Unknown event_level: {event_level}")

    if host_sync_completed:
        return MemorySyncSignalResult(
            ok=True,
            event_level=event_level,
            repo_memory_written=repo_memory_written,
            host_memory_applicable=host_memory_applicable,
            host_sync_completed=host_sync_completed,
            signal=None,
            severity=None,
            reason="host sync completed",
        )

    if not host_memory_applicable:
        return MemorySyncSignalResult(
            ok=True,
            event_level=event_level,
            repo_memory_written=repo_memory_written,
            host_memory_applicable=host_memory_applicable,
            host_sync_completed=host_sync_completed,
            signal="host_memory_not_applicable",
            severity="info",
            reason="host memory is not available or not applicable in this run",
        )

    if event_level == "memory_sync_required":
        return MemorySyncSignalResult(
            ok=False,
            event_level=event_level,
            repo_memory_written=repo_memory_written,
            host_memory_applicable=host_memory_applicable,
            host_sync_completed=host_sync_completed,
            signal="memory_sync_missing",
            severity="warning",
            reason="memory sync is required for this event level but host sync did not complete",
        )

    if repo_memory_written:
        return MemorySyncSignalResult(
            ok=True,
            event_level=event_level,
            repo_memory_written=repo_memory_written,
            host_memory_applicable=host_memory_applicable,
            host_sync_completed=host_sync_completed,
            signal="repo_memory_written_only",
            severity="info",
            reason="repo memory was written and host sync was not required for this event level",
        )

    return MemorySyncSignalResult(
        ok=True,
        event_level=event_level,
        repo_memory_written=repo_memory_written,
        host_memory_applicable=host_memory_applicable,
        host_sync_completed=host_sync_completed,
        signal=None,
        severity=None,
        reason="no sync signal required",
    )


def format_human(result: MemorySyncSignalResult) -> str:
    lines = [
        "[host_agent_memory_sync_signal]",
        f"ok={result.ok}",
        f"event_level={result.event_level}",
        f"repo_memory_written={result.repo_memory_written}",
        f"host_memory_applicable={result.host_memory_applicable}",
        f"host_sync_completed={result.host_sync_completed}",
        f"signal={result.signal}",
        f"severity={result.severity}",
        f"reason={result.reason}",
    ]
    return "\n".join(lines)


def _bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value, got: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate host-agent memory sync policy signals.")
    parser.add_argument("--event-level", choices=sorted(EVENT_LEVELS), required=True)
    parser.add_argument("--repo-memory-written", type=_bool_arg, required=True)
    parser.add_argument("--host-memory-applicable", type=_bool_arg, required=True)
    parser.add_argument("--host-sync-completed", type=_bool_arg, required=True)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = evaluate_memory_sync_signal(
        event_level=args.event_level,
        repo_memory_written=args.repo_memory_written,
        host_memory_applicable=args.host_memory_applicable,
        host_sync_completed=args.host_sync_completed,
    )
    if args.format == "json":
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_human(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
