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


class DiffEvidence(EmbeddedDocument):
    """Diff item 的來源，可能只有一邊"""
    current_document_id = StringField(default="")
    current_page = StringField(default="")
    current_quoted = StringField(default="")
    previous_document_id = StringField(default="")
    previous_page = StringField(default="")
    previous_quoted = StringField(default="")
    presence = StringField(
        choices=["both", "only_in_current", "only_in_previous"],
        default="both",
    )


class DiffItem(EmbeddedDocument):
    """兩份財報之間的一個差異點"""
    diff_id = StringField(required=True)
    section = StringField(required=True)
    diff_type = StringField(
        choices=[
            "new_language",        # 本季新增的說法
            "removed_language",    # 上季有、本季消失
            "tone_shift",          # 語氣變化（不等於財務惡化）
            "numeric_change",      # 數字變動候選
            "new_risk",            # 新出現的風險描述
            "removed_risk",        # 消失的風險描述
        ],
        required=True,
    )
    description = StringField(required=True)
    current_summary = StringField(default="")   # 本季該段摘要
    previous_summary = StringField(default="")  # 上季該段摘要
    evidence = EmbeddedDocumentField(DiffEvidence)
    requires_human_review = BooleanField(default=True)
    # Governance: 語氣變化不等於財務惡化
    tone_only = BooleanField(default=False)


class DiffReport(Document):
    """兩份財報的差異報告"""
    diff_report_id = StringField(required=True, unique=True)
    current_document_id = StringField(required=True)
    previous_document_id = StringField(required=True)
    stock_id = StringField(required=True)
    current_period = StringField(required=True)
    previous_period = StringField(required=True)
    items = ListField(EmbeddedDocumentField(DiffItem))
    sections_compared = ListField(StringField())
    sections_only_current = ListField(StringField())
    sections_only_previous = ListField(StringField())
    requires_human_review = BooleanField(default=True)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    meta = {
        "collection": "diff_reports",
        "indexes": ["current_document_id", "previous_document_id", "stock_id"],
    }


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
