#!/usr/bin/env python3
"""
Minimal runtime smoke for external governance repos.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.contract_resolver import resolve_contract
from governance_tools.domain_contract_loader import load_domain_contract
from governance_tools.human_summary import build_summary_line
from governance_tools.rule_pack_loader import available_rule_packs, parse_rule_list
from runtime_hooks.core.post_task_check import run_post_task_check
from runtime_hooks.core.pre_task_check import run_pre_task_check
from runtime_hooks.core.session_start import build_session_start_context


@dataclass
class ExternalRepoSmokeResult:
    ok: bool
    repo_root: str
    plan_path: str
    contract_path: str | None
    rules: list[str] = field(default_factory=list)
    session_start_ok: bool = False
    pre_task_ok: bool = False
    post_task_ok: bool | None = None
    post_task_cases: list[dict] = field(default_factory=list)
    token_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _default_token_summary() -> dict[str, Any]:
    return {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "token_source_summary": "unknown",
        "token_observability_level": "none",
        "provenance_warning": "not_provided_by_smoke",
        "decision_usage_allowed": False,
        "analysis_safe_for_decision": False,
    }


def _extract_token_summary_from_checks(checks: dict | None) -> dict[str, Any]:
    token_summary = _default_token_summary()
    if not isinstance(checks, dict):
        return token_summary
    token_count = checks.get("token_count") if isinstance(checks.get("token_count"), dict) else {}
    token_summary["prompt_tokens"] = token_count.get("prompt_tokens")
    token_summary["completion_tokens"] = token_count.get("completion_tokens")
    token_summary["total_tokens"] = token_count.get("total_tokens")
    token_summary["token_source_summary"] = checks.get("token_source_summary", "unknown")
    token_summary["token_observability_level"] = checks.get("token_observability_level", "none")
    token_summary["provenance_warning"] = checks.get("provenance_warning", "provenance_unverified")
    token_summary["decision_usage_allowed"] = False
    token_summary["analysis_safe_for_decision"] = False
    return token_summary


def infer_smoke_rules(contract: dict | None) -> list[str]:
    if not contract:
        return ["common"]

    rule_roots = [Path(path) for path in contract.get("rule_roots", [])]
    external_packs = sorted(available_rule_packs(rule_roots))
    return parse_rule_list(["common", *external_packs])


_COMPLIANT_FIXTURE_MARKERS = ("compliant", "known", "clean", "safe")


def discover_post_task_smoke_fixtures(repo_root: Path) -> tuple[Path | None, list[Path], list[str]]:
    fixtures_root = repo_root / "fixtures"
    warnings: list[str] = []
    response_file = fixtures_root / "post_task_response.txt"
    checks_files = sorted(fixtures_root.glob("*.checks.json"))

    if not response_file.exists():
        if checks_files:
            warnings.append("Post-task checks fixtures exist, but fixtures/post_task_response.txt is missing.")
        return None, [], warnings

    compliant = [
        path
        for path in checks_files
        if any(marker in path.name.lower() for marker in _COMPLIANT_FIXTURE_MARKERS)
    ]
    if not compliant and checks_files:
        warnings.append("No compliant post-task checks fixture was found; skipping post-task replay smoke.")
    return response_file, compliant, warnings


def run_external_repo_smoke(
    repo_root: Path,
    *,
    contract_file: str | Path | None = None,
    risk: str = "medium",
    oversight: str = "review-required",
    memory_mode: str = "candidate",
    task_text: str = "External governance onboarding smoke test",
) -> ExternalRepoSmokeResult:
    repo_root = repo_root.resolve()
    plan_path = repo_root / "PLAN.md"
    resolution = resolve_contract(contract_file, project_root=repo_root)
    contract_path = resolution.path
    contract = load_domain_contract(contract_path) if contract_path else None
    rules = infer_smoke_rules(contract)

    warnings = list(resolution.warnings)
    errors: list[str] = []
    if resolution.error:
        errors.append(resolution.error)
    if not plan_path.exists():
        errors.append(f"PLAN.md not found: {plan_path}")
    if contract:
        rule_roots = [Path(path) for path in contract.get("rule_roots", [])]
        missing_rule_roots = [path for path in rule_roots if not path.exists()]
        for path in missing_rule_roots:
            errors.append(f"Contract rule root does not exist: {path}")
        if rule_roots and not missing_rule_roots and rules == ["common"]:
            errors.append("Contract rule roots resolved, but no external rule packs were discovered.")

    session_start_ok = False
    pre_task_ok = False
    post_task_ok: bool | None = None
    post_task_cases: list[dict] = []
    token_summary = _default_token_summary()
    if not errors:
        pre_task = run_pre_task_check(
            project_root=repo_root,
            rules=",".join(rules),
            risk=risk,
            oversight=oversight,
            memory_mode=memory_mode,
            task_text=task_text,
            contract_file=contract_path,
        )
        pre_task_ok = pre_task["ok"]
        warnings.extend(pre_task.get("warnings", []))
        errors.extend(pre_task.get("errors", []))

        session_start = build_session_start_context(
            project_root=repo_root,
            plan_path=plan_path,
            rules=",".join(rules),
            risk=risk,
            oversight=oversight,
            memory_mode=memory_mode,
            task_text=task_text,
            contract_file=contract_path,
        )
        session_start_ok = session_start["ok"]
        warnings.extend(session_start.get("pre_task_check", {}).get("warnings", []))
        errors.extend(session_start.get("pre_task_check", {}).get("errors", []))

        response_file, checks_files, fixture_warnings = discover_post_task_smoke_fixtures(repo_root)
        warnings.extend(fixture_warnings)
        if response_file and checks_files:
            response_text = response_file.read_text(encoding="utf-8")
            post_task_ok = False
            for checks_file in checks_files:
                checks = json.loads(checks_file.read_text(encoding="utf-8"))
                result = run_post_task_check(
                    response_text=response_text,
                    risk=risk,
                    oversight=oversight,
                    memory_mode=memory_mode,
                    create_snapshot=False,
                    checks=checks,
                    contract_file=contract_path,
                    project_root=repo_root,
                    evidence_paths=[response_file.resolve(), checks_file.resolve()],
                )
                case = {
                    "checks_file": str(checks_file),
                    "ok": result["ok"],
                    "domain_validator_count": len(result.get("domain_validator_results") or []),
                    "token_summary": _extract_token_summary_from_checks(result.get("checks")),
                    "warnings": result.get("warnings") or [],
                    "errors": result.get("errors") or [],
                }
                post_task_cases.append(case)
                if case["ok"]:
                    post_task_ok = True
                    token_summary = case["token_summary"]
                    break
            if post_task_ok is False:
                errors.append("No compliant post-task smoke fixture passed.")

    # keep ordering stable while deduplicating
    deduped_warnings = list(dict.fromkeys(warnings))
    deduped_errors = list(dict.fromkeys(errors))
    return ExternalRepoSmokeResult(
        ok=(len(deduped_errors) == 0 and session_start_ok and pre_task_ok and post_task_ok is not False),
        repo_root=str(repo_root),
        plan_path=str(plan_path),
        contract_path=str(contract_path) if contract_path else None,
        rules=rules,
        session_start_ok=session_start_ok,
        pre_task_ok=pre_task_ok,
        post_task_ok=post_task_ok,
        post_task_cases=post_task_cases,
        token_summary=token_summary,
        warnings=deduped_warnings,
        errors=deduped_errors,
    )


def format_human(result: ExternalRepoSmokeResult) -> str:
    lines = [
        "[external_repo_smoke]",
        build_summary_line(
            f"ok={result.ok}",
            f"rules={','.join(result.rules)}",
            f"pre_task_ok={result.pre_task_ok}",
            f"session_start_ok={result.session_start_ok}",
            f"post_task_ok={result.post_task_ok}",
        ),
        "token_summary="
        + ",".join(
            [
                f"prompt={result.token_summary.get('prompt_tokens')}",
                f"completion={result.token_summary.get('completion_tokens')}",
                f"total={result.token_summary.get('total_tokens')}",
                f"source={result.token_summary.get('token_source_summary')}",
                f"observability={result.token_summary.get('token_observability_level')}",
            ]
        ),
        f"repo_root={result.repo_root}",
        f"plan_path={result.plan_path}",
        f"contract_path={result.contract_path or '<missing>'}",
    ]
    if result.post_task_cases:
        lines.append("[post_task_cases]")
        for item in result.post_task_cases:
            lines.append(
                " | ".join(
                    [
                        Path(item["checks_file"]).name,
                        f"ok={item['ok']}",
                        f"domain_validators={item['domain_validator_count']}",
                    ]
                )
            )
            for warning in item.get("warnings") or []:
                lines.append(f"  warning: {warning}")
            for error in item.get("errors") or []:
                lines.append(f"  error: {error}")
    if result.errors:
        lines.append(f"errors={len(result.errors)}")
        for item in result.errors:
            lines.append(f"- {item}")
    if result.warnings:
        lines.append(f"warnings={len(result.warnings)}")
        for item in result.warnings:
            lines.append(f"- {item}")
    return "\n".join(lines)


def format_json(result: ExternalRepoSmokeResult) -> str:
    return json.dumps(
        {
            "ok": result.ok,
            "repo_root": result.repo_root,
            "plan_path": result.plan_path,
            "contract_path": result.contract_path,
            "rules": result.rules,
            "pre_task_ok": result.pre_task_ok,
            "session_start_ok": result.session_start_ok,
            "post_task_ok": result.post_task_ok,
            "post_task_cases": result.post_task_cases,
            "token_summary": result.token_summary,
            "warnings": result.warnings,
            "errors": result.errors,
        },
        ensure_ascii=False,
        indent=2,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a minimal runtime smoke for an external governance repo.")
    parser.add_argument("--repo", default=".", help="Target repo root.")
    parser.add_argument("--contract", help="Optional explicit contract.yaml path.")
    parser.add_argument("--risk", default="medium")
    parser.add_argument("--oversight", default="review-required")
    parser.add_argument("--memory-mode", default="candidate")
    parser.add_argument("--task-text", default="External governance onboarding smoke test")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_external_repo_smoke(
        Path(args.repo),
        contract_file=args.contract,
        risk=args.risk,
        oversight=args.oversight,
        memory_mode=args.memory_mode,
        task_text=args.task_text,
    )
    if args.format == "json":
        print(format_json(result))
    else:
        print(format_human(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
