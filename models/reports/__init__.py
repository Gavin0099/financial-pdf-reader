from mongoengine import (
    Document,
    StringField,
    DateTimeField,
    BooleanField,
    ListField,
    EmbeddedDocument,
    EmbeddedDocumentField,
    FloatField,
    DictField,
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

    Hierarchy:
    - claim_level:  observed_fact > derived_metric > interpretation > hypothesis > insufficient_evidence
    - materiality:  tier_a (核心) > tier_b (輔助) > tier_c (背景)
    - section_key:  觀察所屬的報告章節
    - contaminated: 若時間軸不一致，derived/interpretation/hypothesis 標記為 contaminated
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
            "observed_fact",         # 直接引自 PDF 原文
            "derived_metric",        # 由原文數字計算（deterministic transform）
            "interpretation",        # AI 詮釋，有 evidence 支撐
            "hypothesis",            # AI 推測，evidence 不足
            "insufficient_evidence", # 無法從 PDF 中確認
        ],
        default="interpretation",
    )
    materiality = StringField(
        choices=["tier_a", "tier_b", "tier_c"],
        default="tier_b",
    )
    section_key = StringField(
        choices=[
            "key_financials",        # 營收、毛利、EPS 等核心財務
            "accounting_adjustments",# 一次性項目、會計調整
            "liquidity",             # 現金流、流動性、負債
            "risk_register",         # 風險因素
            "evidence_gaps",         # 無法確認的項目
        ],
        default="key_financials",
    )
    recurring = BooleanField(default=True)   # False = 一次性、非常態項目
    contaminated = BooleanField(default=False)  # 時間軸不一致時標記
    source_type = StringField(
        choices=[
            "financial_evidence",      # 財報數字 / 報表附注
            "operational_evidence",    # 業務運營具體事實（廠房、產能、認證）
            "strategic_narrative",     # 管理層/公司戰略說法（不得為 observed_fact）
            "management_expectation",  # 明確展望/指引（不得為 observed_fact，confidence≤medium）
        ],
        default="financial_evidence",
    )
    forward_looking = BooleanField(default=False)  # True = 描述未來預期/計畫（自動 requires_human_review）
    rhetorical_risk_flag = BooleanField(default=False)   # strategic/management claims 含高確信語氣詞
    rhetorical_risk_terms = ListField(StringField())     # 命中的語氣詞列表
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
    current_summary = StringField(default="")
    previous_summary = StringField(default="")
    evidence = EmbeddedDocumentField(DiffEvidence)
    requires_human_review = BooleanField(default=True)
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
    # Temporal validation layer
    temporal_consistent = BooleanField(default=True)
    temporal_note = StringField(default="")   # mismatch 描述
    # Narrative synthesis
    executive_summary = StringField(default="")
    # Narrative density governance
    narrative_density_score = FloatField(default=0.0)            # 0.0–1.0：claim-count 比例
    narrative_density_weighted_score = FloatField(default=0.0)   # 0.0–1.0：text-length 加權比例
    narrative_flag = BooleanField(default=False)                  # True when score > 0.6
    # Claims
    claims = ListField(EmbeddedDocumentField(AIClaim))
    evidence_status = StringField(
        choices=["complete", "partial", "insufficient"],
        default="partial",
    )
    investment_advice_detected = BooleanField(default=False)
    created_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    meta = {
        "collection": "ai_reports",
        "indexes": ["document_id", "stock_id", "period"],
    }
