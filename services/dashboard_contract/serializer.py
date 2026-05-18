from __future__ import annotations

from models.reports import AIReport


def serialize_summary_response(
    report: AIReport,
    *,
    document_period: str | None = None,
    requested_period: str | None = None,
) -> dict:
    claims = list(report.claims or [])
    total = len(claims)
    contaminated_count = sum(1 for c in claims if c.contaminated)
    insufficient = sum(1 for c in claims if c.claim_level == "insufficient_evidence" and not c.contaminated)
    return {
        "report_id": report.report_id,
        "document_id": report.document_id,
        "stock_id": report.stock_id,
        "period": report.period,
        "temporal_consistent": bool(report.temporal_consistent),
        "temporal_note": report.temporal_note or "",
        "document_period": document_period or report.period,
        "requested_period": requested_period or report.period,
        "executive_summary": report.executive_summary or "",
        "total_claims": total,
        "contaminated_count": contaminated_count,
        "insufficient_evidence_count": insufficient,
        "evidence_status": report.evidence_status,
        "investment_advice_detected": bool(report.investment_advice_detected),
        "narrative_density_score": float(report.narrative_density_score or 0.0),
        "narrative_density_weighted_score": float(report.narrative_density_weighted_score or 0.0),
        "narrative_flag": bool(report.narrative_flag),
        "dashboard": report.dashboard or {},
        "dashboard_contract_valid": bool(report.dashboard_contract_valid),
        "dashboard_contract_errors": list(report.dashboard_contract_errors or []),
        "completeness_warnings": list(report.completeness_warnings or []),
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
                "rhetorical_risk_terms": list(c.rhetorical_risk_terms),
                "attribution_prefix": c.attribution_prefix,
                "confidence": c.confidence,
                "requires_human_review": c.requires_human_review,
                "evidence": [
                    {"page": e.page, "section": e.section, "quoted_text": e.quoted_text}
                    for e in c.evidence
                ],
            }
            for c in claims
        ],
    }
