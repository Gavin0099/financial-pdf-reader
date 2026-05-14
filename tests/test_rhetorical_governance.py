"""
Unit tests for rhetorical risk classifier + weighted narrative density — Phase 10C
All tests are pure Python: no MongoDB, no HTTP, no Claude API calls.
"""
import pytest

from prompts import RHETORICAL_RISK_PHRASES


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _run_parse(items: list[dict], temporal_consistent: bool = True) -> list:
    from services.summarization import _parse_claims
    return _parse_claims({"claims": items}, document_id="doc-test",
                         temporal_consistent=temporal_consistent)


def _item(
    claim_id="c1",
    claim="test claim",
    claim_level="interpretation",
    source_type="financial_evidence",
    forward_looking=False,
    confidence="medium",
    requires_human_review=False,
    evidence=None,
):
    return {
        "claim_id": claim_id,
        "claim": claim,
        "claim_level": claim_level,
        "source_type": source_type,
        "forward_looking": forward_looking,
        "confidence": confidence,
        "requires_human_review": requires_human_review,
        "section_key": "key_financials",
        "materiality": "tier_b",
        "evidence": evidence or [{"page": "3", "section": "s", "quoted_text": "evidence"}],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: strategic_narrative with rhetorical phrase → flag True, term captured
# ─────────────────────────────────────────────────────────────────────────────

def test_strategic_narrative_with_rhetorical_phrase_flags():
    """strategic_narrative containing '明顯受惠' → rhetorical_risk_flag=True."""
    claims = _run_parse([_item(
        claim_id="r1",
        claim="公司明顯受惠於美國供應鏈重組，已形成核心競爭力",
        source_type="strategic_narrative",
        claim_level="interpretation",
    )])
    assert claims[0].rhetorical_risk_flag is True
    assert any(t in claims[0].rhetorical_risk_terms for t in ["明顯", "已形成", "核心競爭力"])


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: financial_evidence with same phrase → NOT flagged
# ─────────────────────────────────────────────────────────────────────────────

def test_financial_evidence_not_flagged_despite_phrase():
    """
    financial_evidence with '大幅增加' must NOT trigger rhetorical_risk_flag.
    Rhetorical scan only applies to strategic_narrative / management_expectation.
    """
    claims = _run_parse([_item(
        claim_id="r2",
        claim="本期營收大幅增加，達 15.3 億元（p.5）",
        source_type="financial_evidence",
        claim_level="observed_fact",
    )])
    assert claims[0].rhetorical_risk_flag is False
    assert claims[0].rhetorical_risk_terms == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: management_expectation with '可望' → flag True
# ─────────────────────────────────────────────────────────────────────────────

def test_management_expectation_with_keiwang_flags():
    """management_expectation with '可望' → rhetorical_risk_flag=True."""
    claims = _run_parse([_item(
        claim_id="r3",
        claim="管理層預計下半年可望顯著改善毛利率",
        source_type="management_expectation",
        claim_level="interpretation",
    )])
    assert claims[0].rhetorical_risk_flag is True
    assert "可望" in claims[0].rhetorical_risk_terms or "顯著" in claims[0].rhetorical_risk_terms


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: strategic_narrative without any rhetorical phrase → NOT flagged
# ─────────────────────────────────────────────────────────────────────────────

def test_strategic_narrative_without_phrase_not_flagged():
    """strategic_narrative with neutral language → rhetorical_risk_flag=False."""
    claims = _run_parse([_item(
        claim_id="r4",
        claim="公司在美國設有子公司，專注生物製劑委託生產業務",
        source_type="strategic_narrative",
        claim_level="interpretation",
    )])
    assert claims[0].rhetorical_risk_flag is False
    assert claims[0].rhetorical_risk_terms == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: weighted narrative density calculation
# ─────────────────────────────────────────────────────────────────────────────

def test_weighted_narrative_density_calculation():
    """
    2 narrative claims of 20 chars each, 2 financial claims of 5 chars each:
    narrative_text_len = 40, total_text_len = 50 → weighted_score = 0.8.
    """
    items = []
    for i in range(2):
        items.append(_item(
            claim_id=f"n{i}",
            claim="12345678901234567890",  # exactly 20 chars
            source_type="strategic_narrative",
            claim_level="interpretation",
        ))
    for i in range(2):
        items.append(_item(
            claim_id=f"f{i}",
            claim="12345",  # exactly 5 chars
            source_type="financial_evidence",
            claim_level="observed_fact",
        ))

    claims = _run_parse(items)
    clean = [c for c in claims if not c.contaminated and c.claim_level != "insufficient_evidence"]
    _narrative_types = {"strategic_narrative", "management_expectation"}
    narrative_text_len = sum(len(c.claim) for c in clean if c.source_type in _narrative_types)
    total_text_len = sum(len(c.claim) for c in clean)
    weighted_score = round(narrative_text_len / total_text_len, 2) if total_text_len else 0.0

    assert narrative_text_len == 40
    assert total_text_len == 50
    assert weighted_score == 0.8


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: count density and weighted density can diverge
# ─────────────────────────────────────────────────────────────────────────────

def test_count_vs_weighted_density_can_diverge():
    """
    1 long narrative claim (100 chars) vs 9 short financial claims (5 chars each):
    count density = 1/10 = 0.1 (low)
    weighted density = 100/145 ≈ 0.69 (high)
    Both can be calculated independently.
    """
    items = [_item(
        claim_id="big_n",
        claim="x" * 100,
        source_type="strategic_narrative",
        claim_level="interpretation",
    )]
    for i in range(9):
        items.append(_item(
            claim_id=f"sf{i}",
            claim="12345",
            source_type="financial_evidence",
            claim_level="observed_fact",
        ))

    claims = _run_parse(items)
    clean = [c for c in claims if not c.contaminated and c.claim_level != "insufficient_evidence"]
    _nt = {"strategic_narrative", "management_expectation"}
    count_density = round(sum(1 for c in clean if c.source_type in _nt) / len(clean), 2)
    weighted_density = round(
        sum(len(c.claim) for c in clean if c.source_type in _nt) /
        sum(len(c.claim) for c in clean), 2
    )

    assert count_density == 0.1
    assert weighted_density > 0.6, f"Expected weighted_density > 0.6, got {weighted_density}"
    # Key assertion: the two metrics diverge
    assert weighted_density > count_density


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: RHETORICAL_RISK_PHRASES list sanity
# ─────────────────────────────────────────────────────────────────────────────

def test_rhetorical_risk_phrases_not_empty():
    assert len(RHETORICAL_RISK_PHRASES) >= 5


def test_rhetorical_risk_phrases_are_strings():
    for phrase in RHETORICAL_RISK_PHRASES:
        assert isinstance(phrase, str) and len(phrase) > 0
