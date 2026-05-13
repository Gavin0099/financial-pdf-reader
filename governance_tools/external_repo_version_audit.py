#!/usr/bin/env python3
"""
Audit external repos for adopted framework release state.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.external_repo_readiness import assess_external_repo


def build_report(repo_roots: list[Path]) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    for repo_root in repo_roots:
        result = assess_external_repo(repo_root)
        version = result.framework_version or {}
        state = str(version.get("state") or "unknown")
        counts[state] += 1
        entries.append(
            {
                "repo_root": result.repo_root,
                "ready": result.ready,
                "version_state": state,
                "current_release": version.get("current_release"),
                "adopted_release": version.get("adopted_release"),
                "adopted_commit": version.get("adopted_commit"),
                "framework_repo": version.get("framework_repo"),
                "canonical_framework_repo": version.get("canonical_framework_repo"),
                "compatibility_range": version.get("compatibility_range"),
                "lock_file": version.get("lock_file"),
                "warnings": result.warnings,
                "errors": result.errors,
            }
        )
    return {
        "repo_count": len(entries),
        "state_counts": dict(sorted(counts.items())),
        "entries": entries,
    }


def format_human(report: dict[str, object]) -> str:
    lines = [
        "[external_repo_version_audit]",
        f"repo_count={report['repo_count']}",
        f"state_counts={json.dumps(report['state_counts'], ensure_ascii=False, sort_keys=True)}",
    ]
    entries = report.get("entries") or []
    if entries:
        lines.append("[repos]")
        for entry in entries:
            lines.append(
                " | ".join(
                    [
                        str(entry.get("repo_root")),
                        f"ready={entry.get('ready')}",
                        f"state={entry.get('version_state')}",
                        f"adopted_release={entry.get('adopted_release')}",
                        f"current_release={entry.get('current_release')}",
                        f"source_ok={entry.get('framework_repo') == entry.get('canonical_framework_repo')}",
                        f"compatibility_range={entry.get('compatibility_range')}",
                    ]
                )
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit external repos for framework version drift.")
    parser.add_argument("--repo", action="append", required=True, help="External repo root. Repeat for multiple repos.")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = build_report([Path(item) for item in args.repo])
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_human(report))
    has_incompatible = any(entry["version_state"] == "incompatible" for entry in report["entries"])
    return 1 if has_incompatible else 0


if __name__ == "__main__":
    raise SystemExit(main())
