"""
Pattern 3: 匯兌損益影響損益
Triggered when: claims mentioning FX/currency gains or losses exist in
risk_register or key_financials. Note: FX loss is NOT automatically one-time;
this pattern only flags its presence for human review.
"""
from reasoning_patterns.schemas import ClaimPropertyFilter, PatternDefinition

_FX_KEYWORDS = [
    "匯兌", "外幣", "匯率", "兌換損益", "外匯",
    "FX", "foreign currency", "exchange rate", "currency",
    "匯兌損失", "匯兌利益", "匯兌影響",
]

PATTERN = PatternDefinition(
    pattern_id="fx_driven_profit",
    name_zh="匯兌損益影響損益",
    observation_template=(
        "本期財報含匯兌損益相關揭露。匯兌損益屬非現金影響，且受匯率波動影響，"
        "需確認其對稅前損益的相對規模，並與業務現金流分開評估。"
        "注意：匯兌損益不應自動歸類為一次性項目，需視公司外幣曝險結構判斷。"
    ),
    inspect_description="匯兌損益關鍵字於 risk_register 或 key_financials",
    required_filters=[
        ClaimPropertyFilter(
            section_keys=["risk_register", "key_financials", "accounting_adjustments"],
            keywords=_FX_KEYWORDS,
            inspect_description="FX/匯兌相關 claim",
        ),
    ],
)
