#!/usr/bin/env python3
"""
Run first-import governance validation checks and write a markdown report skeleton.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CommandResult:
    name: str
    command: list[str]
    ok: bool
    returncode: int
    stdout: str
    stderr: str


def _run_command(command: list[str], cwd: Path, name: str) -> CommandResult:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return CommandResult(
        name=name,
        command=command,
        ok=(proc.returncode == 0),
        returncode=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
    )


def _extract_json_field(payload_text: str, path: list[str], default: object = None) -> object:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return default
    cur: object = payload
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def _report_text(repo_root: Path, results: list[CommandResult]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    result_map = {item.name: item for item in results}

    readiness_ready = _extract_json_field(result_map["readiness"].stdout, ["ready"], default="unknown")
    version_compatible = _extract_json_field(result_map["version_check"].stdout, ["compatible"], default="unknown")
    smoke_ok = _extract_json_field(result_map["quickstart_smoke"].stdout, ["ok"], default="unknown")
    session_start_ok = _extract_json_field(result_map["session_start"].stdout, ["ok"], default="unknown")
    pre_task_ok = _extract_json_field(result_map["pre_task_check"].stdout, ["ok"], default="unknown")

    lines = [
        "# AI Governance First Import Validation Report",
        "",
        f"- generated_at_utc: {now}",
        f"- repo_root: {repo_root}",
        "",
        "## Summary",
        "",
        f"- quickstart_smoke.ok: {smoke_ok}",
        f"- session_start.ok: {session_start_ok}",
        f"- pre_task_check.ok: {pre_task_ok}",
        f"- external_repo_readiness.ready: {readiness_ready}",
        f"- governance_version_check.compatible: {version_compatible}",
        "",
        "## Command Results",
        "",
    ]

    for item in results:
        lines.extend(
            [
                f"### {item.name}",
                "",
                f"- ok: {str(item.ok).lower()}",
                f"- return_code: {item.returncode}",
                f"- command: `{' '.join(item.command)}`",
                "",
                "```text",
                item.stdout or "<empty stdout>",
                "```",
            ]
        )
        if item.stderr:
            lines.extend(
                [
                    "",
                    "```text",
                    item.stderr,
                    "```",
                ]
            )
        lines.append("")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run first import validation checks and write report.")
    parser.add_argument("--repo-root", default=".", help="Target consuming repo root.")
    parser.add_argument(
        "--output",
        help="Output markdown path. Default: AI_Governance_First_Import_Validation_<YYYYMMDD>.md in repo root.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(args.repo_root).resolve()
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    output_path = Path(args.output).resolve() if args.output else (repo_root / f"AI_Governance_First_Import_Validation_{date_tag}.md")

    checks = [
        ("quickstart_smoke", ["python", "quickstart_smoke.py", "--format", "json"]),
        (
            "session_start",
            [
                "python",
                "runtime_hooks/core/session_start.py",
                "--project-root",
                ".",
                "--plan-path",
                "PLAN.md",
                "--task",
                "governance import validation",
                "--rules",
                "common",
                "--risk",
                "low",
                "--oversight",
                "review-required",
                "--memory-mode",
                "candidate",
                "--format",
                "json",
            ],
        ),
        (
            "pre_task_check",
            [
                "python",
                "runtime_hooks/core/pre_task_check.py",
                "--project-root",
                ".",
                "--task-text",
                "governance import validation",
                "--rules",
                "common",
                "--risk",
                "low",
                "--oversight",
                "review-required",
                "--memory-mode",
                "candidate",
                "--format",
                "json",
            ],
        ),
        ("readiness", ["python", "-m", "governance_tools.external_repo_readiness", "--format", "json"]),
        ("version_check", ["python", "-m", "governance_tools.governance_version_check", "--project-root", ".", "--format", "json"]),
    ]

    results = [_run_command(command=cmd, cwd=repo_root, name=name) for name, cmd in checks]
    report = _report_text(repo_root, results)
    output_path.write_text(report, encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path), "all_checks_ok": all(item.ok for item in results)}, ensure_ascii=False, indent=2))
    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

