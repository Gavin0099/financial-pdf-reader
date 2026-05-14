"""
Pattern 3: 匯兌損益影響損益
Triggered when: (1) a claim with FX/currency keywords exists in the relevant sections,
AND (2) at least one claim in those sections also contains a quantified amount.
Bare FX-risk disclosures without any numeric impact → insufficient_evidence.
Note: FX loss is NOT automatically one-time; this pattern only flags the presence
of a quantified FX impact for human review.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter, PatternDefinition

_FX_KEYWORDS = [
    "匯兌", "外幣", "匯率", "兌換損益", "外匯",
    "FX", "foreign currency", "exchange rate", "currency",
    "匯兌損失", "匯兌利益", "匯兌影響",
]

# Require a quantified amount so bare risk disclosures do not trigger.
# "元" is intentionally excluded: it matches "美元"/"歐元" (currency names), not amounts.
# Use compound units (億元, 萬元…) or standalone magnitude words (億, 萬…) instead.
_AMOUNT_KEYWORDS = [
    "%", "％",
    "億元", "萬元", "千萬元", "百萬元",
    "億", "萬", "百萬", "千萬",
    "million", "billion",
]

_FX_SECTIONS = ["risk_register", "key_financials", "accounting_adjustments"]

PATTERN = PatternDefinition(
    pattern_id="fx_driven_profit",
    name_zh="匯兌損益影響損益",
    observation_template=(
        "本期財報含量化匯兌損益揭露。匯兌損益屬非現金影響，且受匯率波動影響，"
        "需確認其對稅前損益的相對規模，並與業務現金流分開評估。"
        "注意：匯兌損益不應自動歸類為一次性項目，需視公司外幣曝險結構判斷。"
    ),
    inspect_description="匯兌損益關鍵字 + 量化金額，於 risk_register 或 key_financials",
    required_filters=[
        ClaimPropertyFilter(
            section_keys=_FX_SECTIONS,
            keywords=_FX_KEYWORDS,
            inspect_description="FX/匯兌相關 claim",
        ),
        ClaimPropertyFilter(
            section_keys=_FX_SECTIONS,
            keywords=_AMOUNT_KEYWORDS,
            inspect_description="含量化金額之 claim（%, 億, 萬, 元 等）",
        ),
    ],
)
