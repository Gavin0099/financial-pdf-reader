import logging

from fastapi import APIRouter, HTTPException, Depends
from models.documents import PDFDocument, PDFChunk
from models.reports import AIReport
from services.dashboard_contract import serialize_summary_response
from services.summarization import generate_summary
from auth.jwt_bearer import JWTBearer

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(JWTBearer())])


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


@router.get("/{document_id}/summary/{report_id}/coverage")
async def get_coverage(document_id: str, report_id: str):
    """
    回傳此摘要報告的讀取覆蓋率：
    哪些頁被送入 Claude、哪些頁沒有被讀到。
    coverage_pct 以頁為單位（非 chunk 數量）。
    """
    report = AIReport.objects(report_id=report_id, document_id=document_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    doc = PDFDocument.objects(document_id=document_id).first()
    total_pages = int(doc.total_pages) if doc and doc.total_pages else 0

    covered_set = {int(p) for p in (report.pages_covered or [])}
    pages_covered = sorted(covered_set)

    if total_pages > 0:
        coverage_pct = round(len(covered_set) / total_pages * 100, 1)
        uncovered_pages = [p for p in range(1, total_pages + 1) if p not in covered_set]
    else:
        coverage_pct = 0.0
        uncovered_pages = []

    total_chunks = PDFChunk.objects(document_id=document_id).count()

    return {
        "report_id": report_id,
        "document_id": document_id,
        "total_pages": total_pages,
        "pages_covered": pages_covered,
        "coverage_pct": coverage_pct,
        "chunks_used": len(report.chunks_used or []),
        "total_chunks": total_chunks,
        "uncovered_pages": uncovered_pages,
    }
