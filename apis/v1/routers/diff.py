from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models.reports import DiffReport
from services.diff import generate_diff, _serialize_report

router = APIRouter()


class DiffRequest(BaseModel):
    current_document_id: str
    previous_document_id: str


@router.post("/diff")
async def create_diff_report(body: DiffRequest):
    """
    比較兩份同公司財報（current vs previous），產生 diff report。
    每個差異項目都附來源頁碼。
    語氣變化標記 tone_only=true，不等同財務惡化。
    """
    try:
        result = generate_diff(body.current_document_id, body.previous_document_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diff/{diff_report_id}")
async def get_diff_report(diff_report_id: str):
    """取得已產生的 diff report"""
    report = DiffReport.objects(diff_report_id=diff_report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Diff report not found")
    return _serialize_report(report)
