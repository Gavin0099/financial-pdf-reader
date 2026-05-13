#!/usr/bin/env python3
"""
Recommend semantic version bump level from changed file paths.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


LEVEL_ORDER = {"none": 0, "patch": 1, "minor": 2, "major": 3}

MAJOR_PATHS = {
    "governance/runtime/required_versions.yaml",
}

MINOR_PREFIXES = (
    "governance_tools/",
    "runtime_hooks/",
    "governance/rules/",
    "scripts/",
)

NONE_PREFIXES = (
    "docs/",
    "memory/",
    "artifacts/",
    "archive/",
)


@dataclass
class BumpDecision:
    recommended_bump: str
    changed_files: list[str]
    reasons: list[str]
    manual_review_required: bool


def _max_level(current: str, incoming: str) -> str:
    return incoming if LEVEL_ORDER[incoming] > LEVEL_ORDER[current] else current


def classify_file(path: str) -> tuple[str, str]:
    normalized = path.replace("\\", "/")
    name = Path(normalized).name.lower()

    if normalized in MAJOR_PATHS:
        return "major", f"{normalized}: runtime compatibility floor changed"

    if normalized.startswith(NONE_PREFIXES):
        return "none", f"{normalized}: documentation/memory/artifact scope"

    if normalized.endswith(".md"):
        return "none", f"{normalized}: markdown-only change"

    if normalized.startswith("tests/"):
        return "patch", f"{normalized}: test surface changed"

    if normalized.startswith(MINOR_PREFIXES):
        return "minor", f"{normalized}: governance/runtime/tooling feature surface changed"

    if name in {"readme.md", "changelog.md"}:
        return "none", f"{normalized}: release/document surface"

    return "patch", f"{normalized}: code/config change outside doc-only scope"


def evaluate_paths(paths: list[str]) -> BumpDecision:
    level = "none"
    reasons: list[str] = []
    for path in paths:
        file_level, reason = classify_file(path)
        level = _max_level(level, file_level)
        reasons.append(reason)
    return BumpDecision(
        recommended_bump=level,
        changed_files=paths,
        reasons=reasons,
        manual_review_required=(level == "major"),
    )


def _git_changed_files(base_ref: str, head_ref: str) -> list[str]:
    cmd = ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return sorted(dict.fromkeys(files))


def format_human(result: BumpDecision) -> str:
    lines = [
        "[version_bump_guard]",
        f"recommended_bump={result.recommended_bump}",
        f"changed_files={len(result.changed_files)}",
        f"manual_review_required={result.manual_review_required}",
    ]
    if result.changed_files:
        lines.append("[files]")
        lines.extend(result.changed_files)
    if result.reasons:
        lines.append("[reasons]")
        lines.extend(f"- {item}" for item in result.reasons)
    return "\n".join(lines)


def format_json(result: BumpDecision) -> str:
    return json.dumps(
        {
            "recommended_bump": result.recommended_bump,
            "changed_files": result.changed_files,
            "reasons": result.reasons,
            "manual_review_required": result.manual_review_required,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recommend semantic version bump level from git diff.")
    parser.add_argument("--base-ref", default="HEAD~1", help="Git base ref (default: HEAD~1).")
    parser.add_argument("--head-ref", default="HEAD", help="Git head ref (default: HEAD).")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument(
        "--paths",
        nargs="*",
        help="Optional explicit file paths. If provided, git diff is not used.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.paths:
        files = sorted(dict.fromkeys(path for path in args.paths if path.strip()))
    else:
        files = _git_changed_files(args.base_ref, args.head_ref)
    decision = evaluate_paths(files)
    if args.format == "json":
        print(format_json(decision))
    else:
        print(format_human(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

