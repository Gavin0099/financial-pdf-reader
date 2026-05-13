from mongoengine import Document, StringField, DateTimeField, DictField, BooleanField
from datetime import datetime, timezone


class ExternalDataRecord(Document):
    """
    從外部資料源（FinMind / TWSE）取得的結構化台股資料。

    Governance 原則：
    - 外部資料只作為 PDF 分析的輔助基準
    - 必須標示 data_source，不得與 PDF 原文混淆
    - 不得直接覆蓋 PDF 中的事實
    """
    record_id = StringField(required=True, unique=True)
    stock_id = StringField(required=True)
    period = StringField(required=True)         # e.g. "2026Q1" 或 "2026-01"（月營收）
    data_type = StringField(
        required=True,
        choices=[
            "monthly_revenue",      # 月營收
            "financial_statement",  # 財務報表（損益表/資產負債表）
            "cash_flow",            # 現金流量表
        ],
    )
    data_source = StringField(required=True)    # e.g. "FinMind/TaiwanStockMonthRevenue"
    source_url = StringField(default="")
    payload = DictField()                       # 原始資料（保留完整欄位）
    fetched_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    # 防止與 PDF 原文混淆
    is_auxiliary = BooleanField(default=True)   # 永遠為 True，不得作為主要 evidence

    meta = {
        "collection": "external_data",
        "indexes": ["stock_id", "period", "data_type"],
    }
