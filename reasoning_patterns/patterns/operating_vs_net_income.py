"""
Pattern 1: 營業損益與稅後損益方向差異
Triggered when: tier_a non-recurring items exist in financials/adjustments
with keywords suggesting other income bridging a gap.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter, PatternDefinition

PATTERN = PatternDefinition(
    pattern_id="operating_vs_net_income",
    name_zh="營業損益與稅後損益方向差異",
    observation_template=(
        "本期財報含 tier_a 非常態業外項目，稅後損益與本業損益可能方向不一致。"
        "建議逐項確認業外收益（處分利益、匯兌、轉投資收益等）性質，"
        "評估本期獲利是否反映常態化本業能力。"
    ),
    inspect_description="tier_a 非常態業外項目（accounting_adjustments 或 key_financials）",
    required_filters=[
        ClaimPropertyFilter(
            section_keys=["accounting_adjustments", "key_financials"],
            materiality=["tier_a"],
            recurring=False,
            inspect_description="tier_a + recurring=False + adjustments/financials",
        ),
        ClaimPropertyFilter(
            section_keys=["accounting_adjustments", "key_financials"],
            keywords=[
                "業外", "其他收益", "其他收入", "處分利益", "投資利益",
                "non-operating", "other income", "disposal gain",
            ],
            inspect_description="業外收益相關 claim",
        ),
    ],
)
