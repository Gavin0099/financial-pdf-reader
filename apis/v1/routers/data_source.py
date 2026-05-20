from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from models.external import ExternalDataRecord
from services.data_source import (
    fetch_monthly_revenue,
    fetch_financial_statement,
    crosscheck_with_pdf,
)
from auth.jwt_bearer import JWTBearer

router = APIRouter(dependencies=[Depends(JWTBearer())])


@router.post("/{stock_id}/fetch-revenue")
async def get_monthly_revenue(stock_id: str, period: str = Query(..., examples="2026Q1")):
    """
    從 FinMind 抓取台股月營收（當季三個月）。
    資料來源：FinMind / TWSE，僅作輔助參考。
    """
    try:
        records = fetch_monthly_revenue(stock_id, period)
        return {
            "stock_id": stock_id,
            "period": period,
            "data_source": "FinMind/TaiwanStockMonthRevenue",
            "is_auxiliary": True,
            "warning": "此資料為外部輔助資料，PDF 原文為主要依據",
            "records": records,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FinMind API 請求失敗: {e}")


@router.post("/{stock_id}/fetch-financials")
async def get_financial_statement(stock_id: str, period: str = Query(..., examples="2026Q1")):
    """
    從 FinMind 抓取財務報表主要科目。
    資料來源：FinMind / TWSE，僅作輔助參考。
    """
    try:
        records = fetch_financial_statement(stock_id, period)
        return {
            "stock_id": stock_id,
            "period": period,
            "data_source": "FinMind/TaiwanStockFinancialStatements",
            "is_auxiliary": True,
            "warning": "此資料為外部輔助資料，PDF 原文為主要依據",
            "total_items": len(records),
            "records": records,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FinMind API 請求失敗: {e}")


@router.get("/{stock_id}/crosscheck")
async def crosscheck(
    stock_id: str,
    period: str = Query(..., examples="2026Q1"),
    metric: str = Query(..., examples="revenue"),
    pdf_value: str = Query(..., examples="12345"),
):
    """
    將 PDF 摘要中的數字與外部資料做比對。
    只輸出 consistent / needs_review / not_comparable。
    不輸出投資判斷。

    metric 可選：revenue / gross_profit / net_income / eps
    """
    result = crosscheck_with_pdf(stock_id, period, metric, pdf_value)
    return result


@router.get("/{stock_id}/external-data")
async def list_external_data(
    stock_id: str,
    data_type: str | None = None,
):
    """列出已快取的外部資料記錄"""
    query = ExternalDataRecord.objects(stock_id=stock_id)
    if data_type:
        query = query.filter(data_type=data_type)

    records = query.order_by("-fetched_at").limit(50)
    return {
        "stock_id": stock_id,
        "is_auxiliary": True,
        "warning": "外部資料僅作輔助，PDF 原文為主要依據",
        "records": [
            {
                "record_id": r.record_id,
                "period": r.period,
                "data_type": r.data_type,
                "data_source": r.data_source,
                "fetched_at": str(r.fetched_at),
            }
            for r in records
        ],
    }
