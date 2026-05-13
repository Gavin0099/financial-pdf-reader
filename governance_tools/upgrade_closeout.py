#!/usr/bin/env python3
"""
upgrade_closeout — opt-in patch: add Session Closeout Obligation to a repo's AGENTS.base.md.

Purpose: Phase 2 of the closeout readiness rollout. Repos adopted before
the closeout obligation was added to the baseline can be upgraded without
a full re-adoption.

Usage:
    # Preview the patch (no files written)
    python -m governance_tools.upgrade_closeout --repo /path/to/repo --dry-run

    # Apply the patch
    python -m governance_tools.upgrade_closeout --repo /path/to/repo

    # Apply to multiple repos
    python -m governance_tools.upgrade_closeout --repo /path/a /path/b

What it does:
    1. Finds AGENTS.base.md (or AGENTS.md) in the target repo
    2. Checks whether "Session Closeout Obligation" is already present
    3. If missing, appends the obligation section from the framework baseline
    4. Shows a diff before writing (unless --no-diff)
    5. Never touches any file except the AGENTS file

What it does NOT do:
    - Does not re-adopt the full governance baseline
    - Does not modify contract.yaml or .governance/
    - Does not run session_end_hook
    - Does not touch memory/ files

IMPORTANT — anti-misuse:
    Running upgrade_closeout means the obligation text is present in AGENTS.base.md.
    It does NOT mean the repo has upgraded its governance quality, closeout
    compliance, or memory promotion rate. It is an instruction surface change,
    not a quality certification. Do not treat "ran upgrade_closeout" as equivalent
    to "closeout governance is working". The stop hook provides enforcement;
    this tool only provides instruction.

Rollback:
    The patch is an append-only operation. To rollback:
        git checkout HEAD -- AGENTS.base.md
    Or manually remove everything after the "## Session Closeout Obligation" line.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ── Obligation text ───────────────────────────────────────────────────────────
# Canonical source: baselines/repo-min/AGENTS.base.md
# This is an embedded copy so upgrade_closeout works without reading the
# framework baseline at runtime (reducing path dependency in cross-repo use).

_OBLIGATION_SECTION = """
## Session Closeout Obligation

Writing `artifacts/session-closeout.txt` before session end is a **governance
obligation**, not a suggestion.

The stop hook always calls `session_end` at session end. If the closeout artifact
is missing or insufficient, the runtime records `closeout_missing` or
`closeout_insufficient` in the verdict. Memory will not update. The gap is
auditable and visible to reviewers.

### Required fields

All fields must be present. Vague values are flagged as insufficient.

```
TASK_INTENT: <one sentence — declared goal of this session>
WORK_COMPLETED: <what was actually done — verifiable claims only>
FILES_TOUCHED: <comma-separated file list, or NONE>
CHECKS_RUN: <specific commands or checks run, or NONE>
OPEN_RISKS: <what might be wrong or incomplete, or NONE>
NOT_DONE: <what was not completed this session, or NONE>
RECOMMENDED_MEMORY_UPDATE: <what memory/ file should change and why, or NO_UPDATE>
```

### Rules

- `WORK_COMPLETED` must contain verifiable claims. Do not write "made improvements"
  or "worked on things" — these are vague and will be rejected as insufficient.
- `CHECKS_RUN` must name specific commands if non-`NONE`.
- If there was no material progress, write `WORK_COMPLETED: NONE` — do not
  fabricate completions.
- `NOT_DONE` and `OPEN_RISKS` are the most important fields. AI agents tend to
  omit failures. Do not.

### Observable anchor requirement

`WORK_COMPLETED` and `CHECKS_RUN` must contain an observable anchor:
a filename (`word.ext`) or a known tool name (pytest, session_end_hook, etc.).
A sentence with no such anchor is treated as vague content even if it looks specific.

### If you cannot write the closeout

Write it anyway with `WORK_COMPLETED: NONE` and explain in `OPEN_RISKS` why
the session produced no verifiable output. This is a valid closeout.

See `docs/session-closeout-schema.md` for examples and field constraints.
"""


def _find_agents_file(repo: Path) -> Path | None:
    for name in ["AGENTS.base.md", "AGENTS.md"]:
        candidate = repo / name
        if candidate.exists():
            return candidate
    return None


def _already_patched(agents_file: Path) -> bool:
    try:
        text = agents_file.read_text(encoding="utf-8", errors="replace")
        return "Session Closeout Obligation" in text
    except Exception:
        return False


def _show_diff(original: str, patched: str, filename: str) -> None:
    """Print a simple unified-style diff of the appended section."""
    import difflib
    diff = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        patched.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=3,
    ))
    if diff:
        print("".join(diff))
    else:
        print("(no diff — files are identical)")


def upgrade_repo(
    repo: Path,
    *,
    dry_run: bool = False,
    show_diff: bool = True,
    framework_root: Path | None = None,
) -> dict:
    """
    Apply (or preview) the closeout obligation patch for a single repo.

    Returns a result dict with keys:
        repo, agents_file, status, message
    Status values: already_patched | patched | dry_run | no_agents_file | error
    """
    repo = repo.resolve()

    if not repo.exists():
        return {
            "repo": str(repo),
            "agents_file": None,
            "status": "error",
            "message": f"repo path does not exist: {repo}",
        }

    agents_file = _find_agents_file(repo)
    if agents_file is None:
        return {
            "repo": str(repo),
            "agents_file": None,
            "status": "no_agents_file",
            "message": (
                "Neither AGENTS.base.md nor AGENTS.md found in repo root. "
                "Run adopt_governance.py first."
            ),
        }

    if _already_patched(agents_file):
        return {
            "repo": str(repo),
            "agents_file": str(agents_file),
            "status": "already_patched",
            "message": "Session Closeout Obligation already present — no changes needed.",
        }

    try:
        original = agents_file.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {
            "repo": str(repo),
            "agents_file": str(agents_file),
            "status": "error",
            "message": f"could not read {agents_file.name}: {exc}",
        }

    # Append obligation (with a blank line separator if file doesn't end in one)
    separator = "\n" if original.endswith("\n") else "\n\n"
    patched = original + separator + _OBLIGATION_SECTION.lstrip("\n")

    if show_diff:
        print(f"\n── Diff for {agents_file} ──")
        _show_diff(original, patched, agents_file.name)

    if dry_run:
        return {
            "repo": str(repo),
            "agents_file": str(agents_file),
            "status": "dry_run",
            "message": f"[dry-run] Would patch {agents_file.name} (+{len(_OBLIGATION_SECTION.splitlines())} lines)",
        }

    try:
        agents_file.write_text(patched, encoding="utf-8")
        return {
            "repo": str(repo),
            "agents_file": str(agents_file),
            "status": "patched",
            "message": f"Patched {agents_file.name} — Session Closeout Obligation added.",
        }
    except Exception as exc:
        return {
            "repo": str(repo),
            "agents_file": str(agents_file),
            "status": "error",
            "message": f"write failed: {exc}",
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patch AGENTS.base.md with the Session Closeout Obligation section."
    )
    parser.add_argument(
        "--repo",
        nargs="+",
        required=True,
        metavar="PATH",
        help="One or more repo paths to patch",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show diff without writing any files",
    )
    parser.add_argument(
        "--no-diff",
        action="store_true",
        help="Suppress diff output (useful in scripts)",
    )
    parser.add_argument(
        "--framework-root",
        metavar="PATH",
        default=str(Path(__file__).resolve().parents[1]),
        help="Path to framework repo (default: auto-detected)",
    )
    args = parser.parse_args()

    framework_root = Path(args.framework_root).resolve()
    any_error = False

    for repo_str in args.repo:
        repo = Path(repo_str)
        print(f"\n[upgrade_closeout] repo: {repo}")

        result = upgrade_repo(
            repo,
            dry_run=args.dry_run,
            show_diff=not args.no_diff,
            framework_root=framework_root,
        )

        status = result["status"]
        message = result["message"]

        if status == "patched":
            print(f"  ✓ {message}")
        elif status == "already_patched":
            print(f"  = {message}")
        elif status == "dry_run":
            print(f"  ~ {message}")
        elif status == "no_agents_file":
            print(f"  ! {message}")
            any_error = True
        elif status == "error":
            print(f"  ✗ {message}")
            any_error = True

    sys.exit(1 if any_error else 0)


if __name__ == "__main__":
    main()
