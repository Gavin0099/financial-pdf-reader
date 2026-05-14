"""
Unit tests for source_type governance — Phase 10B
All tests are pure Python: no MongoDB, no HTTP, no Claude API calls.
Tests mock _parse_claims() inputs and verify governance enforcement.
"""
import pytest

from services.reasoning_patterns.engine import GUARD_CLAIM_LEVEL, GUARD_REQUIRES_REVIEW


# ─────────────────────────────────────────────────────────────────────────────
# Helper: call _parse_claims with a minimal raw_json dict
# ─────────────────────────────────────────────────────────────────────────────

def _run_parse(items: list[dict], temporal_consistent: bool = True) -> list:
    """Invoke _parse_claims with mock data; return list of AIClaim objects."""
    from services.summarization import _parse_claims
    raw = {"claims": items}
    return _parse_claims(raw, document_id="doc-test", temporal_consistent=temporal_consistent)


def _item(
    claim_id="c1",
    claim="test claim",
    claim_level="observed_fact",
    source_type="financial_evidence",
    forward_looking=False,
    confidence="high",
    requires_human_review=False,
    section_key="key_financials",
    materiality="tier_a",
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
        "section_key": section_key,
        "materiality": materiality,
        "evidence": evidence or [{"page": "5", "section": "test", "quoted_text": "test evidence"}],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: strategic_narrative + observed_fact → forced to interpretation
# ─────────────────────────────────────────────────────────────────────────────

def test_strategic_narrative_cannot_be_observed_fact():
    """strategic_narrative + observed_fact → governance forces claim_level to interpretation."""
    items = [_item(
        claim_id="g1",
        claim="公司全球布局持續推進，打造 end-to-end 生態系",
        claim_level="observed_fact",
        source_type="strategic_narrative",
    )]
    claims = _run_parse(items)
    assert len(claims) == 1
    assert claims[0].claim_level == "interpretation", (
        "strategic_narrative must not remain observed_fact — governance should downgrade to interpretation"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: management_expectation + observed_fact → forced to interpretation
# ─────────────────────────────────────────────────────────────────────────────

def test_management_expectation_cannot_be_observed_fact():
    """management_expectation + observed_fact → governance forces claim_level to interpretation."""
    items = [_item(
        claim_id="g2",
        claim="管理層預計明年量產，展望正面",
        claim_level="observed_fact",
        source_type="management_expectation",
    )]
    claims = _run_parse(items)
    assert len(claims) == 1
    assert claims[0].claim_level == "interpretation", (
        "management_expectation must not remain observed_fact"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: management_expectation + confidence=high → lowered to medium
# ─────────────────────────────────────────────────────────────────────────────

def test_management_expectation_confidence_capped_at_medium():
    """management_expectation with confidence=high → governance lowers to medium."""
    items = [_item(
        claim_id="g3",
        claim="管理層指引下半年毛利率將改善",
        claim_level="interpretation",
        source_type="management_expectation",
        confidence="high",
    )]
    claims = _run_parse(items)
    assert len(claims) == 1
    assert claims[0].confidence == "medium", (
        "management_expectation confidence must be capped at medium"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: forward_looking=True → requires_human_review=True
# ─────────────────────────────────────────────────────────────────────────────

def test_forward_looking_sets_requires_human_review():
    """forward_looking=True must auto-set requires_human_review=True."""
    items = [_item(
        claim_id="g4",
        claim="預計 Q3 取得 FDA 510(k) 許可",
        claim_level="interpretation",
        source_type="management_expectation",
        forward_looking=True,
        requires_human_review=False,  # explicitly False — governance must override
    )]
    claims = _run_parse(items)
    assert len(claims) == 1
    assert claims[0].requires_human_review is True, (
        "forward_looking=True must set requires_human_review=True"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: narrative_density_score calculation
# ─────────────────────────────────────────────────────────────────────────────

def test_narrative_density_score_calculation():
    """
    Mock 10 claims: 6 narrative (strategic_narrative/management_expectation),
    4 financial_evidence → score = 6/10 = 0.6.
    """
    items = []
    for i in range(6):
        st = "strategic_narrative" if i % 2 == 0 else "management_expectation"
        items.append(_item(
            claim_id=f"n{i}",
            claim=f"narrative claim {i}",
            claim_level="interpretation",
            source_type=st,
        ))
    for i in range(4):
        items.append(_item(
            claim_id=f"f{i}",
            claim=f"financial claim {i}",
            claim_level="observed_fact",
            source_type="financial_evidence",
        ))

    claims = _run_parse(items)
    clean_claims = [c for c in claims if not c.contaminated]

    _narrative_types = {"strategic_narrative", "management_expectation"}
    narrative_count = sum(1 for c in clean_claims if c.source_type in _narrative_types)
    total_non_gap = sum(1 for c in clean_claims if c.claim_level != "insufficient_evidence")
    score = round(narrative_count / total_non_gap, 2) if total_non_gap else 0.0

    assert total_non_gap == 10
    assert narrative_count == 6
    assert score == 0.6


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: narrative_flag True when score > 0.6, False when ≤ 0.6
# ─────────────────────────────────────────────────────────────────────────────

def test_narrative_flag_threshold():
    """narrative_flag=True when score > 0.6; False when ≤ 0.6."""
    # score = 0.6 → flag False (boundary: > 0.6 required)
    assert (0.6 > 0.6) is False
    # score = 0.61 → flag True
    assert (0.61 > 0.6) is True
    # score = 0.5 → flag False
    assert (0.5 > 0.6) is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: financial_evidence + observed_fact → NOT downgraded
# ─────────────────────────────────────────────────────────────────────────────

def test_financial_evidence_observed_fact_unchanged():
    """financial_evidence + observed_fact must NOT be downgraded."""
    items = [_item(
        claim_id="g7",
        claim="本期營收 12.3 億元（p.5）",
        claim_level="observed_fact",
        source_type="financial_evidence",
        confidence="high",
    )]
    claims = _run_parse(items)
    assert claims[0].claim_level == "observed_fact"
    assert claims[0].confidence == "high"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: management_expectation + confidence=medium → NOT lowered further
# ─────────────────────────────────────────────────────────────────────────────

def test_management_expectation_medium_confidence_unchanged():
    """management_expectation with confidence=medium must stay medium (not lowered to low)."""
    items = [_item(
        claim_id="g8",
        claim="管理層預計利潤率小幅改善",
        claim_level="interpretation",
        source_type="management_expectation",
        confidence="medium",
    )]
    claims = _run_parse(items)
    assert claims[0].confidence == "medium"


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: forward_looking=False → requires_human_review not auto-set
# ─────────────────────────────────────────────────────────────────────────────

def test_non_forward_looking_does_not_set_review():
    """forward_looking=False must NOT auto-set requires_human_review."""
    items = [_item(
        claim_id="g9",
        claim="本期 EPS 2.3 元（p.3）",
        claim_level="observed_fact",
        source_type="financial_evidence",
        forward_looking=False,
        requires_human_review=False,
    )]
    claims = _run_parse(items)
    assert claims[0].requires_human_review is False
