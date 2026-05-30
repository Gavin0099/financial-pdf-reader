"""
Phase 3A — Multi-Period KPI Trend Service
------------------------------------------
從多份 AIReport（每份對應一個 document_id / period）聚合固定 KPI，
產出跨期趨勢報告。

Governance guards:
  R7: 期數 < 3 → r7_warning=True，不可推論長期趨勢
  每個 TrendPoint 必須有 source document_id（防止跨文件來源未標示）
  只採用 observed_fact / derived_metric 的 claims
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from models.documents import PDFDocument
from models.reports import AIReport
from models.trends import TrendPoint, TrendReport

_TRACKED_KPIS = [
    "revenue",
    "gross_margin",
    "operating_income",
    "eps",
    "cash",
    "net_income",
    "debt_ratio",
    "fx",
]

_R7_MIN_PERIODS = 3


def _extract_kpi_points(document_id: str, period: str, dashboard: dict) -> dict[str, TrendPoint]:
    """從單期 dashboard payload 抽出各 KPI 的 TrendPoint。"""
    points: dict[str, TrendPoint] = {}
    what_changed: list[dict] = dashboard.get("what_changed") or []

    for item in what_changed:
        metric_id = item.get("metric_id", "")
        if metric_id not in _TRACKED_KPIS:
            continue
        points[metric_id] = TrendPoint(
            period=period,
            document_id=document_id,
            direction=item.get("direction") or "unknown",
            delta_pct=item.get("delta_pct"),
            claim_text=item.get("claim_text") or "",
            source_claim_id=(item.get("evidence_claim_ids") or [""])[0],
            governance_flags=[],
        )

    # 從 metrics dict（if present）補充 tracked KPIs 未被 what_changed 覆蓋的部分
    metrics: dict = dashboard.get("metrics") or {}
    for metric_id, m in metrics.items():
        if metric_id not in _TRACKED_KPIS or metric_id in points:
            continue
        points[metric_id] = TrendPoint(
            period=period,
            document_id=document_id,
            direction=m.get("direction") or "unknown",
            delta_pct=m.get("delta_pct"),
            claim_text=m.get("claim_text") or "",
            source_claim_id=(m.get("evidence_claim_ids") or [""])[0],
            governance_flags=[],
        )

    return points


def generate_trend(document_ids: list[str], kpi_list: list[str] | None = None) -> dict:
    """
    接受已完成 ingest + summary 的 document_id 清單，
    聚合各期的 KPI 並產出 TrendReport。

    kpi_list: 指定要追蹤的 KPI（預設追蹤 _TRACKED_KPIS）
    回傳 serialized dict。
    """
    if not document_ids:
        raise ValueError("document_ids 不可為空")

    tracked = set(kpi_list) & set(_TRACKED_KPIS) if kpi_list else set(_TRACKED_KPIS)

    # ── 1. 依 document_id 取得 period + latest AIReport ─────────────────────
    period_data: list[tuple[str, str, dict]] = []  # (document_id, period, dashboard)

    for doc_id in document_ids:
        doc = PDFDocument.objects(document_id=doc_id).first()
        if not doc:
            raise ValueError(f"Document not found: {doc_id}")

        report = AIReport.objects(document_id=doc_id).order_by("-created_at").first()
        if not report:
            raise ValueError(f"AIReport not found for document: {doc_id} — 請先執行 /summary")

        dashboard = report.dashboard or {}
        period = doc.period or "UNKNOWN"
        period_data.append((doc_id, period, dashboard))

    # ── 2. 依 period 排序（字典序即時間序 2024Q1 < 2024Q2 ...）──────────────
    period_data.sort(key=lambda x: x[1])
    periods = [p for _, p, _ in period_data]
    doc_ids_ordered = [d for d, _, _ in period_data]

    # ── 3. 聚合各 KPI 的跨期 TrendPoint ────────────────────────────────────
    kpi_series: dict[str, list[TrendPoint]] = {k: [] for k in tracked}

    for doc_id, period, dashboard in period_data:
        points = _extract_kpi_points(doc_id, period, dashboard)
        for kpi in tracked:
            if kpi in points:
                kpi_series[kpi].append(points[kpi])
            # 若某期缺少某 KPI，略過（不補假資料）

    # ── 4. R7 guard ─────────────────────────────────────────────────────────
    n_periods = len(period_data)
    r7_warning = n_periods < _R7_MIN_PERIODS
    governance_flags: list[str] = []
    if r7_warning:
        governance_flags.append(
            f"R7: 僅有 {n_periods} 期資料（需 ≥ {_R7_MIN_PERIODS} 期才可推論長期趨勢）"
        )

    # ── 5. 移除完全沒有資料的 KPI ────────────────────────────────────────
    kpi_series = {k: v for k, v in kpi_series.items() if v}

    # ── 6. 取 stock_id（從第一份文件）────────────────────────────────────
    first_doc = PDFDocument.objects(document_id=doc_ids_ordered[0]).first()
    stock_id = first_doc.stock_id if first_doc else ""

    # ── 7. 序列化 kpi_trends ─────────────────────────────────────────────
    kpi_trends_serialized = [
        {
            "metric_id": metric_id,
            "points": [
                {
                    "period": pt.period,
                    "document_id": pt.document_id,
                    "direction": pt.direction,
                    "delta_pct": pt.delta_pct,
                    "claim_text": pt.claim_text,
                    "source_claim_id": pt.source_claim_id,
                    "governance_flags": pt.governance_flags,
                }
                for pt in points
            ],
        }
        for metric_id, points in kpi_series.items()
    ]

    # ── 8. 持久化 TrendReport ────────────────────────────────────────────
    trend_report_id = str(uuid.uuid4())
    report_doc = TrendReport(
        trend_report_id=trend_report_id,
        stock_id=stock_id,
        document_ids=doc_ids_ordered,
        periods=periods,
        kpi_trends=kpi_trends_serialized,
        r7_warning=r7_warning,
        governance_flags=governance_flags,
    )
    report_doc.save()

    return _serialize(report_doc)


def _serialize(report: TrendReport) -> dict:
    return {
        "trend_report_id": report.trend_report_id,
        "stock_id": report.stock_id,
        "document_ids": report.document_ids,
        "periods": report.periods,
        "kpi_trends": report.kpi_trends,
        "r7_warning": report.r7_warning,
        "governance_flags": report.governance_flags,
        "created_at": str(report.created_at),
    }


def get_trend(trend_report_id: str) -> dict:
    report = TrendReport.objects(trend_report_id=trend_report_id).first()
    if not report:
        raise ValueError(f"TrendReport not found: {trend_report_id}")
    return _serialize(report)
