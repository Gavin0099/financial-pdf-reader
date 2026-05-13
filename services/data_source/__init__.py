"""
Taiwan Data Source Service — Phase 6
--------------------------------------
從 FinMind API 抓取台股結構化資料，作為 PDF 分析的輔助基準。

資料來源：FinMind (https://finmindtrade.com)
  - 資料原始來源：TWSE / MOPS（公開政府資料）
  - 免費版：每小時 600 次請求

Governance 硬性規則：
  R1: 外部資料永遠標記 is_auxiliary=True
  R2: 外部資料不得覆蓋 PDF evidence
  R3: 每筆資料都標示 data_source 欄位
  R4: cross-check 只能輸出「一致 / 需確認 / 無法比較」，不輸出投資判斷
"""
import uuid
from datetime import datetime, date

import httpx

from config.config import FinMindConfig
from models.external import ExternalDataRecord

FINMIND_BASE = FinMindConfig.BASE_URL


def _build_params(dataset: str, stock_id: str, start_date: str, end_date: str) -> dict:
    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if FinMindConfig.TOKEN:
        params["token"] = FinMindConfig.TOKEN
    return params


def _period_to_date_range(period: str) -> tuple[str, str]:
    """
    把 period 字串（e.g. '2026Q1', '2025Q4'）轉成 FinMind 的日期範圍。
    月營收用當季三個月；財務報表用當季最後一個月。
    """
    year = int(period[:4])
    quarter = period[4:]
    q_map = {"Q1": (1, 3), "Q2": (4, 6), "Q3": (7, 9), "Q4": (10, 12)}
    if quarter not in q_map:
        raise ValueError(f"Invalid period format: {period}. Expected YYYYQ1~Q4")
    start_month, end_month = q_map[quarter]
    start = f"{year}-{start_month:02d}-01"
    # end of quarter
    end_day = 31 if end_month in (1, 3, 5, 7, 8, 10, 12) else 30
    end = f"{year}-{end_month:02d}-{end_day}"
    return start, end


def fetch_monthly_revenue(stock_id: str, period: str) -> list[dict]:
    """
    抓取月營收（TaiwanStockMonthRevenue）。
    回傳當季三個月資料，每筆存入 ExternalDataRecord。
    """
    start, end = _period_to_date_range(period)
    params = _build_params("TaiwanStockMonthRevenue", stock_id, start, end)

    with httpx.Client(timeout=15) as client:
        resp = client.get(FINMIND_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

    records = data.get("data", [])
    saved = []

    for row in records:
        month_str = str(row.get("date", ""))[:7].replace("-", "")  # YYYYMM
        rec = ExternalDataRecord(
            record_id=str(uuid.uuid4()),
            stock_id=stock_id,
            period=f"{month_str}",
            data_type="monthly_revenue",
            data_source="FinMind/TaiwanStockMonthRevenue",
            source_url="https://finmindtrade.com",
            payload=row,
            is_auxiliary=True,
        )
        rec.save()
        saved.append({
            "date": row.get("date"),
            "revenue": row.get("revenue"),
            "revenue_month": row.get("revenue_month"),
            "revenue_year": row.get("revenue_year"),
        })

    return saved


def fetch_financial_statement(stock_id: str, period: str) -> list[dict]:
    """
    抓取財務報表（TaiwanStockFinancialStatements）。
    包含損益表主要科目。
    """
    start, end = _period_to_date_range(period)
    params = _build_params("TaiwanStockFinancialStatements", stock_id, start, end)

    with httpx.Client(timeout=15) as client:
        resp = client.get(FINMIND_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

    records = data.get("data", [])
    saved = []

    for row in records:
        rec = ExternalDataRecord(
            record_id=str(uuid.uuid4()),
            stock_id=stock_id,
            period=period,
            data_type="financial_statement",
            data_source="FinMind/TaiwanStockFinancialStatements",
            source_url="https://finmindtrade.com",
            payload=row,
            is_auxiliary=True,
        )
        rec.save()
        saved.append({
            "date": row.get("date"),
            "type": row.get("type"),
            "value": row.get("value"),
            "origin_name": row.get("origin_name"),
        })

    return saved


def crosscheck_with_pdf(
    stock_id: str,
    period: str,
    metric: str,
    pdf_value: str,
) -> dict:
    """
    將外部資料與 PDF 摘要中的數字做比對。
    只輸出「consistent / needs_review / not_comparable」，不輸出投資判斷。

    metric: "revenue" | "gross_profit" | "net_income" | "eps"
    pdf_value: 從 PDF 中取得的數字字串
    """
    # 找最近的外部資料記錄
    records = ExternalDataRecord.objects(
        stock_id=stock_id,
        data_type="financial_statement",
    ).order_by("-fetched_at").limit(20)

    if not records:
        return {
            "verdict": "not_comparable",
            "reason": "尚未抓取外部財務資料，請先呼叫 /fetch-financials",
            "is_auxiliary": True,
            "data_source": "FinMind/TaiwanStockFinancialStatements",
        }

    # 嘗試在外部資料中找到對應科目
    metric_map = {
        "revenue": ["營業收入", "Revenue", "revenue"],
        "gross_profit": ["毛利", "GrossProfit", "gross_profit"],
        "net_income": ["本期淨利", "NetIncome", "net_income"],
        "eps": ["每股盈餘", "EPS", "eps"],
    }
    keywords = metric_map.get(metric, [metric])

    matches = []
    for rec in records:
        origin = str(rec.payload.get("origin_name", "")).lower()
        type_name = str(rec.payload.get("type", "")).lower()
        if any(k.lower() in origin or k.lower() in type_name for k in keywords):
            matches.append(rec)

    if not matches:
        return {
            "verdict": "not_comparable",
            "reason": f"外部資料中找不到對應科目：{metric}",
            "is_auxiliary": True,
            "data_source": "FinMind/TaiwanStockFinancialStatements",
        }

    # 取最新一筆比較
    ext_record = matches[0]
    ext_value = str(ext_record.payload.get("value", ""))

    # 簡單數字比對（只比對是否接近，不做精確財務計算）
    try:
        pdf_num = float(pdf_value.replace(",", "").replace("億", "").replace("元", ""))
        ext_num = float(ext_value.replace(",", "")) if ext_value else None
    except (ValueError, AttributeError):
        pdf_num = None
        ext_num = None

    if pdf_num is not None and ext_num is not None:
        diff_pct = abs(pdf_num - ext_num) / max(abs(ext_num), 1) * 100
        if diff_pct < 5:
            verdict = "consistent"
            reason = f"PDF 數字與外部資料差異 {diff_pct:.1f}%，在合理範圍內"
        else:
            verdict = "needs_review"
            reason = f"PDF 數字與外部資料差異 {diff_pct:.1f}%，建議人工確認單位或計算基礎"
    else:
        verdict = "needs_review"
        reason = "無法解析數字格式，請人工確認"

    return {
        "verdict": verdict,
        "reason": reason,
        "pdf_value": pdf_value,
        "external_value": ext_value,
        "external_date": ext_record.payload.get("date", ""),
        "is_auxiliary": True,
        "data_source": ext_record.data_source,
        "warning": "外部資料為輔助參考，PDF 原文為主要依據",
    }
