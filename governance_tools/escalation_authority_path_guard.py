#!/usr/bin/env python3
"""
Static guard: ensure escalation authority artifacts are only written
through governance_tools/escalation_authority_writer.py.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path


# Policy list of files that are allowed to write to escalation authority paths.
# Each entry is a policy object, not just a name.
#
# invalid_if.pattern  — grep-based automated check: if any pattern appears in
#                       the file content, the exception has grown beyond its
#                       sanctioned scope (early warning, not a security gate).
# invalid_if.semantic — human-audit constraints (not machine-enforced).
# review_required     — True means stale check applies: warn after admitted_date
#                       passes max_days (default 90d) without re-review.
_ALLOWED_WRITERS: list[dict] = [
    {
        "file": "governance_tools/escalation_authority_writer.py",
        "reason": "primary escalation authority writer",
        "review_required": False,
        "invalid_if": {
            "pattern": [],
            "semantic": [],
        },
    },
    {
        "file": "governance_tools/mutation_proof_runner.py",
        "reason": "controlled mutation verification test harness",
        "source_commit": "551d433",
        "admitted_date": "2026-05-03",
        "review_required": True,
        "invalid_if": {
            "pattern": [
                "write_authority_decision(",
                "register_escalation_decision(",
            ],
            "semantic": [
                "introduces new authority lifecycle transitions outside test fixture scope",
                "writes escalation authority without going through the canonical writer",
            ],
        },
    },
]

ALLOWED_WRITER_FILES = {e["file"] for e in _ALLOWED_WRITERS}
WRITE_PATTERNS = (
    ".write_text(",
    ".open(",
    "json.dump(",
)
AUTHORITY_PATH_TOKENS = (
    "e1b-phase-b-escalation",
    "authority",
)


def find_direct_write_violations(project_root: Path) -> list[dict[str, str | int]]:
    violations: list[dict[str, str | int]] = []
    scope_roots = [project_root / "governance_tools", project_root / "runtime_hooks"]

    for scope_root in scope_roots:
        if not scope_root.is_dir():
            continue
        for py_file in scope_root.rglob("*.py"):
            rel = py_file.relative_to(project_root).as_posix()
            if rel in ALLOWED_WRITER_FILES:
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
            except OSError:
                continue

            has_authority_path_token = all(token in content for token in AUTHORITY_PATH_TOKENS)
            if not has_authority_path_token:
                continue

            for idx, line in enumerate(content.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if any(token in stripped for token in AUTHORITY_PATH_TOKENS) and any(
                    pattern in stripped for pattern in WRITE_PATTERNS
                ):
                    violations.append(
                        {
                            "file": rel,
                            "line": idx,
                            "reason": "direct escalation authority artifact write outside authority writer",
                        }
                    )

            # Catch split-line writes in a coarse way (path token elsewhere in file + write API call line).
            if not any(v["file"] == rel for v in violations):
                write_lines = [
                    i + 1
                    for i, l in enumerate(content.splitlines())
                    if any(pattern in l for pattern in WRITE_PATTERNS)
                ]
                if write_lines:
                    path_mentions = [
                        i + 1
                        for i, l in enumerate(content.splitlines())
                        if all(token in l for token in AUTHORITY_PATH_TOKENS)
                    ]
                    if path_mentions and write_lines:
                        violations.append(
                            {
                                "file": rel,
                                "line": write_lines[0],
                                "reason": "potential split-line direct write to escalation authority path outside authority writer",
                            }
                        )

    return violations


def check_invalid_if_violations(project_root: Path) -> list[dict]:
    """Check that each allowed writer hasn't grown beyond its sanctioned scope.

    For each entry with invalid_if.pattern, grep the file content.
    Matches are early warnings — they indicate the exception may need re-review,
    not that the file is necessarily malicious.
    """
    results: list[dict] = []
    for entry in _ALLOWED_WRITERS:
        patterns = entry.get("invalid_if", {}).get("pattern", [])
        if not patterns:
            continue
        file_path = project_root / entry["file"]
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for pattern in patterns:
            if pattern in content:
                results.append({
                    "file": entry["file"],
                    "pattern": pattern,
                    "reason": f"allowed writer exhibits forbidden pattern: {pattern!r}",
                })
    return results


def check_stale_exceptions(max_days: int = 90) -> list[str]:
    """Return warning strings for allowed-writer entries that are overdue for re-review."""
    today = date.today()
    warnings: list[str] = []
    for entry in _ALLOWED_WRITERS:
        if not entry.get("review_required"):
            continue
        admitted_str = entry.get("admitted_date")
        if not admitted_str:
            warnings.append(f"review_required entry missing admitted_date: {entry['file']}")
            continue
        try:
            admitted = date.fromisoformat(admitted_str)
        except ValueError:
            continue
        age = (today - admitted).days
        if age > max_days:
            warnings.append(
                f"stale_exception:{entry['file']} admitted={admitted_str} age={age}d (max={max_days}d)"
            )
    return warnings


def run_guard(project_root: Path) -> dict:
    violations = find_direct_write_violations(project_root)
    constraint_warnings = check_invalid_if_violations(project_root)
    stale_warnings = check_stale_exceptions()
    return {
        "ok": len(violations) == 0,
        "project_root": str(project_root),
        "allowed_writer_files": sorted(ALLOWED_WRITER_FILES),
        "violation_count": len(violations),
        "violations": violations,
        "constraint_warnings": constraint_warnings,
        "stale_warnings": stale_warnings,
    }


def _format_human(result: dict) -> str:
    lines = [
        "[escalation_authority_path_guard]",
        f"ok={result['ok']}",
        f"allowed_writer_files={','.join(result['allowed_writer_files'])}",
        f"violation_count={result['violation_count']}",
    ]
    for item in result["violations"]:
        lines.append(f"violation={item['file']}:{item['line']}:{item['reason']}")
    for w in result.get("constraint_warnings", []):
        lines.append(f"constraint_warning={w['file']}:{w['pattern']}")
    for w in result.get("stale_warnings", []):
        lines.append(f"stale_warning={w}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect direct escalation authority artifact writes outside the authority writer.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    result = run_guard(Path(args.project_root).resolve())
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_human(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
