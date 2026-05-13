#!/usr/bin/env python3
"""
Aggregate trust-signal and release-surface summaries into one reviewer handoff view.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.human_summary import build_summary_line
from governance_tools.review_artifact_linter import lint_text
from governance_tools.release_surface_overview import assess_release_surface
from governance_tools.trust_signal_overview import assess_trust_signal_overview


def _external_project_facts_summaries(result: dict[str, Any]) -> list[str]:
    auditor = (result.get("trust_signal") or {}).get("auditor") or {}
    external_onboarding = auditor.get("external_onboarding") or {}
    summaries: list[str] = []
    for item in external_onboarding.get("top_issues") or []:
        summary = item.get("project_facts_summary")
        if summary:
            summaries.append(f"{item.get('repo_root')}: {summary}")
    return summaries


def _commands(
    release_version: str,
    contract_file: Path | None = None,
    *,
    authority_require_register: bool | None = None,
    authority_policy_file: Path | None = None,
) -> list[dict[str, str]]:
    contract_arg = f" --contract {contract_file}" if contract_file else ""
    authority_arg = ""
    if authority_require_register is True:
        authority_arg = " --authority-require-register"
    elif authority_require_register is False:
        authority_arg = " --no-authority-require-register"
    policy_file_arg = (
        f" --authority-policy-file {authority_policy_file}"
        if authority_policy_file
        else ""
    )
    return [
        {
            "name": "trust_signal_overview",
            "command": "python governance_tools/trust_signal_overview.py --project-root . --plan PLAN.md "
            f"--release-version {release_version}{contract_arg} --format human",
        },
        {
            "name": "release_surface_overview",
            "command": (
                "python governance_tools/release_surface_overview.py "
                f"--version {release_version}{authority_arg}{policy_file_arg} --format human"
            ),
        },
        {
            "name": "phase_gates",
            "command": "bash scripts/verify_phase_gates.sh",
        },
    ]


def _build_lint_surface(
    *,
    release_version: str,
    contract_path: str | None,
    trust_ok: bool,
    release_ok: bool,
    commands: list[dict[str, str]],
) -> str:
    lines = [
        "# Reviewer Handoff Summary",
        "## Handoff Status",
        f"release_version={release_version}",
        f"contract_path={contract_path}",
        f"trust_ok={trust_ok}",
        f"release_ok={release_ok}",
        "## Suggested Commands",
    ]
    for item in commands:
        lines.append(f"- {item['name']}: {item['command']}")
    return "\n".join(lines)


def _severity_rank(level: str) -> int:
    if level == "high":
        return 3
    if level == "medium":
        return 2
    if level == "low":
        return 1
    return 0


def _highest_severity(violations: list[dict[str, Any]]) -> str:
    if not violations:
        return "none"
    return max((str(v.get("severity", "low")) for v in violations), key=_severity_rank)


_ALLOW_REASON_CODES: tuple[str, ...] = (
    "manual_audit_required",
    "known_policy_violation_for_review",
    "pipeline_debugging_only",
    "temporary_reader_visibility",
    "other_requires_note",
)

_NON_OVERRIDABLE_CLAIM_TYPES: frozenset[str] = frozenset(
    {
        "readiness_claim",
        "promotion_claim",
        "stability_claim",
        "confidence_laundering",
    }
)


def _resolve_override_decision_reason(
    *,
    lint_clean: bool,
    allow_non_clean: bool,
    allow_request_valid: bool,
    override_blocked: bool,
    override_active: bool,
) -> str | None:
    if lint_clean:
        return "clean_no_override_needed"
    if not allow_non_clean:
        return None
    if not allow_request_valid:
        return "invalid_override_request"
    if override_blocked:
        return "blocked_non_overridable_claim"
    if override_active:
        return "allowed_for_manual_review"
    return "invalid_override_request"


def _evaluate_override_policy(
    *,
    lint_result: dict[str, Any],
    fail_on_non_clean: bool,
    allow_non_clean: bool,
    lint_override_source: str | None,
    override_reason_code: str | None,
    override_reason_note: str | None,
) -> dict[str, Any]:
    lint_clean = lint_result["status"] == "clean"
    violations = lint_result.get("violations") or []
    non_overridable_matches = [
        v
        for v in violations
        if str(v.get("claim_type")) in _NON_OVERRIDABLE_CLAIM_TYPES
        and str(v.get("severity")) == "high"
    ]

    reason_code_valid = bool(
        override_reason_code is not None and override_reason_code in _ALLOW_REASON_CODES
    )
    reason_note_required = override_reason_code == "other_requires_note"
    reason_note_present = bool((override_reason_note or "").strip())

    allow_request_valid = True
    allow_request_error = None
    if allow_non_clean:
        if not reason_code_valid:
            allow_request_valid = False
            allow_request_error = "allow_non_clean_reason_code_invalid_or_missing"
        elif reason_note_required and not reason_note_present:
            allow_request_valid = False
            allow_request_error = "allow_non_clean_reason_note_required"

    override_blocked = bool(non_overridable_matches)
    override_active = bool(
        allow_non_clean
        and not lint_clean
        and allow_request_valid
        and not override_blocked
    )
    override_decision_reason = _resolve_override_decision_reason(
        lint_clean=lint_clean,
        allow_non_clean=allow_non_clean,
        allow_request_valid=allow_request_valid,
        override_blocked=override_blocked,
        override_active=override_active,
    )

    return {
        "fail_on_non_clean": bool(fail_on_non_clean),
        "allow_non_clean": bool(allow_non_clean),
        "allow_request_valid": allow_request_valid,
        "allow_request_error": allow_request_error,
        "override_active": override_active,
        "override_source": lint_override_source if override_active else None,
        "override_effect": "flow_allowed_non_clean" if override_active else "none",
        "override_reason_code": override_reason_code if allow_non_clean else None,
        "override_reason_note": override_reason_note if allow_non_clean else None,
        "override_decision_reason": override_decision_reason,
        "override_blocked_by_non_overridable": override_blocked,
        "non_overridable_claim_types": sorted(
            {str(v.get("claim_type")) for v in non_overridable_matches}
        ),
        "clean_identity_preserved": True,
    }


def assess_reviewer_handoff(
    *,
    project_root: Path,
    plan_path: Path,
    release_version: str,
    contract_file: Path | None = None,
    external_contract_repos: list[Path] | None = None,
    strict_runtime: bool = False,
    authority_require_register: bool | None = None,
    authority_policy_file: Path | None = None,
    release_bundle_manifest: Path | None = None,
    release_publication_manifest: Path | None = None,
    fail_on_non_clean: bool = True,
    allow_non_clean: bool = False,
    lint_override_source: str | None = None,
    override_reason_code: str | None = None,
    override_reason_note: str | None = None,
) -> dict[str, Any]:
    trust = assess_trust_signal_overview(
        project_root=project_root,
        plan_path=plan_path,
        release_version=release_version,
        contract_file=contract_file,
        external_contract_repos=external_contract_repos,
        strict_runtime=strict_runtime,
    )
    release = assess_release_surface(
        project_root,
        version=release_version,
        bundle_manifest=release_bundle_manifest,
        publication_manifest=release_publication_manifest,
        authority_require_register=authority_require_register,
        authority_policy_file=authority_policy_file,
    )
    commands = _commands(
        release_version,
        contract_file,
        authority_require_register=authority_require_register,
        authority_policy_file=authority_policy_file,
    )
    contract_path = str(contract_file.resolve()) if contract_file else None
    lint_surface = _build_lint_surface(
        release_version=release_version,
        contract_path=contract_path,
        trust_ok=trust["ok"],
        release_ok=release["ok"],
        commands=commands,
    )
    lint = lint_text(lint_surface)
    lint_result = {
        "status": lint["status"],
        "violation_count": lint["violation_count"],
        "highest_severity": _highest_severity(lint["violations"]),
        "violations": lint["violations"],
    }
    lint_clean = lint_result["status"] == "clean"
    upstream_ok = trust["ok"] and release["ok"]
    handoff_clean_identity = bool(upstream_ok and lint_clean)
    lint_policy = _evaluate_override_policy(
        lint_result=lint_result,
        fail_on_non_clean=fail_on_non_clean,
        allow_non_clean=allow_non_clean,
        lint_override_source=lint_override_source,
        override_reason_code=override_reason_code,
        override_reason_note=override_reason_note,
    )
    lint_gate_pass = lint_clean or lint_policy["override_active"] or not fail_on_non_clean
    effective_ok = bool(upstream_ok and lint_gate_pass and lint_policy["allow_request_valid"])
    structural = (release.get("structural_promotion") or {})

    return {
        "ok": effective_ok,
        "upstream_ok": upstream_ok,
        "handoff_clean_identity": handoff_clean_identity,
        "project_root": str(project_root),
        "plan_path": str(plan_path),
        "release_version": release_version,
        "contract_path": contract_path,
        "external_contract_repos": [str(path.resolve()) for path in (external_contract_repos or [])],
        "strict_runtime": strict_runtime,
        "authority_require_register": authority_require_register,
        "authority_policy_file": str(authority_policy_file.resolve()) if authority_policy_file else None,
        "structural_promotion_allowed": bool(structural.get("promotion_allowed", False)),
        "structural_failure_class": str(structural.get("failure_class", "")),
        "structural_blocked_reasons": list(structural.get("blocked_reasons") or []),
        "structural_authority_rate": structural.get("structural_authority_rate"),
        "trust_signal": trust,
        "release_surface": release,
        "commands": commands,
        "reviewer_lint": lint_result,
        "reviewer_lint_policy": lint_policy,
    }


def format_human_result(result: dict[str, Any]) -> str:
    trust = result["trust_signal"]
    release = result["release_surface"]
    lint = result.get("reviewer_lint") or {}
    lint_policy = result.get("reviewer_lint_policy") or {}
    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"upstream_ok={result.get('upstream_ok')}",
        f"trust={trust['ok']}",
        f"release={release['ok']}",
        f"lint={lint.get('status', 'unknown')}",
        f"identity={'clean' if result.get('handoff_clean_identity') else 'non-clean'}",
        f"release_version={result['release_version']}",
        f"contract={result.get('contract_path') or 'none'}",
    )
    lines = [
        summary_line,
        "[reviewer_handoff_summary]",
        f"project_root={result['project_root']}",
        f"plan_path={result['plan_path']}",
        f"release_version={result['release_version']}",
        f"contract_path={result.get('contract_path')}",
        f"strict_runtime={result['strict_runtime']}",
        f"external_contract_repo_count={len(result['external_contract_repos'])}",
        f"structural_promotion_allowed={result.get('structural_promotion_allowed')}",
        f"structural_failure_class={result.get('structural_failure_class')}",
        f"structural_blocked_reasons={','.join(result.get('structural_blocked_reasons') or [])}",
        f"structural_authority_rate={result.get('structural_authority_rate')}",
        "[trust_signal]",
        f"ok={trust['ok']}",
        f"quickstart_ok={trust['quickstart']['ok']}",
        f"examples_ok={trust['examples']['ok']}",
        f"release_ok={trust['release']['ok']}",
        f"auditor_ok={trust['auditor']['ok']}",
        "[release_surface]",
        f"ok={release['ok']}",
        f"readiness_ok={release['readiness']['ok']}",
        f"package_ok={release['package']['ok']}",
        f"bundle_available={release['bundle_manifest']['available']}",
        f"publication_available={release['publication_manifest']['available']}",
        f"bundle_source={release['bundle_manifest']['source']}",
        f"publication_source={release['publication_manifest']['source']}",
    ]
    lines.extend(
        [
            "[reviewer_lint]",
            f"status={lint.get('status')}",
            f"violation_count={lint.get('violation_count')}",
            f"highest_severity={lint.get('highest_severity')}",
        ]
    )
    lines.extend(
        [
            "[reviewer_lint_policy]",
            f"fail_on_non_clean={lint_policy.get('fail_on_non_clean')}",
            f"allow_non_clean={lint_policy.get('allow_non_clean')}",
            f"override_active={lint_policy.get('override_active')}",
            f"override_source={lint_policy.get('override_source')}",
            f"override_effect={lint_policy.get('override_effect')}",
            f"override_reason_code={lint_policy.get('override_reason_code')}",
            f"override_reason_note={lint_policy.get('override_reason_note')}",
            f"override_decision_reason={lint_policy.get('override_decision_reason')}",
            f"allow_request_valid={lint_policy.get('allow_request_valid')}",
            f"allow_request_error={lint_policy.get('allow_request_error')}",
            f"override_blocked_by_non_overridable={lint_policy.get('override_blocked_by_non_overridable')}",
            f"non_overridable_claim_types={','.join(lint_policy.get('non_overridable_claim_types') or [])}",
            f"handoff_clean_identity={result.get('handoff_clean_identity')}",
        ]
    )
    if lint.get("violations"):
        for v in sorted(
            lint["violations"],
            key=lambda item: _severity_rank(str(item.get("severity", "low"))),
            reverse=True,
        )[:5]:
            lines.append(
                f"violation={v.get('severity')}|{v.get('claim_type')}|{v.get('excerpt')}"
            )
    if release["bundle_manifest"].get("manifest_file"):
        lines.append(f"bundle_manifest_file={release['bundle_manifest']['manifest_file']}")
    if release["publication_manifest"].get("manifest_file"):
        lines.append(f"publication_manifest_file={release['publication_manifest']['manifest_file']}")
    fact_summaries = _external_project_facts_summaries(result)
    if fact_summaries:
        lines.append("[external_project_facts]")
        lines.extend(facts for facts in fact_summaries)
    lines.append("[commands]")
    for item in result["commands"]:
        lines.append(f"{item['name']}={item['command']}")
    return "\n".join(lines)


def format_markdown_result(result: dict[str, Any]) -> str:
    trust = result["trust_signal"]
    release = result["release_surface"]
    lint = result.get("reviewer_lint") or {}
    lint_policy = result.get("reviewer_lint_policy") or {}
    summary_line = build_summary_line(
        f"ok={result['ok']}",
        f"upstream_ok={result.get('upstream_ok')}",
        f"trust={trust['ok']}",
        f"release={release['ok']}",
        f"lint={lint.get('status', 'unknown')}",
        f"identity={'clean' if result.get('handoff_clean_identity') else 'non-clean'}",
        f"release_version={result['release_version']}",
        f"contract={result.get('contract_path') or 'none'}",
    )
    lines = [
        "# Reviewer Handoff Summary",
        "",
        f"- Summary: `{summary_line}`",
        f"- Project root: `{result['project_root']}`",
        f"- Plan path: `{result['plan_path']}`",
        f"- Release version: `{result['release_version']}`",
        f"- Contract path: `{result.get('contract_path')}`",
        f"- Structural promotion allowed: `{result.get('structural_promotion_allowed')}`",
        f"- Structural failure class: `{result.get('structural_failure_class')}`",
        f"- Structural blocked reasons: `{','.join(result.get('structural_blocked_reasons') or [])}`",
        f"- Structural authority rate: `{result.get('structural_authority_rate')}`",
        "",
        "## Handoff Status",
        "",
        "| Surface | OK | Detail |",
        "| --- | --- | --- |",
        f"| Trust signal | `{trust['ok']}` | quickstart=`{trust['quickstart']['ok']}` examples=`{trust['examples']['ok']}` auditor=`{trust['auditor']['ok']}` |",
        f"| Release surface | `{release['ok']}` | readiness=`{release['readiness']['ok']}` package=`{release['package']['ok']}` bundle=`{'missing' if not release['bundle_manifest']['available'] else release['bundle_manifest']['ok']}` publication=`{'missing' if not release['publication_manifest']['available'] else release['publication_manifest']['ok']}` |",
        f"| Reviewer lint | `{lint.get('status') == 'clean'}` | status=`{lint.get('status')}` violations=`{lint.get('violation_count')}` highest_severity=`{lint.get('highest_severity')}` |",
        f"| Lint policy | `{result.get('handoff_clean_identity')}` | fail_on_non_clean=`{lint_policy.get('fail_on_non_clean')}` allow_non_clean=`{lint_policy.get('allow_non_clean')}` override_active=`{lint_policy.get('override_active')}` reason_code=`{lint_policy.get('override_reason_code')}` decision_reason=`{lint_policy.get('override_decision_reason')}` |",
        "",
    ]
    if lint.get("violations"):
        lines.extend(["## Lint Violations", ""])
        for v in sorted(
            lint["violations"],
            key=lambda item: _severity_rank(str(item.get("severity", "low"))),
            reverse=True,
        )[:5]:
            lines.append(
                f"- `{v.get('severity')}` `{v.get('claim_type')}` — `{v.get('excerpt')}`"
            )
        lines.append("")
    fact_summaries = _external_project_facts_summaries(result)
    if fact_summaries:
        lines.extend(["## External Fact States", ""] + [f"- `{item}`" for item in fact_summaries] + [""])
    lines.extend(["## Suggested Commands", ""])
    for item in result["commands"]:
        lines.append(f"- `{item['command']}`")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize the current reviewer handoff surfaces.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--plan", default="PLAN.md")
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--contract")
    parser.add_argument("--external-contract-repo", action="append", default=[])
    parser.add_argument("--strict-runtime", action="store_true")
    parser.add_argument(
        "--authority-require-register",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    parser.add_argument("--authority-policy-file")
    parser.add_argument("--release-bundle-manifest")
    parser.add_argument("--release-publication-manifest")
    parser.add_argument(
        "--fail-on-non-clean",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail handoff status when reviewer lint is non-clean (default: true).",
    )
    parser.add_argument(
        "--allow-non-clean",
        action="store_true",
        help="Allow non-clean summary to flow while preserving non-clean identity.",
    )
    parser.add_argument(
        "--allow-non-clean-reason-code",
        choices=_ALLOW_REASON_CODES,
        help="Structured reason code for allow-non-clean override.",
    )
    parser.add_argument(
        "--allow-non-clean-reason-note",
        help="Optional reason note. Required when reason code is other_requires_note.",
    )
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.allow_non_clean and not args.allow_non_clean_reason_code:
        parser.error("--allow-non-clean requires --allow-non-clean-reason-code")
    if (
        args.allow_non_clean
        and args.allow_non_clean_reason_code == "other_requires_note"
        and not (args.allow_non_clean_reason_note or "").strip()
    ):
        parser.error(
            "--allow-non-clean-reason-note is required when reason code is other_requires_note"
        )

    result = assess_reviewer_handoff(
        project_root=Path(args.project_root).resolve(),
        plan_path=Path(args.plan),
        release_version=args.release_version,
        contract_file=Path(args.contract).resolve() if args.contract else None,
        external_contract_repos=[Path(item).resolve() for item in args.external_contract_repo],
        strict_runtime=args.strict_runtime,
        authority_require_register=args.authority_require_register,
        authority_policy_file=Path(args.authority_policy_file).resolve() if args.authority_policy_file else None,
        release_bundle_manifest=Path(args.release_bundle_manifest).resolve() if args.release_bundle_manifest else None,
        release_publication_manifest=Path(args.release_publication_manifest).resolve() if args.release_publication_manifest else None,
        fail_on_non_clean=bool(args.fail_on_non_clean),
        allow_non_clean=bool(args.allow_non_clean),
        lint_override_source="cli_allow_non_clean" if args.allow_non_clean else None,
        override_reason_code=args.allow_non_clean_reason_code,
        override_reason_note=args.allow_non_clean_reason_note,
    )
    if args.format == "json":
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
    elif args.format == "markdown":
        rendered = format_markdown_result(result)
    else:
        rendered = format_human_result(result)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

    print(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
