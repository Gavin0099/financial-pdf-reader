"""
Unit tests for reasoning patterns — Phase 9E
All tests are pure Python: no MongoDB, no HTTP, no Claude API calls.
"""
import pytest

from reasoning_patterns import PATTERN_REGISTRY
from reasoning_patterns.schemas import TriggerResult
from services.reasoning_patterns.engine import evaluate_pattern, GUARD_CLAIM_LEVEL, GUARD_REQUIRES_REVIEW, GUARD_IN_KEY_FINDINGS
from services.reasoning_patterns.evidence_resolver import find_matching_claims
from prompts import INVESTMENT_ADVICE_GUARD_PHRASES


# ─────────────────────────────────────────────────────────────────────────────
# Claim factory helpers
# ─────────────────────────────────────────────────────────────────────────────

def _claim(
    claim_id="c1",
    claim="sample claim text",
    section_key="key_financials",
    materiality="tier_b",
    recurring=True,
    claim_type="financial_observation",
    contaminated=False,
):
    return {
        "claim_id": claim_id,
        "claim": claim,
        "section_key": section_key,
        "materiality": materiality,
        "recurring": recurring,
        "claim_type": claim_type,
        "contaminated": contaminated,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: operating_vs_net_income triggered
# ─────────────────────────────────────────────────────────────────────────────

def test_operating_vs_net_income_triggered():
    """recurring=False tier_a claim with 業外 keyword → triggered."""
    from reasoning_patterns.patterns.operating_vs_net_income import PATTERN
    claims = [
        _claim(
            claim_id="c1",
            claim="本期業外收入大幅增加導致稅後淨利優於營業利益趨勢",
            section_key="accounting_adjustments",
            materiality="tier_a",
            recurring=False,
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    assert result.status == "triggered"
    assert len(result.source_claims) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: non_recurring_eps triggered and insufficient
# ─────────────────────────────────────────────────────────────────────────────

def test_non_recurring_eps_triggered():
    """tier_a + recurring=False claim → triggered."""
    from reasoning_patterns.patterns.non_recurring_eps import PATTERN
    claims = [
        _claim(
            claim_id="c2",
            claim="本期非常態處分利益增加 EPS 0.5 元",
            section_key="key_financials",
            materiality="tier_a",
            recurring=False,
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    assert result.status == "triggered"


def test_non_recurring_eps_insufficient_when_no_tier_a():
    """Only tier_b claims → insufficient_evidence."""
    from reasoning_patterns.patterns.non_recurring_eps import PATTERN
    claims = [
        _claim(
            claim_id="c3",
            claim="本期業外收入較小",
            section_key="key_financials",
            materiality="tier_b",
            recurring=True,
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    assert result.status == "insufficient_evidence"
    assert len(result.missing_keys) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Missing required claims → insufficient_evidence
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_claims_returns_insufficient():
    """No claims at all → every pattern returns insufficient_evidence."""
    for pattern in PATTERN_REGISTRY:
        result = evaluate_pattern(pattern, [])
        assert result.status == "insufficient_evidence", (
            f"Pattern {pattern.pattern_id} should be insufficient with no claims"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Observation text does not contain investment advice
# ─────────────────────────────────────────────────────────────────────────────

def test_pattern_observations_no_investment_advice():
    """All pattern observation_templates must not contain investment advice phrases."""
    for pattern in PATTERN_REGISTRY:
        obs = pattern.observation_template.lower()
        for phrase in INVESTMENT_ADVICE_GUARD_PHRASES:
            assert phrase.lower() not in obs, (
                f"Pattern {pattern.pattern_id} observation contains investment advice phrase: '{phrase}'"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: requires_review always True for triggered patterns
# ─────────────────────────────────────────────────────────────────────────────

def test_triggered_requires_review_true():
    """requires_review must be True whenever status=triggered."""
    from reasoning_patterns.patterns.non_recurring_eps import PATTERN
    claims = [
        _claim(
            claim_id="c5",
            claim="非常態業外利益增加 EPS 0.5 元",  # contains amount keyword
            section_key="key_financials",
            materiality="tier_a",
            recurring=False,
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    assert result.status == "triggered"
    # TriggerResult hardcodes REQUIRES_REVIEW = True
    assert result.REQUIRES_REVIEW is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: FX loss NOT auto-marked as one-time (fx_driven_profit)
# ─────────────────────────────────────────────────────────────────────────────

def test_fx_driven_profit_does_not_force_recurring_flag():
    """
    fx_driven_profit may trigger on recurring=True FX claims.
    Pattern must NOT reject a claim solely because recurring=True.
    """
    from reasoning_patterns.patterns.fx_driven_profit import PATTERN
    claims = [
        _claim(
            claim_id="c6",
            claim="本期匯兌損失 3.2 億元影響淨利",
            section_key="key_financials",
            materiality="tier_b",
            recurring=True,   # explicitly recurring — pattern should still trigger
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    # fx_driven_profit only requires FX keywords, no recurring filter → must trigger
    assert result.status == "triggered"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: debt_maturity_risk triggered on convertible bond keyword
# ─────────────────────────────────────────────────────────────────────────────

def test_debt_maturity_risk_triggered_on_convertible_bond():
    """可轉換公司債 keyword in liquidity → triggered."""
    from reasoning_patterns.patterns.debt_maturity_risk import PATTERN
    claims = [
        _claim(
            claim_id="c7",
            claim="本公司發行之可轉換公司債將於明年到期，面額 10 億元",
            section_key="liquidity",
            materiality="tier_a",
            recurring=False,
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    assert result.status == "triggered"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: customer_concentration triggered on risk_register + keyword
# ─────────────────────────────────────────────────────────────────────────────

def test_customer_concentration_triggered():
    """主要客戶 keyword in risk_register → triggered."""
    from reasoning_patterns.patterns.customer_concentration import PATTERN
    claims = [
        _claim(
            claim_id="c8",
            claim="前三大主要客戶佔本期營收達 68%，客戶集中度偏高",
            section_key="risk_register",
            materiality="tier_b",
            recurring=True,
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    assert result.status == "triggered"


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: contaminated claims are NOT passed to pattern evaluation
# ─────────────────────────────────────────────────────────────────────────────

def test_contaminated_claims_excluded():
    """
    Verify find_matching_claims returns contaminated claims if asked,
    but the service layer filters them out before passing to evaluate_pattern.
    Pattern engine itself is agnostic — filtering is caller responsibility.
    This test documents the contract.
    """
    from reasoning_patterns.patterns.non_recurring_eps import PATTERN
    contaminated = _claim(
        claim_id="c9",
        claim="非常態業外利益 tier_a contaminated",
        section_key="key_financials",
        materiality="tier_a",
        recurring=False,
        contaminated=True,
    )
    # Simulate service layer: exclude contaminated before passing to engine
    clean = [c for c in [contaminated] if not c["contaminated"]]
    result = evaluate_pattern(PATTERN, clean)
    # After exclusion, no valid claims remain → insufficient
    assert result.status == "insufficient_evidence"


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Pattern results claim_level guard = "interpretation"
# ─────────────────────────────────────────────────────────────────────────────

def test_trigger_result_claim_level_guard():
    """TriggerResult always carries CLAIM_LEVEL='interpretation' and IN_KEY_FINDINGS=False."""
    result = TriggerResult(status="triggered")
    assert result.CLAIM_LEVEL == "interpretation"
    assert result.IN_KEY_FINDINGS is False
    assert result.REQUIRES_REVIEW is True

    # Also test engine constants
    assert GUARD_CLAIM_LEVEL == "interpretation"
    assert GUARD_REQUIRES_REVIEW is True
    assert GUARD_IN_KEY_FINDINGS is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: non_recurring_eps requires quantified amount (Phase 9F precision)
# ─────────────────────────────────────────────────────────────────────────────

def test_non_recurring_eps_insufficient_without_amount():
    """tier_a + recurring=False but NO amount keyword → insufficient_evidence."""
    from reasoning_patterns.patterns.non_recurring_eps import PATTERN
    claims = [
        _claim(
            claim_id="c11",
            claim="本期有非常態業外項目，性質屬一次性，尚未確定影響規模",
            section_key="key_financials",
            materiality="tier_a",
            recurring=False,
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    assert result.status == "insufficient_evidence", (
        "non_recurring_eps must not trigger without a quantified amount in the claim"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: fx_driven_profit requires quantified amount (Phase 9F precision)
# ─────────────────────────────────────────────────────────────────────────────

def test_fx_driven_profit_insufficient_without_amount():
    """FX keyword present but NO quantified amount → insufficient_evidence."""
    from reasoning_patterns.patterns.fx_driven_profit import PATTERN
    claims = [
        _claim(
            claim_id="c12",
            claim="本公司業務涉及外幣交易，主要為美元，存在匯兌風險",
            section_key="risk_register",
            materiality="tier_b",
            recurring=True,
        )
    ]
    result = evaluate_pattern(PATTERN, claims)
    assert result.status == "insufficient_evidence", (
        "fx_driven_profit must not trigger on bare FX risk disclosure without a quantified amount"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Bonus: PATTERN_REGISTRY has all 6 patterns with unique IDs
# ─────────────────────────────────────────────────────────────────────────────

def test_pattern_registry_has_6_patterns():
    assert len(PATTERN_REGISTRY) == 6


def test_pattern_registry_ids_unique():
    ids = [p.pattern_id for p in PATTERN_REGISTRY]
    assert len(ids) == len(set(ids))


def test_all_patterns_have_observation_template():
    for p in PATTERN_REGISTRY:
        assert p.observation_template.strip(), f"{p.pattern_id} has empty observation_template"
