from __future__ import annotations

from .constants import (
    DASHBOARD_CONTRACT_VERSION,
    RELATION_ENUM,
    SEVERITY_ENUM,
    TREND_ENUM,
)


def validate_dashboard_contract_v1(payload: dict) -> list[str]:
    errors: list[str] = []
    if payload.get("contract_version") != DASHBOARD_CONTRACT_VERSION:
        errors.append("contract_version_mismatch")
    for m in payload.get("metrics", []):
        if "metric_id" not in m:
            errors.append("metric_missing_metric_id")
        if "metric_type" not in m:
            errors.append("metric_missing_metric_type")
        if m.get("direction") not in TREND_ENUM:
            errors.append(f"metric_invalid_direction:{m.get('metric_id')}")
        if not m.get("evidence_claim_ids"):
            errors.append(f"metric_missing_evidence:{m.get('metric_id')}")
    for e in payload.get("causal_edges", []):
        if e.get("relation") not in RELATION_ENUM:
            errors.append(f"edge_invalid_relation:{e.get('source_metric')}->{e.get('target_metric')}")
        if not e.get("evidence_claim_ids"):
            errors.append(f"edge_missing_evidence:{e.get('source_metric')}->{e.get('target_metric')}")
    for r in payload.get("risk_surface", []):
        if r.get("severity") not in SEVERITY_ENUM:
            errors.append(f"risk_invalid_severity:{r.get('risk_id')}")
        if r.get("trend") not in TREND_ENUM:
            errors.append(f"risk_invalid_trend:{r.get('risk_id')}")
        if "severity_reason" not in r:
            errors.append(f"risk_missing_reason:{r.get('risk_id')}")
    return errors
