#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

_REAL_HASH = re.compile(r'^[a-f0-9]{5,40}$', re.IGNORECASE)

WRITER_ID = "governance_tools.memory_record"
RECORD_FORMAT_VERSION = "1.0"
MEMORY_TYPE_SESSION_DERIVED = "session-derived"


def _current_local_date() -> str:
    return datetime.now().astimezone().date().isoformat()


def build_session_derived_record(
    *,
    what_changed: str,
    commit: str,
    session_id: str,
    memory_binding: str,
    test_evidence: str,
    next_step: str,
) -> dict[str, str]:
    return {
        "memory_type": MEMORY_TYPE_SESSION_DERIVED,
        "record_format_version": RECORD_FORMAT_VERSION,
        "writer": WRITER_ID,
        "what_changed": what_changed,
        "commit": commit,
        "commit_hash": commit,
        "session_id": session_id,
        "memory_binding": memory_binding,
        "test_evidence": test_evidence,
        "next_step": next_step,
    }


def render_session_derived_entry(record: dict[str, str]) -> str:
    return (
        f"- memory_type: {record['memory_type']}\n"
        f"  record_format_version: {record['record_format_version']}\n"
        f"  writer: {record['writer']}\n"
        f"  what_changed: {record['what_changed']}\n"
        f"  commit: {record['commit']}\n"
        f"  commit_hash: {record['commit_hash']}\n"
        f"  session_id: {record['session_id']}\n"
        f"  memory_binding: {record['memory_binding']}\n"
        f"  test_evidence: {record['test_evidence']}\n"
        f"  next_step: {record['next_step']}\n"
    )


def append_session_derived_entry(*, project_root: Path, record: dict[str, str]) -> Path:
    memory_root = project_root / "memory"
    memory_root.mkdir(parents=True, exist_ok=True)
    daily_path = memory_root / f"{_current_local_date()}.md"
    if not daily_path.exists():
        daily_path.write_text(f"# {_current_local_date()}\n\n", encoding="utf-8")

    entry = render_session_derived_entry(record)
    with daily_path.open("a", encoding="utf-8") as fh:
        if daily_path.stat().st_size > 0:
            fh.write("\n")
        fh.write(entry)
    return daily_path


def _auto_detect_commit(project_root: Path) -> str:
    """Best-effort: read the latest git commit hash. Returns 'UNCOMMITTED' on failure."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h"],
            capture_output=True, text=True, cwd=project_root, timeout=5,
        )
        h = result.stdout.strip()
        return h if h else "UNCOMMITTED"
    except Exception:
        return "UNCOMMITTED"


def build_memory_record_suggestion(
    *,
    what_changed: str,
    commit: str,
    session_id: str,
    next_step: str = "[fill in]",
    project_root: str = ".",
) -> str:
    """Return a ready-to-paste CLI command that writes a canonical memory entry."""
    return (
        f"python governance_tools/memory_record.py"
        f' --what-changed "{what_changed}"'
        f" --commit {commit}"
        f" --session-id {session_id}"
        f' --next-step "{next_step}"'
        f" --project-root {project_root}"
    )


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Append a canonical session-derived memory entry to memory/YYYY-MM-DD.md."
    )
    parser.add_argument("--what-changed", required=True, help="Summary of what changed this session")
    parser.add_argument("--next-step", required=True, help="What to do next")
    parser.add_argument("--commit", default=None, help="Git commit hash (auto-detected if omitted)")
    parser.add_argument("--session-id", default=None, help="Session ID (timestamp-based if omitted)")
    parser.add_argument("--test-evidence", default="", help="Test run evidence")
    parser.add_argument("--project-root", default=".", help="Repository root (default: .)")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    commit = args.commit or _auto_detect_commit(project_root)
    session_id = args.session_id or f"cli-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    memory_binding = "bound" if _REAL_HASH.match(commit) else "unbound"

    record = build_session_derived_record(
        what_changed=args.what_changed,
        commit=commit,
        session_id=session_id,
        memory_binding=memory_binding,
        test_evidence=args.test_evidence,
        next_step=args.next_step,
    )
    path = append_session_derived_entry(project_root=project_root, record=record)
    print(f"[memory_record] Written: {path}")
    print(render_session_derived_entry(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
