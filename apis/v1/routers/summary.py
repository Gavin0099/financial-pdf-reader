import logging

from fastapi import APIRouter, HTTPException
from models.reports import AIReport
from services.summarization import generate_summary

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{document_id}/summary")
async def create_summary(document_id: str):
    """
    對已 ingest 的 PDF 產生 evidence-bound 財報摘要。
    每個 claim 都附頁碼；沒有 evidence 的 claim 自動標為 insufficient_evidence。
    不輸出投資建議。
    """
    try:
        result = generate_summary(document_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("generate_summary unexpected error: document_id=%s", document_id)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {type(e).__name__}: {e}")


@router.get("/{document_id}/summary/{report_id}")
async def get_summary(document_id: str, report_id: str):
    """取得已產生的摘要報告"""
    report = AIReport.objects(report_id=report_id, document_id=document_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return {
        "report_id": report.report_id,
        "document_id": report.document_id,
        "stock_id": report.stock_id,
        "period": report.period,
        "evidence_status": report.evidence_status,
        "investment_advice_detected": report.investment_advice_detected,
        "completeness_warnings": list(report.completeness_warnings or []),
        "created_at": str(report.created_at),
        "claims": [
            {
                "claim_id": c.claim_id,
                "claim": c.claim,
                "claim_type": c.claim_type,
                "claim_level": c.claim_level,
                "confidence": c.confidence,
                "source_type": c.source_type,
                "attribution_prefix": c.attribution_prefix,
                "forward_looking": c.forward_looking,
                "rhetorical_risk_flag": c.rhetorical_risk_flag,
                "requires_human_review": c.requires_human_review,
                "evidence": [
                    {"page": e.page, "section": e.section, "quoted_text": e.quoted_text}
                    for e in c.evidence
                ],
            }
            for c in report.claims
        ],
    }
