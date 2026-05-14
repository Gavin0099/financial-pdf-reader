from mongoengine import (
    Document,
    EmbeddedDocument,
    StringField,
    ListField,
    EmbeddedDocumentField,
    IntField,
    DateTimeField,
)
from datetime import datetime, timezone

DISCLOSURE_REGISTRY = [
    ("related_party_transactions",    "關係人交易"),
    ("commitments_and_contingencies", "承諾事項與或有負債"),
    ("subsequent_events",             "後續事項"),
    ("business_combination",          "企業合併"),
    ("major_customers",               "主要客戶集中度"),
    ("segment_information",           "部門資訊"),
    ("financial_risk_fx",             "外幣匯率風險"),
    ("financial_risk_credit",         "信用風險"),
    ("financial_risk_liquidity",      "流動性風險"),
    ("key_accounting_estimates",      "關鍵會計估計"),
    ("inventory_valuation",           "存貨評價"),
    ("income_tax",                    "所得稅"),
    ("convertible_bonds",             "可轉換公司債"),
    ("dividends",                     "股利分配"),
]

STATUS_CHOICES = ["found", "found_incomplete", "not_found", "ambiguous", "not_applicable"]


class DisclosureCoverageItem(EmbeddedDocument):
    """單項法定揭露事項的稽核結果"""
    key = StringField(required=True)
    label_zh = StringField(required=True)
    status = StringField(choices=STATUS_CHOICES, default="ambiguous")
    evidence_pages = ListField(StringField())   # 有找到時的頁碼
    note = StringField(default="")             # 15 字以內，說明判斷依據


class DisclosureCoverageReport(Document):
    """財報 14 項法定揭露完整性稽核報告"""
    coverage_id = StringField(required=True, unique=True)
    document_id = StringField(required=True)
    stock_id = StringField(required=True)
    period = StringField(required=True)
    items = ListField(EmbeddedDocumentField(DisclosureCoverageItem))
    found_count = IntField(default=0)
    found_incomplete_count = IntField(default=0)
    not_found_count = IntField(default=0)
    not_applicable_count = IntField(default=0)
    total_count = IntField(default=14)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    meta = {
        "collection": "disclosure_coverage_reports",
        "indexes": ["document_id", "stock_id"],
    }
