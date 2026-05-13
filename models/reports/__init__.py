from mongoengine import (
    Document,
    StringField,
    DateTimeField,
    BooleanField,
    ListField,
    EmbeddedDocument,
    EmbeddedDocumentField,
    FloatField,
)
from datetime import datetime, timezone


class ClaimEvidence(EmbeddedDocument):
    """單條 evidence，必須可以回溯到原文頁碼"""
    document_id = StringField(required=True)
    page = StringField(required=True)       # 字串，可能是 "12" 或 "12-13"
    section = StringField(default="unknown")
    quoted_text = StringField(default="")


class AIClaim(EmbeddedDocument):
    """
    AI 產出的每一個觀察或結論。
    claim_level 決定 AI 確信程度；沒有 evidence 時強制降級為 insufficient_evidence。
    """
    claim_id = StringField(required=True)
    claim = StringField(required=True)
    claim_type = StringField(
        choices=[
            "financial_observation",
            "management_tone",
            "risk_factor",
            "accounting_note",
            "numeric_cross_check",
        ],
        default="financial_observation",
    )
    claim_level = StringField(
        choices=[
            "observed_fact",        # 直接引自 PDF 原文
            "derived_metric",       # 由原文數字計算
            "interpretation",       # AI 詮釋，有 evidence
            "hypothesis",           # AI 推測，evidence 不足
            "insufficient_evidence",# 無法從 PDF 中確認
        ],
        default="interpretation",
    )
    evidence = ListField(EmbeddedDocumentField(ClaimEvidence))
    confidence = StringField(
        choices=["high", "medium", "low"],
        default="medium",
    )
    requires_human_review = BooleanField(default=False)


class AIReport(Document):
    """單份 PDF 的 evidence-bound 財報摘要"""
    report_id = StringField(required=True, unique=True)
    document_id = StringField(required=True)
    stock_id = StringField(required=True)
    period = StringField(required=True)
    report_type = StringField(
        choices=["single_summary", "diff_report"],
        default="single_summary",
    )
    claims = ListField(EmbeddedDocumentField(AIClaim))
    evidence_status = StringField(
        choices=["complete", "partial", "insufficient"],
        default="partial",
    )
    investment_advice_detected = BooleanField(default=False)  # governance guard
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    meta = {
        "collection": "ai_reports",
        "indexes": ["document_id", "stock_id", "period"],
    }
