"""
Pattern 4: 獲利趨勢與營收趨勢不一致
Triggered when: claims exist about revenue/gross margin AND tier_a non-recurring items
exist — suggesting the two trends may be diverging for non-operational reasons.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter, PatternDefinition

_REVENUE_KEYWORDS = [
    "營收", "營業收入", "revenue", "sales",
    "毛利", "毛利率", "gross margin", "gross profit",
    "費用率", "營業費用", "operating expense",
]

PATTERN = PatternDefinition(
    pattern_id="expense_ratio_offset",
    name_zh="獲利趨勢與營收趨勢不一致",
    observation_template=(
        "本期財報同時含營收/毛利率相關揭露與 tier_a 非常態項目，"
        "獲利趨勢與營收趨勢可能因業外或非常態因素出現分歧。"
        "建議分別確認：毛利率變化、費用率結構、及業外項目對淨利的貢獻比重。"
    ),
    inspect_description="同時有營收/費用相關 claim + tier_a 非常態項目",
    required_filters=[
        ClaimPropertyFilter(
            section_keys=["key_financials", "accounting_adjustments"],
            keywords=_REVENUE_KEYWORDS,
            inspect_description="營收/毛利/費用率相關 claim",
        ),
        ClaimPropertyFilter(
            section_keys=["key_financials", "accounting_adjustments"],
            materiality=["tier_a"],
            recurring=False,
            inspect_description="tier_a + recurring=False",
        ),
    ],
)
