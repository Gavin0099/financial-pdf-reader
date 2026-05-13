#!/usr/bin/env python3
"""
Observe workflow entry-layer artifacts without turning them into verdicts.

This module intentionally uses observational language only:
  - recognized
  - missing
  - incomplete
  - stale
  - unverifiable

It does NOT infer that a workflow was followed or skipped internally. It only
describes what artifacts are observable and whether they are recognizable under
the entry-layer contract.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from governance_tools.workflow_observation_policy import (
    consumer_defaults,
    diagnostic_field_policy,
    load_workflow_observation_policy,
    metric_policy,
    observation_metric_name,
    state_diagnostics,
    state_policy,
)


EXPECTED_ARTIFACTS: dict[str, dict[str, Any]] = {
    "tech_spec": {
        "skill": "tech-spec",
        "required_payload": ["task", "problem", "scope", "non_goals", "evidence_plan"],
        "recognized_statuses": {"completed"},
    },
    "validation_evidence": {
        "skill": "precommit",
        "required_payload": ["entrypoint", "mode", "result", "summary"],
        "recognized_statuses": {"passed", "completed"},
    },
    "pr_handoff": {
        "skill": "create-pr",
        "required_payload": ["change_summary", "scope_included", "scope_excluded", "risk_summary", "evidence_summary"],
        "recognized_statuses": {"completed"},
    },
}

REQUIRED_ENVELOPE_FIELDS = ["artifact_type", "skill", "scope", "timestamp", "status", "provenance"]
OBSERVATION_STATES = {"recognized", "missing", "incomplete", "stale", "unverifiable"}
DEFAULT_STALE_DAYS = 14


def _split_state_policy(state: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return state_policy(state), state_diagnostics(state)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "task"


def default_task_artifact_dir(artifacts_root: Path, task_text: str) -> Path:
    return artifacts_root / _slugify(task_text)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _scope_matches(scope: dict[str, Any], *, project_root: Path, task_text: str | None) -> bool:
    repo_root = scope.get("repo_root")
    if not repo_root:
        return False
    try:
        same_root = Path(repo_root).resolve() == project_root.resolve()
    except OSError:
        return False
    if not same_root:
        return False
    if task_text is None:
        return True
    return scope.get("task_text") == task_text


def _classify_artifact(
    artifact_type: str,
    payload: dict[str, Any],
    *,
    project_root: Path,
    task_text: str | None,
    stale_days: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    spec = EXPECTED_ARTIFACTS[artifact_type]

    for field in REQUIRED_ENVELOPE_FIELDS:
        if field not in payload:
            reasons.append(f"missing envelope field: {field}")
    if reasons:
        return "incomplete", reasons

    if payload.get("skill") != spec["skill"]:
        reasons.append(f"skill mismatch: expected {spec['skill']}")
        return "unverifiable", reasons

    timestamp = _parse_timestamp(str(payload.get("timestamp", "")))
    if timestamp is None:
        reasons.append("timestamp is not a valid ISO 8601 value")
        return "unverifiable", reasons

    scope = payload.get("scope")
    if not isinstance(scope, dict) or not _scope_matches(scope, project_root=project_root, task_text=task_text):
        reasons.append("scope does not match the current observable context")
        return "unverifiable", reasons

    provenance = payload.get("provenance")
    if not isinstance(provenance, dict) or not provenance.get("producer") or not provenance.get("repository_path"):
        reasons.append("provenance is missing required producer or repository_path")
        return "unverifiable", reasons

    content = payload.get("content")
    if not isinstance(content, dict):
        reasons.append("content payload is missing")
        return "incomplete", reasons

    missing_payload = [field for field in spec["required_payload"] if field not in content]
    if missing_payload:
        reasons.append(f"missing content fields: {', '.join(missing_payload)}")
        return "incomplete", reasons

    status = payload.get("status")
    if status == "partial":
        reasons.append("artifact status is partial")
        return "incomplete", reasons
    if status not in spec["recognized_statuses"]:
        reasons.append(f"status {status!r} is not recognized for {artifact_type}")
        return "unverifiable", reasons

    # Freshness is evaluated only after trust-linkage and recognition preconditions.
    # Otherwise a stale timestamp can mask a more important unverifiable condition
    # such as scope mismatch or missing provenance.
    if timestamp < datetime.now(timezone.utc) - timedelta(days=stale_days):
        reasons.append(f"artifact older than {stale_days}d freshness window")
        return "stale", reasons

    return "recognized", reasons


def observe_workflow_entry(
    *,
    project_root: Path,
    artifacts_root: Path,
    task_text: str | None = None,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> dict[str, Any]:
    observations: dict[str, dict[str, Any]] = {}
    recognized_count = 0
    policy = load_workflow_observation_policy()

    for artifact_type in EXPECTED_ARTIFACTS:
        task_dir = default_task_artifact_dir(artifacts_root, task_text) if task_text else artifacts_root
        artifact_path = task_dir / f"{artifact_type}.json"
        if not artifact_path.exists():
            state_policy_data, diagnostics = _split_state_policy("missing")
            observations[artifact_type] = {
                "state": "missing",
                "artifact_path": str(artifact_path),
                "reasons": ["artifact file not found"],
                "state_policy": state_policy_data,
                "diagnostics": diagnostics,
            }
            continue

        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            state_policy_data, diagnostics = _split_state_policy("unverifiable")
            observations[artifact_type] = {
                "state": "unverifiable",
                "artifact_path": str(artifact_path),
                "reasons": [f"artifact could not be parsed: {exc}"],
                "state_policy": state_policy_data,
                "diagnostics": diagnostics,
            }
            continue

        state, reasons = _classify_artifact(
            artifact_type,
            payload,
            project_root=project_root,
            task_text=task_text,
            stale_days=stale_days,
        )
        if state == "recognized":
            recognized_count += 1
        state_policy_data, diagnostics = _split_state_policy(state)
        observations[artifact_type] = {
            "state": state,
            "artifact_path": str(artifact_path),
            "reasons": reasons,
            "state_policy": state_policy_data,
            "diagnostics": diagnostics,
        }

    state_counts = {state: 0 for state in OBSERVATION_STATES}
    for item in observations.values():
        state_counts[item["state"]] += 1

    expected_count = len(EXPECTED_ARTIFACTS)
    observation_coverage = round(recognized_count / expected_count, 2) if expected_count else 0.0

    return {
        "schema_version": 1,
        "observation_mode": "workflow-entry",
        "project_root": str(project_root.resolve()),
        "artifacts_root": str(artifacts_root.resolve()),
        "task_text": task_text,
        "observation_coverage": observation_coverage,
        "coverage_metric": observation_metric_name(),
        "expected_artifact_count": expected_count,
        "recognized_artifact_count": recognized_count,
        "state_counts": state_counts,
        "artifact_observations": observations,
        "observation_subject": policy.get("scope", {}).get("subject"),
        "semantic_boundary": {
            "observation_only": True,
            "artifact_recognizer_only": True,
            "not_a_workflow_fact": True,
            "forbidden_verdict_terms": ["followed", "skipped", "compliant", "non-compliant"],
            "allowed_states": sorted(OBSERVATION_STATES),
            "metric_policy": metric_policy(),
            "consumer_defaults": consumer_defaults(),
            "surface_roles": {
                "state_policy": "observation-state semantics only",
                "diagnostics": "diagnostic-only metadata",
                "metric_policy": "coverage-only metric semantics",
            },
            "diagnostic_fields": {
                "failure_source_class": diagnostic_field_policy("failure_source_class"),
            },
            "interpretation_contract": {
                "version": policy.get("version"),
                "path": str((Path(__file__).resolve().parents[1] / "governance" / "workflow_observation_interpretation.v1.json").resolve()),
            },
        },
    }


def format_human_result(result: dict[str, Any]) -> str:
    lines = [
        "[workflow_entry_observer]",
        f"observation_coverage={result['observation_coverage']}",
        f"coverage_metric={result['coverage_metric']}",
        "metric_boundary=coverage-only; not-a-score-or-threshold",
        f"recognized_artifact_count={result['recognized_artifact_count']}/{result['expected_artifact_count']}",
        "semantic_boundary=observation_only",
        f"observation_subject={result['observation_subject']}",
    ]
    for artifact_type, observation in result["artifact_observations"].items():
        lines.append(f"{artifact_type}={observation['state']}")
        failure_source_class = observation.get("diagnostics", {}).get("failure_source_class")
        if failure_source_class:
            lines.append(f"  failure_source_class={failure_source_class}")
        for reason in observation["reasons"]:
            lines.append(f"  reason={reason}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Observe workflow entry artifacts without turning them into verdicts.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--artifacts-root", default="artifacts/workflow-entry")
    parser.add_argument("--task-text")
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = observe_workflow_entry(
        project_root=Path(args.project_root).resolve(),
        artifacts_root=Path(args.artifacts_root).resolve(),
        task_text=args.task_text,
        stale_days=args.stale_days,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())