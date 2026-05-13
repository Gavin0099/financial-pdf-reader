#!/usr/bin/env python3
"""Machine-readable runtime phase execution policy helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_RUNTIME_PHASE_POLICY_PATH = Path("governance/runtime/runtime_phase_policy.yaml")
PHASE_ORDER = (
    "sync_gate",
    "sync_advisory",
    "async_closeout",
    "async_audit",
    "manual_review_only",
)
REQUIRED_RULES = {
    "sync_gate_blocks_execution": True,
    "sync_advisory_hidden_gate_allowed": False,
    "async_audit_can_retroactively_change_verdict": False,
}
REQUIRED_PHASE_EFFECTS = {
    "sync_gate": "blocks_execution",
    "sync_advisory": "advisory_only",
    "async_closeout": "deferred_closeout",
    "async_audit": "deferred_audit",
    "manual_review_only": "human_authority_required",
}


def _validate_runtime_phase_policy(data: dict[str, Any], *, path: Path) -> dict[str, Any]:
    schema_version = str(data.get("schema_version", "")).strip()
    if not schema_version:
        raise ValueError(f"runtime phase policy missing schema_version: {path}")

    rules = data.get("rules")
    if not isinstance(rules, dict):
        raise ValueError(f"runtime phase policy rules must be a mapping: {path}")
    for rule_name, expected_value in REQUIRED_RULES.items():
        actual_value = rules.get(rule_name)
        if actual_value is not expected_value:
            raise ValueError(
                f"runtime phase policy rule {rule_name} must be {expected_value!r}: {path}"
            )

    phases = data.get("phases")
    if not isinstance(phases, dict):
        raise ValueError(f"runtime phase policy phases must be a mapping: {path}")
    for phase_name in PHASE_ORDER:
        spec = phases.get(phase_name)
        if not isinstance(spec, dict):
            raise ValueError(f"runtime phase policy phase {phase_name} must be a mapping: {path}")
        expected_effect = REQUIRED_PHASE_EFFECTS[phase_name]
        actual_effect = str(spec.get("execution_effect", "")).strip()
        if actual_effect != expected_effect:
            raise ValueError(
                f"runtime phase policy phase {phase_name} must declare execution_effect={expected_effect!r}: {path}"
            )

    actions = data.get("actions")
    if not isinstance(actions, dict):
        raise ValueError(f"runtime phase policy actions must be a mapping: {path}")
    for action_name, spec in actions.items():
        if not isinstance(spec, dict):
            raise ValueError(f"runtime phase policy action {action_name} must be a mapping: {path}")
        phase = str(spec.get("phase", "")).strip()
        if phase not in PHASE_ORDER:
            raise ValueError(
                f"runtime phase policy action {action_name} references unknown phase {phase!r}: {path}"
            )

    return data


def load_runtime_phase_policy(*, framework_root: Path | None = None) -> dict[str, Any]:
    root = framework_root or Path(__file__).resolve().parent.parent
    path = root / DEFAULT_RUNTIME_PHASE_POLICY_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"runtime phase policy must be a mapping: {path}")
    return _validate_runtime_phase_policy(data, path=path)


def build_phase_classification(
    *,
    action_ids: list[str],
    hook: str,
    framework_root: Path | None = None,
) -> dict[str, Any]:
    policy = load_runtime_phase_policy(framework_root=framework_root)
    actions = policy.get("actions") or {}
    phase_summary = {phase: [] for phase in PHASE_ORDER}
    unknown_actions: list[str] = []
    entries: list[dict[str, Any]] = []

    for action_id in action_ids:
        action = str(action_id).strip()
        if not action:
            continue
        spec = actions.get(action)
        if not isinstance(spec, dict):
            unknown_actions.append(action)
            continue
        phase = str(spec.get("phase", "")).strip()
        if phase not in phase_summary:
            unknown_actions.append(action)
            continue
        phase_summary[phase].append(action)
        entries.append(
            {
                "action": action,
                "phase": phase,
                "owner": spec.get("owner"),
                "description": spec.get("description"),
            }
        )

    compact_summary = {phase: values for phase, values in phase_summary.items() if values}
    return {
        "schema_version": policy.get("schema_version"),
        "hook": hook,
        "actions": entries,
        "phase_summary": compact_summary,
        "rules": policy.get("rules") or {},
        "unknown_actions": unknown_actions,
    }


def aggregate_phase_classifications(
    *,
    phase_classifications: dict[str, dict[str, Any]],
    framework_root: Path | None = None,
) -> dict[str, Any]:
    policy = load_runtime_phase_policy(framework_root=framework_root)
    aggregated = {phase: [] for phase in PHASE_ORDER}

    for _, payload in phase_classifications.items():
        if not isinstance(payload, dict):
            continue
        for phase, actions in (payload.get("phase_summary") or {}).items():
            if phase not in aggregated:
                continue
            for action in actions:
                if action not in aggregated[phase]:
                    aggregated[phase].append(action)

    return {
        "schema_version": policy.get("schema_version"),
        "phase_classifications": phase_classifications,
        "phase_summary": {phase: values for phase, values in aggregated.items() if values},
        "rules": policy.get("rules") or {},
    }
