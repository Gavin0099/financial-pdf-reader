#!/usr/bin/env python3
"""
session_closeout_entry.py — Agent-agnostic session closeout entrypoint.

This is the single canonical command that executes the governance closeout
pipeline. Every agent integration (Claude, Copilot, Gemini, ChatGPT) calls
this command — or instructs the user to call it manually. The agent adapter
layer decides *when* and *how* this gets triggered; this module defines *what*
happens.

Usage:
    python -m governance_tools.session_closeout_entry --project-root .
    python -m governance_tools.session_closeout_entry --project-root . --format json

Exit codes:
    0  closeout executed (pipeline ran, regardless of closeout content quality)
    1  pipeline failed to run (runtime error, not closeout content failure)

Closeout content quality (missing file, schema invalid, etc.) is reported in
the output but does NOT cause a non-zero exit. The pipeline ran; the verdict
records the quality gap. Failing on content quality would make the stop hook
itself unreliable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from governance_tools.session_end_hook import run_session_end_hook, format_human_result


def run(project_root: Path) -> dict[str, Any]:
    """
    Execute the closeout pipeline for the given project root.

    This is the single callable entry point for all agent adapters.
    It delegates entirely to session_end_hook.run_session_end_hook, which
    handles: closeout file classification, memory snapshot, promotion policy,
    verdict and trace artifact emission.
    """
    return run_session_end_hook(project_root=project_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Agent-agnostic session closeout entrypoint. "
            "Executes the governance closeout pipeline for the current project. "
            "Called by agent integrations (Claude stop hook, Copilot task, etc.) "
            "or manually at session end."
        )
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Path to the project root (default: current directory)",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    try:
        result = run(project_root)
    except Exception as exc:
        if args.format == "json":
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"[session_closeout_entry] runtime error: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))

    # Exit 0 if pipeline ran. Content quality gaps are in the output, not exit code.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
