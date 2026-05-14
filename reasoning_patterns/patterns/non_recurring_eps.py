"""
Pattern 2: 非常態項目影響 EPS
Triggered when: any tier_a non-recurring claim exists in financials or adjustments.
This is the simplest pattern — any recurring=False tier_a item suggests EPS normalization is needed.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter, PatternDefinition

PATTERN = PatternDefinition(
    pattern_id="non_recurring_eps",
    name_zh="非常態項目影響 EPS",
    observation_template=(
        "本期財報含 tier_a 非常態性項目，報告 EPS 可能包含一次性收益或損失。"
        "建議計算正規化 EPS（剔除非常態項目後），以評估常態獲利能力。"
    ),
    inspect_description="tier_a 非常態項目（key_financials 或 accounting_adjustments）",
    required_filters=[
        ClaimPropertyFilter(
            section_keys=["key_financials", "accounting_adjustments"],
            materiality=["tier_a"],
            recurring=False,
            inspect_description="tier_a + recurring=False",
        ),
    ],
)
