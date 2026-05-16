"""
Dashboard Contract v1
---------------------
Constants, validator, and serializer for the AIReport dashboard payload.
Centralises schema so the summarization service and router share one definition.
"""
from models.reports import AIReport

DASHBOARD_CONTRACT_VERSION = "1.0"

METRIC_TYPE: dict[str, str] = {
    "revenue": "income_statement",
    "gross_margin": "income_statement",
    "operating_income": "income_statement",
    "eps": "per_share",
    "cash": "balance_sheet",
    "debt": "balance_sheet",
    "fx": "exposure",
    "customer_concentration": "risk",
}

TREND_ENUM: set[str] = {"up", "down", "flat"}

_REQUIRED_DASHBOARD_FIELDS = [
    "what_changed",
    "causal_edges",
    "adjustments",
    "risk_surface",
    "transparency",
]


def validate_dashboard_contract_v1(dashboard_payload: dict) -> list[str]:
    errors: list[str] = []
    for field in _REQUIRED_DASHBOARD_FIELDS:
        if field not in dashboard_payload:
            errors.append(f"missing field: {field}")
    for item in dashboard_payload.get("what_changed", []):
        if item.get("direction") not in TREND_ENUM:
            errors.append(f"invalid direction '{item.get('direction')}' for metric '{item.get('metric_id')}'")
    return errors


def serialize_summary_response(
    report: "AIReport",
    document_period: str | None = None,
    requested_period: str | None = None,
) -> dict:
    claims = report.claims or []
    total = len(claims)
    contaminated_count = sum(1 for c in claims if c.contaminated)
    insufficient = sum(
        1 for c in claims
        if c.claim_level == "insufficient_evidence" and not c.contaminated
    )

    return {
        "report_id": report.report_id,
        "document_id": report.document_id,
        "stock_id": report.stock_id,
        "period": report.period,
        "temporal_consistent": report.temporal_consistent,
        "temporal_note": report.temporal_note,
        "document_period": document_period or report.period,
        "requested_period": requested_period or report.period,
        "executive_summary": report.executive_summary,
        "total_claims": total,
        "contaminated_count": contaminated_count,
        "insufficient_evidence_count": insufficient,
        "evidence_status": report.evidence_status,
        "investment_advice_detected": report.investment_advice_detected,
        "narrative_density_score": report.narrative_density_score,
        "narrative_density_weighted_score": report.narrative_density_weighted_score,
        "narrative_flag": report.narrative_flag,
        "completeness_warnings": list(report.completeness_warnings or []),
        "dashboard": report.dashboard or {},
        "dashboard_contract_valid": report.dashboard_contract_valid,
        "dashboard_contract_errors": list(report.dashboard_contract_errors or []),
        "claims": [
            {
                "claim_id": c.claim_id,
                "claim": c.claim,
                "claim_type": c.claim_type,
                "claim_level": c.claim_level,
                "materiality": c.materiality,
                "section_key": c.section_key,
                "recurring": c.recurring,
                "contaminated": c.contaminated,
                "source_type": c.source_type,
                "forward_looking": c.forward_looking,
                "rhetorical_risk_flag": c.rhetorical_risk_flag,
                "rhetorical_risk_terms": list(c.rhetorical_risk_terms or []),
                "attribution_prefix": c.attribution_prefix,
                "confidence": c.confidence,
                "requires_human_review": c.requires_human_review,
                "evidence": [
                    {
                        "page": e.page,
                        "section": e.section,
                        "quoted_text": e.quoted_text,
                    }
                    for e in (c.evidence or [])
                ],
            }
            for c in claims
        ],
    }
