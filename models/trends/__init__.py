from mongoengine import (
    Document,
    EmbeddedDocument,
    StringField,
    FloatField,
    BooleanField,
    ListField,
    EmbeddedDocumentField,
    DateTimeField,
)
from datetime import datetime, timezone


class TrendPoint(EmbeddedDocument):
    """單一期別、單一 KPI 的觀測點"""
    period = StringField(required=True)           # e.g. "2025Q3"
    document_id = StringField(required=True)
    direction = StringField(choices=["up", "down", "flat", "unknown"], default="unknown")
    delta_pct = FloatField(default=None)          # 相對上期變化 %
    claim_text = StringField(default="")
    source_claim_id = StringField(default="")
    governance_flags = ListField(StringField(), default=list)


class TrendReport(Document):
    """跨期 KPI 趨勢報告"""
    meta = {"collection": "trend_reports"}

    trend_report_id = StringField(required=True, unique=True)
    stock_id = StringField(default="")
    document_ids = ListField(StringField())        # 輸入的 document_id 清單（按期別排序）
    periods = ListField(StringField())             # 對應的 period 清單
    # kpi_trends: { metric_id: [TrendPoint, ...] }
    # 因 mongoengine 不支援 nested DictField + EmbeddedDocument，改用 ListField 存 dict
    kpi_trends = ListField()                       # list of { metric_id, points: [TrendPoint] }
    r7_warning = BooleanField(default=False)       # True = 期數 < 3，不足以推論長期趨勢
    governance_flags = ListField(StringField(), default=list)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
