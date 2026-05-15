import logging

from fastapi import APIRouter, HTTPException
from models.reports import AIReport
from services.dashboard_contract import serialize_summary_response
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

    payload = serialize_summary_response(report)
    payload["created_at"] = str(report.created_at)
    return payload
