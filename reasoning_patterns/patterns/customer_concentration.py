"""
Pattern 6: 客戶集中度風險
Triggered when: claims in risk_register or key_financials mention customer
concentration, major customer dependency, or concentrated receivables.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter, PatternDefinition

_CONCENTRATION_KEYWORDS = [
    "客戶集中", "客戶集中度", "customer concentration",
    "主要客戶", "major customer", "key customer", "top customer",
    "應收帳款集中", "concentration of receivables",
    "單一客戶", "single customer",
    "依賴", "dependency", "reliance",
    "前五大", "前十大", "top 5", "top 10",
]

PATTERN = PatternDefinition(
    pattern_id="customer_concentration",
    name_zh="客戶集中度風險",
    observation_template=(
        "本期財報含客戶集中度相關揭露，建議確認：前幾大客戶佔營收比重、"
        "應收帳款集中情形、主要客戶訂單能見度，"
        "及單一客戶減少採購對整體營收之潛在影響。"
    ),
    inspect_description="risk_register/key_financials 中含客戶集中度相關 claim",
    required_filters=[
        ClaimPropertyFilter(
            section_keys=["risk_register", "key_financials", "accounting_adjustments"],
            keywords=_CONCENTRATION_KEYWORDS,
            inspect_description="客戶集中度/主要客戶/應收帳款集中相關 claim",
        ),
    ],
)
