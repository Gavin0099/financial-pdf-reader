#!/usr/bin/env python3
"""
Build a proposal-time governance artifact from task context, rule suggestions, and impact estimation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.architecture_impact_estimator import estimate_architecture_impact
from governance_tools.rule_pack_loader import parse_rule_list
from governance_tools.rule_pack_suggester import suggest_rule_packs


def _infer_scope(requested_rules: list[str], suggestions: dict) -> str:
    if "refactor" in requested_rules:
        return "refactor"
    for item in suggestions.get("scope_packs", []):
        if item.get("name") == "refactor":
            return "refactor"
    return "feature"


def build_proposal_summary(result: dict) -> dict:
    guidance = result.get("proposal_guidance") or {}
    return {
        "task": result.get("task", ""),
        "requested_rules": result.get("requested_rules", []) or [],
        "suggested_rules_preview": result.get("suggested_rules_preview", []) or [],
        "recommended_risk": guidance.get("recommended_risk"),
        "recommended_oversight": guidance.get("recommended_oversight"),
        "expected_validators": guidance.get("expected_validators", []) or [],
        "required_evidence": guidance.get("required_evidence", []) or [],
        "concerns": guidance.get("concerns", []) or [],
    }


def build_change_proposal(
    *,
    project_root: Path,
    task_text: str,
    rules: str = "common",
    impact_before_files: list[Path] | None = None,
    impact_after_files: list[Path] | None = None,
) -> dict:
    requested_rules = parse_rule_list(rules)
    suggestions = suggest_rule_packs(project_root, task_text=task_text)
    impact_before_files = impact_before_files or []
    impact_after_files = impact_after_files or []
    impact_preview = None

    if impact_before_files or impact_after_files:
        impact_preview = estimate_architecture_impact(
            impact_before_files,
            impact_after_files,
            scope=_infer_scope(requested_rules, suggestions),
            active_rules=requested_rules,
        )

    proposal_guidance = None
    if impact_preview:
        proposal_guidance = {
            "recommended_risk": impact_preview.get("recommended_risk"),
            "recommended_oversight": impact_preview.get("recommended_oversight"),
            "expected_validators": impact_preview.get("expected_validators", []) or [],
            "required_evidence": impact_preview.get("required_evidence", []) or [],
            "concerns": impact_preview.get("concerns", []) or [],
        }

    result = {
        "task": task_text,
        "project_root": str(project_root.resolve()),
        "requested_rules": requested_rules,
        "suggested_rules_preview": suggestions.get("suggested_rules_preview", []),
        "rule_pack_suggestions": suggestions,
        "architecture_impact_preview": impact_preview,
        "proposal_guidance": proposal_guidance,
    }
    result["proposal_summary"] = build_proposal_summary(result)
    return result


def format_human_result(result: dict) -> str:
    lines = [
        "[change_proposal]",
        f"task={result['task']}",
        f"requested_rules={','.join(result.get('requested_rules') or [])}",
    ]
    preview = result.get("suggested_rules_preview") or []
    if preview:
        lines.append(f"suggested_rules_preview={','.join(preview)}")

    summary = result.get("proposal_summary") or {}
    guidance = result.get("proposal_guidance") or {}
    if guidance:
        lines.append("[proposal_guidance]")
        lines.append(f"recommended_risk={summary.get('recommended_risk')}")
        lines.append(f"recommended_oversight={summary.get('recommended_oversight')}")
        validators = summary.get("expected_validators") or []
        if validators:
            lines.append(f"expected_validators={','.join(validators)}")
        evidence = summary.get("required_evidence") or []
        if evidence:
            lines.append(f"required_evidence={','.join(evidence)}")
        concerns = summary.get("concerns") or []
        if concerns:
            lines.append(f"concerns={','.join(concerns)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a proposal-time governance artifact.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--task-text", required=True)
    parser.add_argument("--rules", default="common")
    parser.add_argument("--impact-before", action="append", default=[])
    parser.add_argument("--impact-after", action="append", default=[])
    parser.add_argument("--format", choices=["human", "json"], default="json")
    parser.add_argument("--output")
    args = parser.parse_args()

    result = build_change_proposal(
        project_root=Path(args.project_root),
        task_text=args.task_text,
        rules=args.rules,
        impact_before_files=[Path(path) for path in args.impact_before],
        impact_after_files=[Path(path) for path in args.impact_after],
    )

    rendered = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else format_human_result(result)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
