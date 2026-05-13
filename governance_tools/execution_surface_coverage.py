#!/usr/bin/env python3
"""
Generate a first-slice execution surface coverage model.

This layer is decision-aware:

- classifies execution/evidence/authority surfaces by coverage role
- assigns hard/soft/optional requirement levels
- defines a small set of decision-level coverage requirements
- emits reviewer-facing gaps without changing runtime verdicts
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.framework_versioning import repo_root_from_tooling
from governance_tools.runtime_surface_manifest import build_runtime_surface_manifest


SURFACE_CLASSIFICATIONS: list[dict[str, Any]] = [
    {
        "surface_name": "session_start",
        "surface_type": "runtime_entrypoint",
        "coverage_role": "decision",
        "requirement_level": "hard",
        "used_by": ["session_start_governance"],
        "failure_modes_if_missing": [
            {"mode": "blind_spot", "suggested_action": "require_review"},
        ],
    },
    {
        "surface_name": "pre_task_check",
        "surface_type": "runtime_entrypoint",
        "coverage_role": "decision",
        "requirement_level": "hard",
        "used_by": ["pre_task_governance"],
        "failure_modes_if_missing": [
            {"mode": "false_allow", "suggested_action": "require_review"},
            {"mode": "pseudo_allow", "suggested_action": "degrade_confidence"},
        ],
    },
    {
        "surface_name": "post_task_check",
        "surface_type": "runtime_entrypoint",
        "coverage_role": "decision",
        "requirement_level": "hard",
        "used_by": ["post_task_governance"],
        "failure_modes_if_missing": [
            {"mode": "false_allow", "suggested_action": "require_review"},
            {"mode": "false_deny", "suggested_action": "require_review"},
        ],
    },
    {
        "surface_name": "session_end",
        "surface_type": "runtime_entrypoint",
        "coverage_role": "decision",
        "requirement_level": "soft",
        "used_by": ["runtime_reviewability"],
        "failure_modes_if_missing": [
            {"mode": "blind_spot", "suggested_action": "degrade_confidence"},
        ],
    },
    {
        "surface_name": "runtime_verdict_artifact",
        "surface_type": "evidence_surface",
        "coverage_role": "evidence",
        "requirement_level": "hard",
        "used_by": ["runtime_reviewability"],
        "failure_modes_if_missing": [
            {"mode": "pseudo_allow", "suggested_action": "require_review"},
        ],
    },
    {
        "surface_name": "runtime_trace_artifact",
        "surface_type": "evidence_surface",
        "coverage_role": "evidence",
        "requirement_level": "hard",
        "used_by": ["runtime_reviewability"],
        "failure_modes_if_missing": [
            {"mode": "blind_spot", "suggested_action": "require_review"},
        ],
    },
    {
        "surface_name": "runtime_decision_model",
        "surface_type": "authority_surface",
        "coverage_role": "authority",
        "requirement_level": "hard",
        "used_by": [
            "session_start_governance",
            "pre_task_governance",
            "post_task_governance",
            "runtime_reviewability",
        ],
        "failure_modes_if_missing": [
            {"mode": "blind_spot", "suggested_action": "require_review"},
        ],
    },
    {
        "surface_name": "decision_boundary_model",
        "surface_type": "authority_surface",
        "coverage_role": "authority",
        "requirement_level": "soft",
        "used_by": ["pre_task_governance"],
        "failure_modes_if_missing": [
            {"mode": "pseudo_allow", "suggested_action": "degrade_confidence"},
        ],
    },
    {
        "surface_name": "governance_authority_table",
        "surface_type": "authority_surface",
        "coverage_role": "authority",
        "requirement_level": "soft",
        "used_by": ["runtime_reviewability"],
        "failure_modes_if_missing": [
            {"mode": "blind_spot", "suggested_action": "warn_only"},
        ],
    },
]


DECISION_DEFINITIONS: list[dict[str, Any]] = [
    {
        "decision": "session_start_governance",
        "required_surfaces": ["session_start"],
        "evidence_surfaces": [],
        "authority_surfaces": ["runtime_decision_model"],
        "requirement_level": {
            "session_start": "hard",
            "runtime_decision_model": "hard",
        },
    },
    {
        "decision": "pre_task_governance",
        "required_surfaces": ["pre_task_check"],
        "evidence_surfaces": [],
        "authority_surfaces": ["runtime_decision_model", "decision_boundary_model"],
        "requirement_level": {
            "pre_task_check": "hard",
            "runtime_decision_model": "hard",
            "decision_boundary_model": "soft",
        },
    },
    {
        "decision": "post_task_governance",
        "required_surfaces": ["post_task_check"],
        "evidence_surfaces": [],
        "authority_surfaces": ["runtime_decision_model"],
        "requirement_level": {
            "post_task_check": "hard",
            "runtime_decision_model": "hard",
        },
    },
    {
        "decision": "runtime_reviewability",
        "required_surfaces": ["session_end"],
        "evidence_surfaces": ["runtime_verdict_artifact", "runtime_trace_artifact"],
        "authority_surfaces": ["runtime_decision_model", "governance_authority_table"],
        "requirement_level": {
            "session_end": "soft",
            "runtime_verdict_artifact": "hard",
            "runtime_trace_artifact": "hard",
            "runtime_decision_model": "hard",
            "governance_authority_table": "soft",
        },
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _available_surface_names(manifest: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    names.update(entry["entrypoint_name"] for entry in manifest["runtime_entrypoints"])
    names.update(entry["surface_name"] for entry in manifest["evidence_surfaces"])
    names.update(entry["authority_surface"] for entry in manifest["authority_surfaces"])
    return names


def _classifications_by_name() -> dict[str, dict[str, Any]]:
    return {entry["surface_name"]: dict(entry) for entry in SURFACE_CLASSIFICATIONS}


def _decision_requirement_items(decision: dict[str, Any]) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    for surface_name in decision.get("required_surfaces", []):
        items.append(("decision", surface_name, decision["requirement_level"].get(surface_name, "unknown")))
    for surface_name in decision.get("evidence_surfaces", []):
        items.append(("evidence", surface_name, decision["requirement_level"].get(surface_name, "unknown")))
    for surface_name in decision.get("authority_surfaces", []):
        items.append(("authority", surface_name, decision["requirement_level"].get(surface_name, "unknown")))
    return items


def _missing_by_requirement(definitions: list[dict[str, Any]], available: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    missing_hard: list[dict[str, Any]] = []
    missing_soft: list[dict[str, Any]] = []
    for decision in definitions:
        for role, surface_name, level in _decision_requirement_items(decision):
            if surface_name in available:
                continue
            item = {
                "decision": decision["decision"],
                "surface_name": surface_name,
                "coverage_role": role,
                "requirement_level": level,
            }
            if level == "hard":
                missing_hard.append(item)
            elif level == "soft":
                missing_soft.append(item)
    return missing_hard, missing_soft


def _dead_surfaces(classifications: dict[str, dict[str, Any]], available: set[str], definitions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    referenced = {
        surface_name
        for definition in definitions
        for _, surface_name, _ in _decision_requirement_items(definition)
    }
    never_observed: list[dict[str, Any]] = []
    never_required: list[dict[str, Any]] = []

    for surface_name, classification in classifications.items():
        if surface_name not in available:
            never_observed.append({
                "surface_name": surface_name,
                "coverage_role": classification["coverage_role"],
                "requirement_level": classification["requirement_level"],
            })
        elif surface_name not in referenced:
            never_required.append({
                "surface_name": surface_name,
                "coverage_role": classification["coverage_role"],
                "requirement_level": classification["requirement_level"],
            })

    return never_observed, never_required


def _decision_status(definitions: list[dict[str, Any]], missing_hard: list[dict[str, Any]], missing_soft: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hard_by_decision = {}
    soft_by_decision = {}
    for item in missing_hard:
        hard_by_decision.setdefault(item["decision"], []).append(item)
    for item in missing_soft:
        soft_by_decision.setdefault(item["decision"], []).append(item)

    results: list[dict[str, Any]] = []
    for definition in definitions:
        decision = definition["decision"]
        if hard_by_decision.get(decision):
            status = "hard_incomplete"
        elif soft_by_decision.get(decision):
            status = "soft_incomplete"
        else:
            status = "covered"
        results.append({
            "decision": decision,
            "status": status,
            "missing_hard": hard_by_decision.get(decision, []),
            "missing_soft": soft_by_decision.get(decision, []),
        })
    return results


def build_execution_surface_coverage(repo_root: Path | None = None) -> dict[str, Any]:
    root = (repo_root or repo_root_from_tooling()).resolve()
    manifest = build_runtime_surface_manifest(root)
    classifications = _classifications_by_name()
    available = _available_surface_names(manifest)
    missing_hard, missing_soft = _missing_by_requirement(DECISION_DEFINITIONS, available)
    never_observed, never_required = _dead_surfaces(classifications, available, DECISION_DEFINITIONS)
    decisions = _decision_status(DECISION_DEFINITIONS, missing_hard, missing_soft)

    return {
        "generated_at": _utc_now(),
        "repo_root": str(root),
        "repo_commit": manifest.get("repo_commit"),
        "consumer": "reviewer",
        "signal_posture": "soft-enforcement",
        "surface_classifications": list(classifications.values()),
        "decision_definitions": [dict(item) for item in DECISION_DEFINITIONS],
        "decision_status": decisions,
        "coverage": {
            "missing_hard_required": missing_hard,
            "missing_soft_required": missing_soft,
            "dead_surfaces": {
                "never_observed": never_observed,
                "never_required": never_required,
            },
        },
    }


def coverage_has_signal(payload: dict[str, Any]) -> bool:
    coverage = payload["coverage"]
    return any(
        [
            coverage["missing_hard_required"],
            coverage["missing_soft_required"],
            coverage["dead_surfaces"]["never_observed"],
            coverage["dead_surfaces"]["never_required"],
        ]
    )


def render_markdown(payload: dict[str, Any]) -> str:
    coverage = payload["coverage"]
    lines = [
        "# Execution Surface Coverage",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- repo_commit: `{payload['repo_commit']}`",
        f"- consumer: `{payload['consumer']}`",
        f"- signal_posture: `{payload['signal_posture']}`",
        "",
        "## Decision Status",
        "",
        "| Decision | Status | Missing Hard | Missing Soft |",
        "|---|---|---|---|",
    ]
    for item in payload["decision_status"]:
        lines.append(
            f"| `{item['decision']}` | `{item['status']}` | "
            f"`{len(item['missing_hard'])}` | `{len(item['missing_soft'])}` |"
        )

    lines += [
        "",
        "## Coverage Signals",
        "",
        f"- missing_hard_required: `{len(coverage['missing_hard_required'])}`",
        f"- missing_soft_required: `{len(coverage['missing_soft_required'])}`",
        f"- dead_never_observed: `{len(coverage['dead_surfaces']['never_observed'])}`",
        f"- dead_never_required: `{len(coverage['dead_surfaces']['never_required'])}`",
        "",
    ]

    if coverage["missing_hard_required"]:
        lines += ["### Missing Hard Required", ""]
        for item in coverage["missing_hard_required"]:
            lines.append(
                f"- `{item['decision']}` missing `{item['surface_name']}` "
                f"(`{item['coverage_role']}`, `{item['requirement_level']}`)"
            )
        lines.append("")

    if coverage["missing_soft_required"]:
        lines += ["### Missing Soft Required", ""]
        for item in coverage["missing_soft_required"]:
            lines.append(
                f"- `{item['decision']}` missing `{item['surface_name']}` "
                f"(`{item['coverage_role']}`, `{item['requirement_level']}`)"
            )
        lines.append("")

    if coverage["dead_surfaces"]["never_observed"]:
        lines += ["### Dead Surfaces: never_observed", ""]
        for item in coverage["dead_surfaces"]["never_observed"]:
            lines.append(
                f"- `{item['surface_name']}` "
                f"(`{item['coverage_role']}`, `{item['requirement_level']}`)"
            )
        lines.append("")

    if coverage["dead_surfaces"]["never_required"]:
        lines += ["### Dead Surfaces: never_required", ""]
        for item in coverage["dead_surfaces"]["never_required"]:
            lines.append(
                f"- `{item['surface_name']}` "
                f"(`{item['coverage_role']}`, `{item['requirement_level']}`)"
            )
        lines.append("")

    lines += [
        "## Surface Classification",
        "",
        "| Surface | Type | Role | Requirement | Used By |",
        "|---|---|---|---|---|",
    ]
    for item in payload["surface_classifications"]:
        lines.append(
            f"| `{item['surface_name']}` | `{item['surface_type']}` | `{item['coverage_role']}` | "
            f"`{item['requirement_level']}` | `{', '.join(item['used_by'])}` |"
        )

    return "\n".join(lines).rstrip() + "\n"


def format_human(payload: dict[str, Any]) -> str:
    coverage = payload["coverage"]
    return "\n".join([
        "[execution_surface_coverage]",
        f"repo_root={payload['repo_root']}",
        f"repo_commit={payload['repo_commit']}",
        f"consumer={payload['consumer']}",
        f"signal_posture={payload['signal_posture']}",
        f"decisions={len(payload['decision_definitions'])}",
        f"missing_hard_required={len(coverage['missing_hard_required'])}",
        f"missing_soft_required={len(coverage['missing_soft_required'])}",
        f"dead_never_observed={len(coverage['dead_surfaces']['never_observed'])}",
        f"dead_never_required={len(coverage['dead_surfaces']['never_required'])}",
    ])


def _write_outputs(repo_root: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    generated_dir = repo_root / "docs" / "status" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    generated_json = generated_dir / "execution-surface-coverage.json"
    generated_md = repo_root / "docs" / "status" / "execution-surface-coverage.md"
    generated_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generated_md.write_text(render_markdown(payload), encoding="utf-8")
    return generated_json, generated_md


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a first-slice execution surface coverage model.")
    parser.add_argument("--repo-root", help="Framework repo root (default: auto-detect).")
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    parser.add_argument("--write", action="store_true", help="Write generated JSON and Markdown outputs to docs/status/.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None
    payload = build_execution_surface_coverage(repo_root)
    if args.write:
        _write_outputs(Path(payload["repo_root"]), payload)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(render_markdown(payload), end="")
    else:
        print(format_human(payload))
    return 1 if coverage_has_signal(payload) else 0


if __name__ == "__main__":
    raise SystemExit(main())
