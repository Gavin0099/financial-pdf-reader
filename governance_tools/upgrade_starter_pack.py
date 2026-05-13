#!/usr/bin/env python3
"""
upgrade_starter_pack: opt-in scaffold refresh for repos using examples/starter-pack.

Purpose:
    Provide a bounded upgrade path for repos that started from the starter-pack
    scaffold but have not yet adopted the full framework.

What it does:
    1. Seeds missing starter-pack files into the target repo
    2. Optionally refreshes managed adapter/prompt files
    3. Never overwrites PLAN.md automatically
    4. Can copy memory_janitor.py from governance_tools/

What it does NOT do:
    - Does not adopt the full framework baseline
    - Does not create governance/ or .governance/
    - Does not certify repo quality
    - Does not modify repo-specific plan content
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass(frozen=True)
class ScaffoldFile:
    source: str
    target: str
    managed_refresh: bool = True
    overwrite_default: bool = False


STARTER_PACK_FILES = [
    ScaffoldFile("examples/starter-pack/SYSTEM_PROMPT.md", "SYSTEM_PROMPT.md", managed_refresh=True),
    ScaffoldFile("examples/starter-pack/CLAUDE.md", "CLAUDE.md", managed_refresh=True),
    ScaffoldFile("examples/starter-pack/GEMINI.md", "GEMINI.md", managed_refresh=True),
    ScaffoldFile("examples/starter-pack/.github/copilot-instructions.md", ".github/copilot-instructions.md", managed_refresh=True),
    ScaffoldFile("examples/starter-pack/memory/01_active_task.md", "memory/01_active_task.md", managed_refresh=True),
    ScaffoldFile("governance_tools/memory_janitor.py", "memory_janitor.py", managed_refresh=True),
    ScaffoldFile("examples/starter-pack/PLAN.md", "PLAN.md", managed_refresh=False, overwrite_default=False),
]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def upgrade_repo(
    repo: Path,
    *,
    framework_root: Path,
    dry_run: bool = False,
    refresh_managed: bool = False,
) -> dict:
    repo = repo.resolve()
    framework_root = framework_root.resolve()

    if not repo.exists():
        return {
            "repo": str(repo),
            "ok": False,
            "status": "error",
            "message": f"repo path does not exist: {repo}",
            "files": [],
        }

    file_results: list[dict] = []
    actions_taken = 0

    for entry in STARTER_PACK_FILES:
        source = framework_root / entry.source
        target = repo / entry.target

        if not source.exists():
            file_results.append(
                {
                    "target": entry.target,
                    "status": "missing_source",
                    "message": f"framework source missing: {entry.source}",
                }
            )
            continue

        if not target.exists():
            if not dry_run:
                _copy_file(source, target)
            actions_taken += 1
            file_results.append(
                {
                    "target": entry.target,
                    "status": "seeded",
                    "message": f"seeded missing file from {entry.source}",
                }
            )
            continue

        if entry.target == "PLAN.md":
            file_results.append(
                {
                    "target": entry.target,
                    "status": "skipped_existing_plan",
                    "message": "existing PLAN.md is repo-specific and was not overwritten",
                }
            )
            continue

        if refresh_managed and entry.managed_refresh:
            source_text = _read_text(source)
            target_text = _read_text(target)
            if source_text == target_text:
                file_results.append(
                    {
                        "target": entry.target,
                        "status": "already_current",
                        "message": "managed file already matches framework source",
                    }
                )
            else:
                if not dry_run:
                    _copy_file(source, target)
                actions_taken += 1
                file_results.append(
                    {
                        "target": entry.target,
                        "status": "refreshed",
                        "message": f"refreshed managed file from {entry.source}",
                    }
                )
        else:
            file_results.append(
                {
                    "target": entry.target,
                    "status": "kept_existing",
                    "message": "existing file kept; use --refresh-managed to replace managed starter-pack surfaces",
                }
            )

    status = "dry_run" if dry_run else "patched"
    return {
        "repo": str(repo),
        "ok": True,
        "status": status,
        "message": f"{actions_taken} file action(s) planned" if dry_run else f"{actions_taken} file action(s) applied",
        "refresh_managed": refresh_managed,
        "files": file_results,
    }


def format_human_result(result: dict) -> str:
    lines = [
        "[upgrade_starter_pack]",
        f"repo={result['repo']}",
        f"ok={result['ok']}",
        f"status={result['status']}",
        f"refresh_managed={result.get('refresh_managed', False)}",
        f"message={result['message']}",
    ]
    for item in result.get("files", []):
        lines.append(f"file[{item['target']}]={item['status']} | {item['message']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed or refresh starter-pack scaffold files in a target repo.")
    parser.add_argument("--repo", nargs="+", required=True, metavar="PATH", help="One or more target repos")
    parser.add_argument("--framework-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dry-run", action="store_true", help="Show intended changes without writing files")
    parser.add_argument(
        "--refresh-managed",
        action="store_true",
        help="Refresh managed starter-pack surfaces such as SYSTEM_PROMPT/adapters/memory_janitor",
    )
    parser.add_argument("--format", choices=("human", "json"), default="human")
    args = parser.parse_args()

    import json

    results = [
        upgrade_repo(
            Path(repo),
            framework_root=Path(args.framework_root),
            dry_run=args.dry_run,
            refresh_managed=args.refresh_managed,
        )
        for repo in args.repo
    ]

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(format_human_result(item) for item in results))

    if any(not item["ok"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
