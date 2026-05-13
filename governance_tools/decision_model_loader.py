#!/usr/bin/env python3
"""Helpers for reading the governance runtime decision model."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


DECISION_MODEL_PATH = Path(__file__).resolve().parents[1] / "governance" / "governance_decision_model.v2.6.json"


@lru_cache(maxsize=1)
def load_decision_model() -> dict[str, Any]:
    return json.loads(DECISION_MODEL_PATH.read_text(encoding="utf-8"))


def decision_model_version() -> str:
    return str(load_decision_model().get("version", "unknown"))


def runtime_version_tag() -> str:
    payload = load_decision_model()
    version = str(payload.get("version", "unknown"))
    status = str(payload.get("status", "draft")).strip() or "draft"
    return f"v{version}-{status}-runtime"


def build_runtime_policy_ref(*, artifact_schema_version: str = "1.0") -> dict[str, str]:
    return {
        "governance_runtime_decision_model": decision_model_version(),
        "artifact_schema_version": artifact_schema_version,
        "runtime_version": runtime_version_tag(),
    }


def required_evidence_kinds() -> set[str]:
    rows = load_decision_model().get("matrices", {}).get("evidence_classification", [])
    return {
        str(row["evidence_kind"])
        for row in rows
        if row.get("required") is True and str(row.get("evidence_kind", "")).strip()
    }


def policy_precedence_rows() -> list[dict[str, Any]]:
    return list(load_decision_model().get("matrices", {}).get("policy_precedence", []))


def violation_handling_rows() -> list[dict[str, Any]]:
    return list(load_decision_model().get("matrices", {}).get("violation_handling", []))


def violation_verdict_impact(violation_type: str, default: str) -> str:
    for row in violation_handling_rows():
        if str(row.get("violation_type")) == violation_type:
            value = str(row.get("default_verdict_impact", "")).strip()
            return value or default
    return default


def runtime_decision_source() -> str:
    return str(load_decision_model().get("enforcement_model", {}).get("runtime_role", "unknown"))


def final_verdict_owner() -> str:
    rows = load_decision_model().get("matrices", {}).get("decision_ownership", [])
    for row in rows:
        if str(row.get("concern")) == "final governance verdict":
            return str(row.get("owner", "unknown"))
    return "unknown"
