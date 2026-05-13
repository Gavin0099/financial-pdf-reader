#!/usr/bin/env python3
"""
Helpers for extracting external contract context from session artifacts.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from governance_tools.domain_governance_metadata import domain_risk_tier


def normalize_session_start_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("event_type") == "session_start" and isinstance(payload.get("result"), dict):
        return payload["result"]
    return payload


def extract_contract_context(session_start_payload: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_session_start_payload(session_start_payload or {})
    contract_resolution = payload.get("contract_resolution") or {}
    domain_contract = payload.get("domain_contract") or {}
    domain_raw = domain_contract.get("raw") or {}

    return {
        "source": contract_resolution.get("source"),
        "path": contract_resolution.get("path") or payload.get("resolved_contract_file"),
        "name": domain_contract.get("name"),
        "domain": domain_raw.get("domain"),
        "plugin_version": domain_raw.get("plugin_version"),
        "risk_tier": domain_risk_tier(domain_raw.get("domain")),
    }


def contract_label(contract_context: dict[str, Any]) -> str | None:
    return contract_context.get("domain") or contract_context.get("name")
