"""
Unit tests for forward-looking implication guard — Phase 10D
All tests are pure Python: no MongoDB, no HTTP, no Claude API calls.

The guard auto-sets forward_looking=True + requires_human_review=True
when narrative claims contain forward-looking indicator words,
even if Claude's raw output had forward_looking=False.
"""
import pytest

from prompts import FORWARD_LOOKING_INDICATOR_PHRASES


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
    requires_human_review=False,
    evidence=None,
):
    return {
        "claim_id": claim_id,
        "claim": claim,
        "claim_level": claim_level,
        "source_type": source_type,
        "forward_looking": forward_looking,
        "requires_human_review": requires_human_review,
        "confidence": "medium",
        "section_key": "key_financials",
        "materiality": "tier_b",
        "evidence": evidence or [{"page": "4", "section": "s", "quoted_text": "evidence text"}],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: strategic_narrative with "預計" + Claude says forward_looking=False
#         → guard auto-sets True
# ─────────────────────────────────────────────────────────────────────────────

def test_strategic_narrative_yiji_auto_forward_looking():
    """strategic_narrative + '預計' with Claude forward_looking=False → auto-set True."""
    claims = _run_parse([_item(
        claim_id="fl1",
        claim="公司預計明年進入美國市場，擴大供應鏈布局",
        source_type="strategic_narrative",
        forward_looking=False,  # Claude failed to flag this
    )])
    assert claims[0].forward_looking is True
    assert claims[0].requires_human_review is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: management_expectation with "將" → auto-set forward_looking
# ─────────────────────────────────────────────────────────────────────────────

def test_management_expectation_jiang_auto_forward_looking():
    """management_expectation + '將' → forward_looking=True, requires_human_review=True."""
    claims = _run_parse([_item(
        claim_id="fl2",
        claim="管理層表示下半年毛利率將顯著回升",
        source_type="management_expectation",
        forward_looking=False,
    )])
    assert claims[0].forward_looking is True
    assert claims[0].requires_human_review is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: financial_evidence with "預計" → NOT auto-set (scope guard)
# ─────────────────────────────────────────────────────────────────────────────

def test_financial_evidence_not_auto_forward_looking():
    """
    financial_evidence with '預計' must NOT trigger guard.
    Scope is limited to narrative source types only.
    """
    claims = _run_parse([_item(
        claim_id="fl3",
        claim="本期折舊費用預計較上期增加 2.1 億元",
        source_type="financial_evidence",
        forward_looking=False,
    )])
    assert claims[0].forward_looking is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: strategic_narrative already forward_looking=True → stays True (no double-flip)
# ─────────────────────────────────────────────────────────────────────────────

def test_already_forward_looking_not_altered():
    """
    If Claude already marked forward_looking=True,
    guard must not flip it or produce side effects.
    """
    claims = _run_parse([_item(
        claim_id="fl4",
        claim="公司規劃明年完成美國廠認證",
        source_type="strategic_narrative",
        forward_looking=True,   # already correct from Claude
        requires_human_review=True,
    )])
    assert claims[0].forward_looking is True
    assert claims[0].requires_human_review is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: strategic_narrative without any indicator words → forward_looking stays False
# ─────────────────────────────────────────────────────────────────────────────

def test_strategic_narrative_no_indicator_not_flagged():
    """strategic_narrative with no forward-looking indicator words → forward_looking=False."""
    claims = _run_parse([_item(
        claim_id="fl5",
        claim="公司在台灣設有三座生產廠房，均已取得 ISO 認證",
        source_type="strategic_narrative",
        forward_looking=False,
    )])
    assert claims[0].forward_looking is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: management_expectation with "目標" → auto-detected
# ─────────────────────────────────────────────────────────────────────────────

def test_management_expectation_mubiao_auto_forward_looking():
    """management_expectation + '目標' → forward_looking=True."""
    claims = _run_parse([_item(
        claim_id="fl6",
        claim="管理層設定年度目標毛利率達 35%",
        source_type="management_expectation",
        forward_looking=False,
    )])
    assert claims[0].forward_looking is True
    assert claims[0].requires_human_review is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: operational_evidence with "規劃" → NOT auto-set (only narrative types)
# ─────────────────────────────────────────────────────────────────────────────

def test_operational_evidence_not_in_scope():
    """operational_evidence is not in scope of forward-looking guard."""
    claims = _run_parse([_item(
        claim_id="fl7",
        claim="公司規劃中的第四廠目前正在建設，預計 Q4 完工",
        source_type="operational_evidence",
        forward_looking=False,
    )])
    assert claims[0].forward_looking is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: FORWARD_LOOKING_INDICATOR_PHRASES sanity
# ─────────────────────────────────────────────────────────────────────────────

def test_forward_looking_phrases_not_empty():
    assert len(FORWARD_LOOKING_INDICATOR_PHRASES) >= 5


def test_forward_looking_phrases_are_strings():
    for p in FORWARD_LOOKING_INDICATOR_PHRASES:
        assert isinstance(p, str) and len(p) > 0
