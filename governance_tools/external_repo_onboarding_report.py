#!/usr/bin/env python3
"""
Generate a combined onboarding report for an external governance repo.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.external_repo_readiness import assess_external_repo
from governance_tools.external_repo_smoke import run_external_repo_smoke


@dataclass
class ExternalRepoOnboardingReport:
    ok: bool
    repo_root: str
    contract_path: str | None
    generated_at: str
    readiness: dict
    smoke: dict


def build_onboarding_report(
    repo_root: Path,
    *,
    contract_file: str | Path | None = None,
    framework_root: str | Path | None = None,
    risk: str = "medium",
    oversight: str = "review-required",
    memory_mode: str = "candidate",
    task_text: str = "External governance onboarding smoke test",
) -> ExternalRepoOnboardingReport:
    readiness = assess_external_repo(
        repo_root,
        contract_path=contract_file,
        framework_root=Path(framework_root) if framework_root is not None else None,
    )
    smoke = run_external_repo_smoke(
        repo_root,
        contract_file=contract_file,
        risk=risk,
        oversight=oversight,
        memory_mode=memory_mode,
        task_text=task_text,
    )
    return ExternalRepoOnboardingReport(
        ok=readiness.ready and smoke.ok,
        repo_root=str(Path(repo_root).resolve()),
        contract_path=smoke.contract_path,
        generated_at=datetime.now(timezone.utc).isoformat(),
        readiness={
            "ready": readiness.ready,
            "checks": readiness.checks,
            "contract": readiness.contract,
            "framework_version": readiness.framework_version,
            "plan": readiness.plan,
            "hooks": readiness.hooks,
            "project_facts": readiness.project_facts,
            "agents_calibration": readiness.agents_calibration,
            "warnings": readiness.warnings,
            "errors": readiness.errors,
        },
        smoke={
            "ok": smoke.ok,
            "rules": smoke.rules,
            "plan_path": smoke.plan_path,
            "contract_path": smoke.contract_path,
            "pre_task_ok": smoke.pre_task_ok,
            "session_start_ok": smoke.session_start_ok,
            "post_task_ok": smoke.post_task_ok,
            "post_task_cases": smoke.post_task_cases,
            "token_summary": smoke.token_summary,
            "warnings": smoke.warnings,
            "errors": smoke.errors,
        },
    )


def _project_facts_summary(project_facts: dict | None) -> str | None:
    if not project_facts:
        return None
    return " | ".join(
        [
            f"status={project_facts.get('status')}",
            f"artifact_exists={project_facts.get('artifact_exists')}",
            f"artifact_drift={project_facts.get('artifact_drift')}",
            f"source={project_facts.get('source_filename')}",
        ]
    )


def format_human(report: ExternalRepoOnboardingReport) -> str:
    lines = [
        "External Repo Onboarding Report",
        "",
        f"ok                = {report.ok}",
        f"repo_root         = {report.repo_root}",
        f"contract_path     = {report.contract_path or '<missing>'}",
        f"generated_at      = {report.generated_at}",
        f"readiness_ready   = {report.readiness.get('ready')}",
        f"smoke_ok          = {report.smoke.get('ok')}",
        f"project_facts      = {_project_facts_summary(report.readiness.get('project_facts'))}",
        "token_summary      = "
        + ",".join(
            [
                f"prompt={((report.smoke.get('token_summary') or {}).get('prompt_tokens'))}",
                f"completion={((report.smoke.get('token_summary') or {}).get('completion_tokens'))}",
                f"total={((report.smoke.get('token_summary') or {}).get('total_tokens'))}",
                f"source={((report.smoke.get('token_summary') or {}).get('token_source_summary'))}",
                f"observability={((report.smoke.get('token_summary') or {}).get('token_observability_level'))}",
            ]
        ),
        "",
        "[readiness]",
    ]
    for key, value in sorted((report.readiness.get("checks") or {}).items()):
        lines.append(f"{key:<24} = {value}")

    project_facts = report.readiness.get("project_facts") or {}
    framework_version = report.readiness.get("framework_version") or {}
    agents_calibration = report.readiness.get("agents_calibration") or {}
    if framework_version:
        lines.extend(
            [
                "",
                "[framework_version]",
                f"state              = {framework_version.get('state')}",
                f"current_release    = {framework_version.get('current_release')}",
                f"adopted_release    = {framework_version.get('adopted_release')}",
                f"adopted_commit     = {framework_version.get('adopted_commit')}",
                f"framework_repo     = {framework_version.get('framework_repo')}",
                f"canonical_repo     = {framework_version.get('canonical_framework_repo')}",
            ]
        )
    if project_facts:
        lines.extend(
            [
                "",
                "[project_facts]",
                f"status             = {project_facts.get('status')}",
                f"source_file        = {project_facts.get('source_file')}",
                f"source_filename    = {project_facts.get('source_filename')}",
                f"sync_direction     = {project_facts.get('sync_direction')}",
                f"artifact_path      = {project_facts.get('artifact_path')}",
                f"artifact_exists    = {project_facts.get('artifact_exists')}",
                f"artifact_drift     = {project_facts.get('artifact_drift')}",
                f"reason             = {project_facts.get('reason')}",
                f"remediation_hint   = {project_facts.get('remediation_hint')}",
            ]
        )
    if agents_calibration:
        lines.extend(
            [
                "",
                "[agents_calibration]",
                f"status             = {agents_calibration.get('status')}",
                f"reason             = {agents_calibration.get('reason')}",
                f"path               = {agents_calibration.get('path')}",
                f"reviewer_signal    = {agents_calibration.get('reviewer_signal')}",
            ]
        )

    lines.extend(
        [
            "",
            "[smoke]",
            f"rules             = {','.join(report.smoke.get('rules') or [])}",
            f"pre_task_ok       = {report.smoke.get('pre_task_ok')}",
            f"session_start_ok  = {report.smoke.get('session_start_ok')}",
            f"post_task_ok      = {report.smoke.get('post_task_ok')}",
        ]
    )
    post_task_cases = report.smoke.get("post_task_cases") or []
    if post_task_cases:
        lines.append("[post_task_cases]")
        for item in post_task_cases:
            lines.append(
                " | ".join(
                    [
                        Path(item.get("checks_file", "")).name,
                        f"ok={item.get('ok')}",
                        f"domain_validators={item.get('domain_validator_count')}",
                    ]
                )
            )

    all_errors = [
        *(f"readiness: {item}" for item in (report.readiness.get("errors") or [])),
        *(f"smoke: {item}" for item in (report.smoke.get("errors") or [])),
    ]
    if all_errors:
        lines.append("")
        lines.append(f"errors: {len(all_errors)}")
        for item in all_errors:
            lines.append(f"- {item}")

    all_warnings = [
        *(f"readiness: {item}" for item in (report.readiness.get("warnings") or [])),
        *(f"smoke: {item}" for item in (report.smoke.get("warnings") or [])),
    ]
    if all_warnings:
        lines.append("")
        lines.append(f"warnings: {len(all_warnings)}")
        for item in all_warnings:
            lines.append(f"- {item}")

    return "\n".join(lines)


def format_json(report: ExternalRepoOnboardingReport) -> str:
    return json.dumps(
        {
            "ok": report.ok,
            "repo_root": report.repo_root,
            "contract_path": report.contract_path,
            "generated_at": report.generated_at,
            "readiness": report.readiness,
            "smoke": report.smoke,
        },
        ensure_ascii=False,
        indent=2,
    )


def _history_stem(report: ExternalRepoOnboardingReport) -> str:
    dt = datetime.fromisoformat(report.generated_at.replace("Z", "+00:00"))
    return dt.strftime("%Y%m%d_%H%M%S")


def _index_lines(history_dir: Path) -> list[str]:
    json_files = sorted(history_dir.glob("*.json"))
    lines = ["[external_repo_onboarding_index]", f"history_dir={history_dir}", f"reports={len(json_files)}"]
    if json_files:
        lines.append("[reports]")
        for path in reversed(json_files):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                lines.append(f"{path.name} | unreadable")
                continue
            lines.append(
                " | ".join(
                    [
                        path.name,
                        f"ok={payload.get('ok')}",
                        f"repo_root={payload.get('repo_root')}",
                        f"contract_path={payload.get('contract_path')}",
                        f"generated_at={payload.get('generated_at')}",
                    ]
                )
            )
    return lines


def write_report_bundle(report: ExternalRepoOnboardingReport, bundle_dir: Path) -> dict[str, str]:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    history_dir = bundle_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    stem = _history_stem(report)
    latest_json = bundle_dir / "latest.json"
    latest_txt = bundle_dir / "latest.txt"
    history_json = history_dir / f"{stem}.json"
    history_txt = history_dir / f"{stem}.txt"
    index_txt = bundle_dir / "INDEX.txt"

    json_text = format_json(report) + "\n"
    human_text = format_human(report) + "\n"

    latest_json.write_text(json_text, encoding="utf-8")
    latest_txt.write_text(human_text, encoding="utf-8")
    history_json.write_text(json_text, encoding="utf-8")
    history_txt.write_text(human_text, encoding="utf-8")
    index_txt.write_text("\n".join(_index_lines(history_dir)) + "\n", encoding="utf-8")

    return {
        "latest_json": str(latest_json),
        "latest_txt": str(latest_txt),
        "history_json": str(history_json),
        "history_txt": str(history_txt),
        "index_txt": str(index_txt),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a combined onboarding report for an external governance repo.")
    parser.add_argument("--repo", default=".", help="Target repo root.")
    parser.add_argument("--contract", help="Optional explicit contract.yaml path.")
    parser.add_argument("--framework-root", help="Optional explicit framework root for readiness validation.")
    parser.add_argument("--risk", default="medium")
    parser.add_argument("--oversight", default="review-required")
    parser.add_argument("--memory-mode", default="candidate")
    parser.add_argument("--task-text", default="External governance onboarding smoke test")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--output", help="Optional output file path.")
    parser.add_argument("--write-bundle", help="Optional onboarding artifact directory; writes latest/history/index artifacts.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = build_onboarding_report(
        Path(args.repo),
        contract_file=args.contract,
        framework_root=args.framework_root,
        risk=args.risk,
        oversight=args.oversight,
        memory_mode=args.memory_mode,
        task_text=args.task_text,
    )
    rendered = format_json(report) if args.format == "json" else format_human(report)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    if args.write_bundle:
        paths = write_report_bundle(report, Path(args.write_bundle))
        if args.format == "human":
            print("")
            print("[report_bundle]")
            for key, value in paths.items():
                print(f"{key}={value}")
    print(rendered)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
