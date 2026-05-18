"""
Unit tests for quotation / attribution prefix layer — Phase 10E
All tests are pure Python: no MongoDB, no HTTP, no Claude API calls.

The quotation layer ensures:
1. strategic_narrative claims get "公司宣稱：" prefix
2. management_expectation claims get "管理層表示：" prefix
3. financial_evidence / operational_evidence get no prefix (empty string)
4. Prefix is stable regardless of other governance rules applied to the same claim
5. Combined governance: source type downgrade + correct prefix
"""
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_parse(items: list[dict], temporal_consistent: bool = True) -> list:
    from services.summarization import _parse_claims
    return _parse_claims({"claims": items}, document_id="doc-test",
                         temporal_consistent=temporal_consistent)


def _item(
    claim_id="c1",
    claim="test claim",
    claim_level="observed_fact",
    source_type="financial_evidence",
    confidence="medium",
    evidence=None,
    forward_looking=False,
    requires_human_review=False,
):
    return {
        "claim_id": claim_id,
        "claim": claim,
        "claim_level": claim_level,
        "source_type": source_type,
        "confidence": confidence,
        "forward_looking": forward_looking,
        "requires_human_review": requires_human_review,
        "section_key": "key_financials",
        "materiality": "tier_b",
        "evidence": evidence or [{"page": "5", "section": "s", "quoted_text": "財報來源文字"}],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: strategic_narrative → attribution_prefix = "公司宣稱："
# ─────────────────────────────────────────────────────────────────────────────

def test_strategic_narrative_gets_prefix():
    """strategic_narrative claims must receive '公司宣稱：' prefix."""
    claims = _run_parse([_item(
        claim_id="q1",
        claim="公司在東南亞建立完整供應鏈布局",
        source_type="strategic_narrative",
        claim_level="interpretation",
    )])
    assert claims[0].attribution_prefix == "公司宣稱："


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: management_expectation → attribution_prefix = "管理層表示："
# ─────────────────────────────────────────────────────────────────────────────

def test_management_expectation_gets_prefix():
    """management_expectation claims must receive '管理層表示：' prefix."""
    claims = _run_parse([_item(
        claim_id="q2",
        claim="管理層預計下半年毛利率將回升至 35%",
        source_type="management_expectation",
        claim_level="interpretation",
    )])
    assert claims[0].attribution_prefix == "管理層表示："


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: financial_evidence → no prefix (empty string)
# ─────────────────────────────────────────────────────────────────────────────

def test_financial_evidence_no_prefix():
    """financial_evidence claims must NOT receive any attribution prefix."""
    claims = _run_parse([_item(
        claim_id="q3",
        claim="本期毛利率為 32.5%，較上期下降 3.2 pp",
        source_type="financial_evidence",
        claim_level="observed_fact",
    )])
    assert claims[0].attribution_prefix == ""


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: operational_evidence → no prefix
# ─────────────────────────────────────────────────────────────────────────────

def test_operational_evidence_no_prefix():
    """operational_evidence claims must NOT receive any attribution prefix."""
    claims = _run_parse([_item(
        claim_id="q4",
        claim="本期出貨量達 120 萬片，較上期增加 8%",
        source_type="operational_evidence",
        claim_level="observed_fact",
    )])
    assert claims[0].attribution_prefix == ""


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: strategic_narrative + observed_fact → downgraded to interpretation,
#          but prefix is still "公司宣稱："
# ─────────────────────────────────────────────────────────────────────────────

def test_strategic_narrative_downgraded_keeps_prefix():
    """
    strategic_narrative with claim_level=observed_fact is governance-downgraded
    to interpretation, but attribution_prefix must still be "公司宣稱：".
    """
    claims = _run_parse([_item(
        claim_id="q5",
        claim="公司宣稱已達到市場領先地位",
        source_type="strategic_narrative",
        claim_level="observed_fact",  # governance will downgrade this
    )])
    assert claims[0].claim_level == "interpretation", "Should be downgraded by governance"
    assert claims[0].attribution_prefix == "公司宣稱："


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: management_expectation + confidence=high → capped to medium,
#          and prefix is still "管理層表示："
# ─────────────────────────────────────────────────────────────────────────────

def test_management_expectation_confidence_capped_keeps_prefix():
    """
    management_expectation with confidence=high is governance-capped to medium,
    but attribution_prefix must still be "管理層表示：".
    """
    claims = _run_parse([_item(
        claim_id="q6",
        claim="管理層對明年獲利前景充滿信心",
        source_type="management_expectation",
        claim_level="interpretation",
        confidence="high",  # governance will cap to medium
    )])
    assert claims[0].confidence == "medium", "Confidence should be capped by governance"
    assert claims[0].attribution_prefix == "管理層表示："


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: prefix is source_type-based, not evidence-based
#          strategic_narrative with evidence still gets prefix
# ─────────────────────────────────────────────────────────────────────────────

def test_prefix_stable_with_evidence():
    """
    Attribution prefix is assigned based on source_type, not evidence presence.
    strategic_narrative with valid evidence still gets "公司宣稱：".
    """
    claims = _run_parse([_item(
        claim_id="q7",
        claim="公司表示台灣廠區產能利用率達 95%",
        source_type="strategic_narrative",
        claim_level="interpretation",
        evidence=[{"page": "12", "section": "production", "quoted_text": "產能利用率 95%"}],
    )])
    assert claims[0].attribution_prefix == "公司宣稱："
    assert len(claims[0].evidence) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: batch — each claim gets correct prefix based on its own source_type
# ─────────────────────────────────────────────────────────────────────────────

def test_multiple_source_types_correct_prefixes():
    """Batch: each claim gets the correct prefix based on its own source_type."""
    items = [
        _item("m1", "毛利率 32%，較上期下降 3 pp", "observed_fact", "financial_evidence"),
        _item("m2", "公司主導高端市場，具備差異化優勢", "interpretation", "strategic_narrative"),
        _item("m3", "管理層目標下季回到 35% 毛利率", "interpretation", "management_expectation"),
        _item("m4", "本季出貨量 120 萬片，年增 8%", "observed_fact", "operational_evidence"),
    ]
    claims = _run_parse(items)
    prefixes = {c.claim_id: c.attribution_prefix for c in claims}
    assert prefixes["m1"] == ""
    assert prefixes["m2"] == "公司宣稱："
    assert prefixes["m3"] == "管理層表示："
    assert prefixes["m4"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: all narrative source types have non-empty prefix
# ─────────────────────────────────────────────────────────────────────────────

def test_all_narrative_types_have_nonempty_prefix():
    """
    Both narrative source types (strategic_narrative, management_expectation)
    must produce a non-empty attribution_prefix.
    """
    narrative_types = ["strategic_narrative", "management_expectation"]
    for st in narrative_types:
        claims = _run_parse([_item("x", "test claim", "interpretation", st)])
        assert claims[0].attribution_prefix != "", \
            f"{st} should produce a non-empty attribution_prefix"
