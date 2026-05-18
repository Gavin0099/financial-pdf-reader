from types import SimpleNamespace

from services.summarization import _check_completeness


def _claim(*, text: str, section: str = "liquidity", level: str = "observed_fact"):
    return SimpleNamespace(
        claim=text,
        section_key=section,
        claim_level=level,
        recurring=True,
    )


def test_oc2_warns_for_cash_and_corporate_bond_without_safety_margin():
    claims = [
        _claim(text="現金水位充足"),
        _claim(text="公司債將於明年到期"),
    ]
    warnings = _check_completeness(claims)
    assert any(w.startswith("OC-2:") for w in warnings)


def test_oc2_warns_for_cash_and_convertible_bond_without_safety_margin():
    claims = [
        _claim(text="Cash balance increased this quarter"),
        _claim(text="可轉換公司債到期壓力上升"),
    ]
    warnings = _check_completeness(claims)
    assert any(w.startswith("OC-2:") for w in warnings)


def test_oc2_no_warning_when_liquidity_safety_margin_exists():
    claims = [
        _claim(text="現金部位增加"),
        _claim(text="短期借款續借成本提高"),
        _claim(text="liquidity_safety_margin = 1.3x", level="derived_metric"),
    ]
    warnings = _check_completeness(claims)
    assert all(not w.startswith("OC-2:") for w in warnings)


def test_oc2_does_not_trigger_for_non_liquidity_section():
    claims = [
        _claim(text="現金部位增加"),
        _claim(text="公司債條款更新", section="risk_register"),
    ]
    warnings = _check_completeness(claims)
    assert all(not w.startswith("OC-2:") for w in warnings)

