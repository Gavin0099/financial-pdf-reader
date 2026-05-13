#!/usr/bin/env python3
"""
Build a cross-repo index over external onboarding report artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.human_summary import build_summary_line


def _load_latest_report(repo_root: Path) -> dict | None:
    latest_path = repo_root / "memory" / "governance_onboarding" / "latest.json"
    if not latest_path.is_file():
        return None
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    payload["_latest_path"] = str(latest_path)
    payload["_repo_root"] = str(repo_root.resolve())
    return payload


def _entry_priority(entry: dict) -> tuple[int, int, str]:
    ok_rank = 0 if entry.get("ok") is False else 1
    smoke_ok = (entry.get("smoke") or {}).get("ok")
    smoke_rank = 0 if smoke_ok is False else 1
    post_task_ok = (entry.get("smoke") or {}).get("post_task_ok")
    post_task_rank = 0 if post_task_ok is False else 1
    repo_root = entry.get("_repo_root", "")
    return (ok_rank, smoke_rank, post_task_rank, repo_root)


def _suggested_command(entry: dict) -> str:
    repo_root = entry["repo_root"]
    reasons = []
    if entry.get("readiness_ready") is False:
        reasons.append("readiness")
    if entry.get("smoke_ok") is False:
        reasons.append("smoke")
    if entry.get("post_task_ok") is False:
        reasons.append("post-task")
    if not reasons:
        reasons.append("report")

    if "readiness" in reasons and "smoke" in reasons:
        return f"python governance_tools/external_repo_onboarding_report.py --repo {repo_root} --format human"
    if "readiness" in reasons:
        return f"python governance_tools/external_repo_readiness.py --repo {repo_root} --format human"
    if "smoke" in reasons:
        return f"python governance_tools/external_repo_smoke.py --repo {repo_root} --format human"
    if "post-task" in reasons:
        return f"python governance_tools/external_repo_smoke.py --repo {repo_root} --format human"
    return f"python governance_tools/external_repo_onboarding_index.py --repo {repo_root} --format human"


def build_external_repo_onboarding_index(repo_roots: list[Path]) -> dict:
    entries = []
    missing = []

    for repo_root in repo_roots:
        repo_root = repo_root.resolve()
        payload = _load_latest_report(repo_root)
        if payload is None:
            missing.append(str(repo_root))
            continue
        readiness = payload.get("readiness") or {}
        smoke = payload.get("smoke") or {}
        project_facts = (readiness.get("project_facts") or {})
        entries.append(
            {
                "repo_root": str(repo_root),
                "latest_path": payload.get("_latest_path"),
                "ok": payload.get("ok"),
                "generated_at": payload.get("generated_at"),
                "contract_path": payload.get("contract_path"),
                "readiness_ready": readiness.get("ready"),
                "smoke_ok": smoke.get("ok"),
                "post_task_ok": smoke.get("post_task_ok"),
                "rules": smoke.get("rules") or [],
                "project_facts_status": project_facts.get("status"),
                "project_facts_summary": " | ".join(
                    [
                        f"status={project_facts.get('status')}",
                        f"artifact_exists={project_facts.get('artifact_exists')}",
                        f"artifact_drift={project_facts.get('artifact_drift')}",
                        f"source={project_facts.get('source_filename')}",
                    ]
                ) if project_facts else None,
                "readiness_errors": len(readiness.get("errors") or []),
                "smoke_errors": len(smoke.get("errors") or []),
            }
        )

    ordered_entries = sorted(entries, key=_entry_priority)
    top_issues = []
    for entry in ordered_entries[:3]:
        if entry.get("ok") is True:
            continue
        reasons = []
        if entry.get("readiness_ready") is False:
            reasons.append("readiness")
        if entry.get("smoke_ok") is False:
            reasons.append("smoke")
        if entry.get("post_task_ok") is False:
            reasons.append("post-task")
        if not reasons:
            reasons.append("report")
        top_issues.append(
            {
                "repo_root": entry["repo_root"],
                "reasons": reasons,
                "contract_path": entry.get("contract_path"),
                "project_facts_summary": entry.get("project_facts_summary"),
                "suggested_command": _suggested_command(entry),
            }
        )

    return {
        "ok": len(missing) == 0 and all(entry.get("ok") for entry in ordered_entries),
        "repo_count": len(repo_roots),
        "indexed_count": len(ordered_entries),
        "missing_reports": missing,
        "entries": ordered_entries,
        "top_issues": top_issues,
    }


def format_human(result: dict) -> str:
    lines = [
        "[external_repo_onboarding_index]",
        build_summary_line(
            f"ok={result['ok']}",
            f"repos={result['repo_count']}",
            f"indexed={result['indexed_count']}",
            f"missing={len(result.get('missing_reports') or [])}",
            f"top_issues={len(result.get('top_issues') or [])}",
        ),
        f"ok={result['ok']}",
        f"repo_count={result['repo_count']}",
        f"indexed_count={result['indexed_count']}",
    ]

    missing = result.get("missing_reports") or []
    if missing:
        lines.append("[missing_reports]")
        for item in missing:
            lines.append(item)

    entries = result.get("entries") or []
    if entries:
        lines.append("[repos]")
        for entry in entries:
            lines.append(
                " | ".join(
                    [
                        entry["repo_root"],
                        f"ok={entry['ok']}",
                        f"readiness={entry['readiness_ready']}",
                        f"smoke={entry['smoke_ok']}",
                        f"post_task={entry['post_task_ok']}",
                        f"rules={','.join(entry['rules'])}",
                        f"project_facts={entry.get('project_facts_summary')}",
                        f"generated_at={entry['generated_at']}",
                    ]
                )
            )

    top_issues = result.get("top_issues") or []
    if top_issues:
        lines.append("[top_issues]")
        for item in top_issues:
            lines.append(
                " | ".join(
                    [
                        item["repo_root"],
                        f"reasons={','.join(item['reasons'])}",
                        f"contract_path={item.get('contract_path')}",
                        f"suggested_command={item.get('suggested_command')}",
                    ]
                )
            )

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a framework-level index for external onboarding reports.")
    parser.add_argument("--repo", action="append", default=[], help="External repo root to include. Can be repeated.")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--output")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_roots = [Path(item) for item in args.repo]
    result = build_external_repo_onboarding_index(repo_roots)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else format_human(result)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
