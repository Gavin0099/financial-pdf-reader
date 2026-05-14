"""
Pattern 5: 短期債務/可轉債到期壓力
Triggered when: claims in liquidity/evidence_gaps sections mention debt maturity,
convertible bonds, put options, or current liabilities.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter, PatternDefinition

_DEBT_KEYWORDS = [
    "可轉換公司債", "可轉債", "convertible bond", "convertible note",
    "到期", "maturity", "due date",
    "賣回", "put option", "put back",
    "流動負債", "current liabilities", "current portion",
    "短期借款", "short-term debt", "short-term borrowing",
    "償還", "repayment", "refinancing",
]

PATTERN = PatternDefinition(
    pattern_id="debt_maturity_risk",
    name_zh="短期債務/可轉債到期壓力",
    observation_template=(
        "本期財報含流動性或證據缺口相關揭露，涉及債務到期、可轉債或短期負債，"
        "建議確認：近期到期債務規模、可轉債賣回條款行使可能性、"
        "及現金與可用信用額度是否足以覆蓋到期債務。"
    ),
    inspect_description="流動性/evidence_gaps 區段中含債務到期或可轉債相關 claim",
    required_filters=[
        ClaimPropertyFilter(
            section_keys=["liquidity", "evidence_gaps", "key_financials"],
            keywords=_DEBT_KEYWORDS,
            inspect_description="債務到期/可轉債/流動負債相關 claim",
        ),
    ],
)
