"""
Unit tests for core/governance.py — R1-R7 rules + GovernanceAuditResult

All tests are pure Python: no MongoDB, no HTTP, no external services.
"""
import pytest
from core.governance import (
    GovernanceViolation,
    GovernanceAuditResult,
    audit_claims,
    check_r1,
    check_r2,
    check_r3,
    check_r4_report,
    check_r4_claim,
    check_r5,
    check_r7_claim,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ev(doc_id="doc-1", page="5", quoted="營收為 100 億"):
    return {"document_id": doc_id, "page": page, "section": "營收", "quoted_text": quoted}


def _claim(
    claim_id="c1",
    claim="本季營收成長",
    claim_level="interpretation",
    evidence=None,
):
    return {
        "claim_id": claim_id,
        "claim": claim,
        "claim_level": claim_level,
        "claim_type": "financial_observation",
        "evidence": evidence if evidence is not None else [_ev()],
    }


# ─────────────────────────────────────────────────────────────────────────────
# R1: claim 必須有 evidence
# ─────────────────────────────────────────────────────────────────────────────

class TestR1:
    def test_pass_with_evidence(self):
        assert check_r1("c1", [_ev()]) is None

    def test_fail_empty_evidence(self):
        v = check_r1("c1", [])
        assert v is not None
        assert v.rule == "R1"
        assert v.severity == "error"
        assert v.claim_id == "c1"

    def test_fail_none_evidence(self):
        v = check_r1("c1", None)
        assert v is not None
        assert v.rule == "R1"


# ─────────────────────────────────────────────────────────────────────────────
# R2: derived_metric 必須有 quoted_text
# ─────────────────────────────────────────────────────────────────────────────

class TestR2:
    def test_skip_non_derived_metric(self):
        # R2 只對 derived_metric 觸發
        assert check_r2("c1", "interpretation", [_ev(quoted="")]) is None
        assert check_r2("c1", "observed_fact", [_ev(quoted="")]) is None

    def test_pass_derived_metric_with_quoted(self):
        ev = _ev(quoted="毛利率 45.2%")
        assert check_r2("c1", "derived_metric", [ev]) is None

    def test_fail_derived_metric_empty_quoted(self):
        ev = _ev(quoted="")
        v = check_r2("c1", "derived_metric", [ev])
        assert v is not None
        assert v.rule == "R2"
        assert v.severity == "error"

    def test_fail_derived_metric_whitespace_only_quoted(self):
        ev = _ev(quoted="   ")
        v = check_r2("c1", "derived_metric", [ev])
        assert v is not None
        assert v.rule == "R2"

    def test_pass_derived_metric_any_evidence_has_quoted(self):
        # 多條 evidence，只要有一條有 quoted_text 就通過
        evs = [_ev(quoted=""), _ev(quoted="EPS 3.5 元")]
        assert check_r2("c1", "derived_metric", evs) is None


# ─────────────────────────────────────────────────────────────────────────────
# R3: 無 evidence 時 claim_level 必須是 hypothesis 或 insufficient_evidence
# ─────────────────────────────────────────────────────────────────────────────

class TestR3:
    def test_skip_when_has_evidence(self):
        # 有 evidence → R3 不觸發
        assert check_r3("c1", "interpretation", [_ev()]) is None

    def test_pass_hypothesis_no_evidence(self):
        assert check_r3("c1", "hypothesis", []) is None

    def test_pass_insufficient_evidence_no_evidence(self):
        assert check_r3("c1", "insufficient_evidence", []) is None

    def test_fail_interpretation_no_evidence(self):
        v = check_r3("c1", "interpretation", [])
        assert v is not None
        assert v.rule == "R3"
        assert v.auto_fixed is True  # summarization 已自動修正

    def test_fail_observed_fact_no_evidence(self):
        v = check_r3("c1", "observed_fact", [])
        assert v is not None
        assert v.rule == "R3"

    def test_fail_derived_metric_no_evidence(self):
        v = check_r3("c1", "derived_metric", [])
        assert v is not None
        assert v.rule == "R3"


# ─────────────────────────────────────────────────────────────────────────────
# R4: 不允許投資建議
# ─────────────────────────────────────────────────────────────────────────────

class TestR4:
    def test_report_pass_no_advice(self):
        assert check_r4_report(False) is None

    def test_report_fail_advice_detected(self):
        v = check_r4_report(True)
        assert v is not None
        assert v.rule == "R4"
        assert v.severity == "error"
        assert v.claim_id is None  # report-level，沒有 claim_id

    def test_claim_pass_clean_text(self):
        assert check_r4_claim("c1", "本季營收較上季成長 5%") is None

    def test_claim_fail_chinese_advice(self):
        v = check_r4_claim("c1", "基於以上分析，建議買入此股票")
        assert v is not None
        assert v.rule == "R4"
        assert v.severity == "error"

    def test_claim_fail_english_advice(self):
        v = check_r4_claim("c1", "Based on results, a buy recommendation is warranted")
        assert v is not None
        assert v.rule == "R4"

    def test_claim_fail_target_price(self):
        v = check_r4_claim("c1", "目標價 250 元，預計上漲空間 15%")
        assert v is not None
        assert v.rule == "R4"

    def test_claim_case_insensitive(self):
        v = check_r4_claim("c1", "Investment Advice: buy now")
        assert v is not None
        assert v.rule == "R4"


# ─────────────────────────────────────────────────────────────────────────────
# R5: evidence document_id 必須一致（跨文件推論標警告）
# ─────────────────────────────────────────────────────────────────────────────

class TestR5:
    def test_pass_same_document(self):
        ev = _ev(doc_id="doc-abc")
        assert check_r5("c1", "doc-abc", [ev]) is None

    def test_pass_empty_evidence(self):
        assert check_r5("c1", "doc-abc", []) is None

    def test_fail_different_document(self):
        ev = _ev(doc_id="doc-other")
        v = check_r5("c1", "doc-abc", [ev])
        assert v is not None
        assert v.rule == "R5"
        assert v.severity == "warning"  # R5 是 warning，不是 error

    def test_pass_evidence_without_document_id(self):
        # evidence 沒有 document_id → 不觸發 R5
        ev = {"page": "5", "quoted_text": "test"}
        assert check_r5("c1", "doc-abc", [ev]) is None

    def test_fail_only_one_mismatch_needed(self):
        evs = [_ev(doc_id="doc-abc"), _ev(doc_id="doc-other")]
        v = check_r5("c1", "doc-abc", evs)
        assert v is not None
        assert v.rule == "R5"


# ─────────────────────────────────────────────────────────────────────────────
# R7: 單季資料不得推論長期趨勢
# ─────────────────────────────────────────────────────────────────────────────

class TestR7:
    def test_pass_no_trend_language(self):
        assert check_r7_claim("c1", "本季毛利率為 45.2%，較上季上升 2.1 個百分點") is None

    def test_fail_chinese_trend_phrase(self):
        v = check_r7_claim("c1", "依本季數據，長期趨勢向好")
        assert v is not None
        assert v.rule == "R7"
        assert v.severity == "warning"  # R7 是 warning

    def test_fail_english_trend_phrase(self):
        v = check_r7_claim("c1", "This represents a long-term trend of margin expansion")
        assert v is not None
        assert v.rule == "R7"

    def test_fail_sustained_growth(self):
        v = check_r7_claim("c1", "Results indicate sustained growth ahead")
        assert v is not None
        assert v.rule == "R7"

    def test_case_insensitive(self):
        v = check_r7_claim("c1", "LONG-TERM TREND confirmed by data")
        assert v is not None
        assert v.rule == "R7"


# ─────────────────────────────────────────────────────────────────────────────
# GovernanceAuditResult properties
# ─────────────────────────────────────────────────────────────────────────────

class TestGovernanceAuditResult:
    def _make_result(self, violations=None, warnings=None):
        return GovernanceAuditResult(
            report_id="r1",
            document_id="doc-1",
            total_claims=3,
            violations=violations or [],
            warnings=warnings or [],
        )

    def test_passed_no_violations(self):
        r = self._make_result()
        assert r.passed is True
        assert r.violation_count == 0
        assert r.warning_count == 0

    def test_passed_with_warnings_only(self):
        w = GovernanceViolation(rule="R7", description="trend", severity="warning")
        r = self._make_result(warnings=[w])
        assert r.passed is True  # warning 不影響 passed
        assert r.warning_count == 1

    def test_failed_with_error(self):
        v = GovernanceViolation(rule="R1", description="no evidence", severity="error")
        r = self._make_result(violations=[v])
        assert r.passed is False
        assert r.violation_count == 1

    def test_failed_multiple_violations(self):
        v1 = GovernanceViolation(rule="R1", description="e1", severity="error")
        v2 = GovernanceViolation(rule="R4", description="e2", severity="error")
        r = self._make_result(violations=[v1, v2])
        assert r.passed is False
        assert r.violation_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# audit_claims() — integration of all rules
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditClaims:
    def test_clean_report_passes(self):
        claims = [_claim()]
        result = audit_claims("r1", "doc-1", claims, investment_advice_detected=False)
        assert result.passed is True
        assert result.violation_count == 0

    def test_investment_advice_detected_fails(self):
        claims = [_claim()]
        result = audit_claims("r1", "doc-1", claims, investment_advice_detected=True)
        assert result.passed is False
        r4_violations = [v for v in result.violations if v.rule == "R4"]
        assert len(r4_violations) >= 1

    def test_r1_violation_no_evidence(self):
        claims = [_claim(evidence=[])]
        result = audit_claims("r1", "doc-1", claims, investment_advice_detected=False)
        assert result.passed is False
        r1_violations = [v for v in result.violations if v.rule == "R1"]
        assert len(r1_violations) == 1

    def test_r3_auto_fixed_goes_to_warnings(self):
        # R3 auto_fixed=True → warning, not violation
        claims = [_claim(claim_level="interpretation", evidence=[])]
        result = audit_claims("r1", "doc-1", claims, investment_advice_detected=False)
        r3_warnings = [w for w in result.warnings if w.rule == "R3"]
        assert len(r3_warnings) == 1
        # R1 still fires (no evidence)
        r1_violations = [v for v in result.violations if v.rule == "R1"]
        assert len(r1_violations) == 1

    def test_r5_cross_doc_goes_to_warnings(self):
        ev = _ev(doc_id="other-doc")
        claims = [_claim(evidence=[ev])]
        result = audit_claims("r1", "doc-1", claims, investment_advice_detected=False)
        r5_warnings = [w for w in result.warnings if w.rule == "R5"]
        assert len(r5_warnings) == 1
        assert result.passed is True  # R5 是 warning，不影響 passed

    def test_r7_trend_goes_to_warnings(self):
        claims = [_claim(claim="本季數據顯示長期趨勢向上")]
        result = audit_claims("r1", "doc-1", claims, investment_advice_detected=False)
        r7_warnings = [w for w in result.warnings if w.rule == "R7"]
        assert len(r7_warnings) == 1
        assert result.passed is True  # R7 是 warning

    def test_multiple_claims_violations_accumulate(self):
        claims = [
            _claim(claim_id="c1", evidence=[]),      # R1 violation
            _claim(claim_id="c2"),                   # clean
            _claim(claim_id="c3", evidence=[]),      # R1 violation
        ]
        result = audit_claims("r1", "doc-1", claims, investment_advice_detected=False)
        r1_violations = [v for v in result.violations if v.rule == "R1"]
        assert len(r1_violations) == 2

    def test_empty_claims_passes(self):
        result = audit_claims("r1", "doc-1", [], investment_advice_detected=False)
        assert result.passed is True
        assert result.total_claims == 0

    def test_r2_derived_metric_missing_quoted_text(self):
        ev = _ev(quoted="")
        claims = [_claim(claim_level="derived_metric", evidence=[ev])]
        result = audit_claims("r1", "doc-1", claims, investment_advice_detected=False)
        r2_violations = [v for v in result.violations if v.rule == "R2"]
        assert len(r2_violations) == 1
        assert result.passed is False
