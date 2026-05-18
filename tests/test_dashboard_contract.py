from pathlib import Path
from types import SimpleNamespace

from services.dashboard_contract import (
    DASHBOARD_CONTRACT_VERSION,
    serialize_summary_response,
    validate_dashboard_contract_v1,
)


def _dummy_report():
    ev = [SimpleNamespace(page="1", section="s", quoted_text="q")]
    claim = SimpleNamespace(
        claim_id="c1",
        claim="毛利率下降 12pp",
        claim_type="financial_observation",
        claim_level="derived_metric",
        materiality="tier_a",
        section_key="key_financials",
        recurring=True,
        contaminated=False,
        source_type="financial_evidence",
        forward_looking=False,
        rhetorical_risk_flag=False,
        rhetorical_risk_terms=[],
        attribution_prefix="",
        confidence="high",
        requires_human_review=False,
        evidence=ev,
    )
    return SimpleNamespace(
        report_id="r1",
        document_id="d1",
        stock_id="2330",
        period="2026Q1",
        temporal_consistent=True,
        temporal_note="",
        executive_summary="summary",
        narrative_density_score=0.1,
        narrative_density_weighted_score=0.1,
        narrative_flag=False,
        claims=[claim],
        evidence_status="complete",
        investment_advice_detected=False,
        completeness_warnings=[],
        dashboard={
            "contract_version": DASHBOARD_CONTRACT_VERSION,
            "metrics": [],
            "what_changed": [],
            "causal_edges": [],
            "risk_surface": [],
            "adjustments": [],
            "transparency": {},
        },
        dashboard_contract_valid=True,
        dashboard_contract_errors=[],
    )


def test_invalid_dashboard_contract_marks_invalid():
    payload = {
        "contract_version": "bad",
        "metrics": [{"metric_id": "gross_margin", "direction": "down", "metric_type": "profitability", "evidence_claim_ids": []}],
        "what_changed": [],
        "causal_edges": [],
        "risk_surface": [],
        "adjustments": [],
        "transparency": {},
    }
    errors = validate_dashboard_contract_v1(payload)
    assert errors
    assert "contract_version_mismatch" in errors


def test_frontend_invalid_contract_has_render_only_guard():
    src = Path("static/index.html").read_text(encoding="utf-8")
    assert "const contractValid = data.dashboard_contract_valid !== false;" in src
    assert "if (contractValid) {" in src
    assert "→ unknown" not in src


def test_create_get_contract_keys_share_serializer_contract_shape():
    report = _dummy_report()
    payload = serialize_summary_response(report)
    required = {
        "dashboard",
        "dashboard_contract_valid",
        "dashboard_contract_errors",
        "what_changed",
    }
    assert "dashboard" in payload
    assert required - (set(payload.keys()) | set(payload["dashboard"].keys())) == set()


def test_summarization_must_not_redefine_dashboard_enums():
    src = Path("services/summarization/__init__.py").read_text(encoding="utf-8")
    banned_tokens = [
        "DASHBOARD_CONTRACT_VERSION =",
        "_RELATION_ENUM =",
        "_SEVERITY_ENUM =",
        "_TREND_ENUM =",
    ]
    for token in banned_tokens:
        assert token not in src
