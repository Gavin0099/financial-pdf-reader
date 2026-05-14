"""
Pattern 2: 非常態項目影響 EPS
Triggered when: a tier_a non-recurring claim that contains a quantified amount exists
in key_financials or accounting_adjustments.
Requires an amount indicator keyword (%, 億, 萬, 元, etc.) — bare qualitative
disclosures without a number return insufficient_evidence instead of triggering.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter, PatternDefinition

# Require a quantified amount in the claim text.
# Without a number/unit the impact on EPS cannot be assessed → insufficient_evidence.
_AMOUNT_KEYWORDS = [
    "%", "％",
    "億", "萬", "百萬", "千萬",
    "元",
    "million", "billion",
]

PATTERN = PatternDefinition(
    pattern_id="non_recurring_eps",
    name_zh="非常態項目影響 EPS",
    observation_template=(
        "本期財報含 tier_a 非常態性項目且有量化金額揭露，報告 EPS 可能包含一次性收益或損失。"
        "建議計算正規化 EPS（剔除非常態項目後），以評估常態獲利能力。"
    ),
    inspect_description="tier_a 非常態項目含金額揭露（key_financials 或 accounting_adjustments）",
    required_filters=[
        ClaimPropertyFilter(
            section_keys=["key_financials", "accounting_adjustments"],
            materiality=["tier_a"],
            recurring=False,
            keywords=_AMOUNT_KEYWORDS,
            inspect_description="tier_a + recurring=False + 含金額揭露",
        ),
    ],
)
