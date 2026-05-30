from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from services.trend import generate_trend, get_trend
from auth.jwt_bearer import JWTBearer

router = APIRouter(dependencies=[Depends(JWTBearer())])


class TrendRequest(BaseModel):
    document_ids: list[str]
    kpi_list: list[str] | None = None


@router.post("/trend")
async def create_trend_report(body: TrendRequest):
    """
    接受 2-N 份已 summary 完成的 document_id，產生跨期 KPI 趨勢報告。

    - document_ids: 同公司不同季的 document_id（需各自已完成 /ingest + /summary）
    - kpi_list: 指定追蹤的 KPI（可選，預設追蹤 revenue/gross_margin/eps/cash 等 8 項）
    - R7 guard: 期數 < 3 時 r7_warning=True，不可推論長期趨勢
    """
    if len(body.document_ids) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 份文件才能產生趨勢")
    try:
        return generate_trend(body.document_ids, kpi_list=body.kpi_list)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trend/{trend_report_id}")
async def fetch_trend_report(trend_report_id: str):
    """取得已產生的跨期趨勢報告"""
    try:
        return get_trend(trend_report_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
