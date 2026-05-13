#!/usr/bin/env python3
"""
Generic external observation adapter.

Transforms untrusted external payloads into canonical advisory-only envelope.
"""

from __future__ import annotations

from typing import Any

from governance_tools.phase2_aggregation_consumer import normalize_misuse_evidence_status

_ALLOWED_CONFIDENCE = frozenset({"low", "medium", "high", "unknown"})

_FORBIDDEN_AUTHORITY_FIELDS = frozenset({
    "verdict",
    "gate_verdict",
    "current_state",
    "closure_verified",
    "promote_eligible",
    "phase3_entry_allowed",
    "closure_review_approved",
})


def _safe_list_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [x.strip() for x in value if isinstance(x, str) and x.strip()]


def normalize_external_observation(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("external payload must be dict")

    warnings: list[str] = []
    notes: list[str] = []
    ingest_status = "accepted"

    forbidden_seen = sorted(k for k in _FORBIDDEN_AUTHORITY_FIELDS if k in payload)
    if forbidden_seen:
        ingest_status = "degraded"
        warnings.append(
            "forbidden authority fields detected and ignored: " + ", ".join(forbidden_seen)
        )

    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    source_id = source.get("source_id")
    source_type = source.get("source_type")
    producer_version = source.get("producer_version")

    if not isinstance(source_id, str) or not source_id.strip():
        source_id = "unknown_source"
        ingest_status = "degraded"
        warnings.append("missing source.source_id -> downgraded to unknown_source")
    else:
        source_id = source_id.strip()

    if not isinstance(source_type, str) or not source_type.strip():
        source_type = "unknown_type"
        ingest_status = "degraded"
        warnings.append("missing source.source_type -> downgraded to unknown_type")
    else:
        source_type = source_type.strip()

    observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
    raw_status = observation.get("misuse_evidence_status", "not_tested")
    try:
        status = normalize_misuse_evidence_status(str(raw_status))
    except ValueError:
        status = "not_tested"
        ingest_status = "degraded"
        warnings.append(
            f"invalid misuse_evidence_status {raw_status!r} -> downgraded to not_tested"
        )

    confidence = observation.get("confidence_level", "unknown")
    if not isinstance(confidence, str) or confidence not in _ALLOWED_CONFIDENCE:
        confidence = "unknown"
        ingest_status = "degraded"
        warnings.append("invalid confidence_level -> downgraded to unknown")

    evidence_refs = _safe_list_str(observation.get("evidence_refs"))
    if status == "observed" and not evidence_refs:
        ingest_status = "degraded"
        warnings.append("observed status without evidence_refs -> degraded")

    # External input is always advisory-only and never carries decision authority.
    notes.append("external observation ingested as advisory-only evidence")

    return {
        "ingest_status": ingest_status,
        "source": {
            "source_id": source_id,
            "source_type": source_type,
            "producer_version": producer_version if isinstance(producer_version, str) else None,
        },
        "observation": {
            "misuse_evidence_status": status,
            "evidence_refs": evidence_refs,
            "confidence_level": confidence,
        },
        "advisory": {
            "warnings": warnings,
            "notes": notes,
        },
        "decision_constraints": {
            "external_authority": False,
            "verdict_authority": False,
            "promotion_authority": False,
        },
    }

