#!/usr/bin/env python3
"""Helpers for reading the workflow observation interpretation contract."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


OBSERVATION_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "governance" / "workflow_observation_interpretation.v1.json"
)


@lru_cache(maxsize=1)
def load_workflow_observation_policy() -> dict[str, Any]:
    return json.loads(OBSERVATION_POLICY_PATH.read_text(encoding="utf-8"))


def observation_metric_name() -> str:
    return str(load_workflow_observation_policy().get("metric", {}).get("name", "observation_coverage"))


def metric_policy() -> dict[str, Any]:
    return dict(load_workflow_observation_policy().get("metric", {}))


def state_policy(state: str) -> dict[str, Any]:
    policy = load_workflow_observation_policy().get("states", {})
    state_data = dict(policy.get(state, {}))
    state_data.pop("failure_source_class", None)
    return state_data


def state_diagnostics(state: str) -> dict[str, Any]:
    policy = load_workflow_observation_policy().get("states", {})
    state_data = dict(policy.get(state, {}))
    return {"failure_source_class": state_data.get("failure_source_class")}


def consumer_defaults() -> dict[str, Any]:
    return dict(load_workflow_observation_policy().get("consumer_defaults", {}))


def diagnostic_field_policy(field_name: str) -> dict[str, Any]:
    fields = load_workflow_observation_policy().get("diagnostic_fields", {})
    return dict(fields.get(field_name, {}))
