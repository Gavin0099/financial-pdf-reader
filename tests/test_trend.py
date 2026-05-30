"""
Phase 3A — Multi-Period KPI Trend Service unit tests
純 Python，不依賴 MongoDB。
"""
import pytest
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_doc(document_id: str, period: str, stock_id: str = "2330"):
    doc = MagicMock()
    doc.document_id = document_id
    doc.period = period
    doc.stock_id = stock_id
    return doc


def _make_report(document_id: str, dashboard: dict):
    report = MagicMock()
    report.document_id = document_id
    report.dashboard = dashboard
    return report


def _dashboard(kpis: dict) -> dict:
    """Build minimal dashboard payload with what_changed list."""
    return {
        "what_changed": [
            {
                "metric_id": k,
                "metric_type": "ratio",
                "label": k,
                "direction": v.get("direction", "up"),
                "delta_pct": v.get("delta_pct", 5.0),
                "evidence_claim_ids": ["claim-001"],
                "impact": "medium",
                "claim_text": v.get("claim_text", f"{k} changed"),
                "confidence": "high",
            }
            for k, v in kpis.items()
        ]
    }


# ── _extract_kpi_points ───────────────────────────────────────────────────────

def test_extract_kpi_points_basic():
    from services.trend import _extract_kpi_points
    dashboard = _dashboard({"revenue": {"direction": "up", "delta_pct": 8.5}})
    points = _extract_kpi_points("doc-1", "2025Q1", dashboard)
    assert "revenue" in points
    assert points["revenue"].direction == "up"
    assert points["revenue"].delta_pct == 8.5
    assert points["revenue"].period == "2025Q1"
    assert points["revenue"].document_id == "doc-1"


def test_extract_kpi_points_ignores_unknown_kpi():
    from services.trend import _extract_kpi_points
    dashboard = _dashboard({"unknown_kpi_xyz": {"direction": "up"}})
    points = _extract_kpi_points("doc-1", "2025Q1", dashboard)
    assert "unknown_kpi_xyz" not in points


def test_extract_kpi_points_multiple_kpis():
    from services.trend import _extract_kpi_points
    dashboard = _dashboard({
        "revenue": {"direction": "up", "delta_pct": 10.0},
        "gross_margin": {"direction": "down", "delta_pct": -3.5},
        "eps": {"direction": "up", "delta_pct": 5.0},
    })
    points = _extract_kpi_points("doc-1", "2025Q2", dashboard)
    assert len(points) == 3
    assert points["gross_margin"].direction == "down"
    assert points["gross_margin"].delta_pct == -3.5


def test_extract_kpi_points_empty_dashboard():
    from services.trend import _extract_kpi_points
    points = _extract_kpi_points("doc-1", "2025Q1", {})
    assert points == {}


def test_extract_kpi_points_source_claim_id():
    from services.trend import _extract_kpi_points
    dashboard = _dashboard({"cash": {"direction": "flat", "delta_pct": 0.0}})
    points = _extract_kpi_points("doc-1", "2025Q1", dashboard)
    assert points["cash"].source_claim_id == "claim-001"


# ── R7 guard ──────────────────────────────────────────────────────────────────

def test_r7_warning_when_less_than_3_periods():
    from services.trend import generate_trend

    docs = [_make_doc(f"doc-{i}", f"2025Q{i}") for i in range(1, 3)]
    reports = [_make_report(f"doc-{i}", _dashboard({"revenue": {"direction": "up"}})) for i in range(1, 3)]

    with patch("services.trend.PDFDocument") as MockDoc, \
         patch("services.trend.AIReport") as MockReport, \
         patch("services.trend.TrendReport") as MockTR:

        # +1 extra for the stock_id lookup at end of generate_trend
        MockDoc.objects.return_value.first.side_effect = docs + [docs[0]]
        report_qs = MagicMock()
        report_qs.order_by.return_value.first.side_effect = reports
        MockReport.objects.return_value = report_qs

        saved = {}
        def fake_save(self_obj=None):
            pass

        tr_instance = MagicMock()
        tr_instance.trend_report_id = "tr-001"
        tr_instance.stock_id = "2330"
        tr_instance.document_ids = ["doc-1", "doc-2"]
        tr_instance.periods = ["2025Q1", "2025Q2"]
        tr_instance.kpi_trends = []
        tr_instance.r7_warning = True
        tr_instance.governance_flags = ["R7: 僅有 2 期資料（需 ≥ 3 期才可推論長期趨勢）"]
        tr_instance.created_at = "2026-05-30T00:00:00+00:00"
        MockTR.return_value = tr_instance

        result = generate_trend(["doc-1", "doc-2"])
        assert result["r7_warning"] is True
        assert any("R7" in f for f in result["governance_flags"])


def test_no_r7_warning_when_3_or_more_periods():
    from services.trend import generate_trend

    docs = [_make_doc(f"doc-{i}", f"2025Q{i}") for i in range(1, 4)]
    reports = [_make_report(f"doc-{i}", _dashboard({"revenue": {"direction": "up"}})) for i in range(1, 4)]

    with patch("services.trend.PDFDocument") as MockDoc, \
         patch("services.trend.AIReport") as MockReport, \
         patch("services.trend.TrendReport") as MockTR:

        MockDoc.objects.return_value.first.side_effect = docs + [docs[0]]
        report_qs = MagicMock()
        report_qs.order_by.return_value.first.side_effect = reports
        MockReport.objects.return_value = report_qs

        tr_instance = MagicMock()
        tr_instance.trend_report_id = "tr-002"
        tr_instance.stock_id = "2330"
        tr_instance.document_ids = ["doc-1", "doc-2", "doc-3"]
        tr_instance.periods = ["2025Q1", "2025Q2", "2025Q3"]
        tr_instance.kpi_trends = []
        tr_instance.r7_warning = False
        tr_instance.governance_flags = []
        tr_instance.created_at = "2026-05-30T00:00:00+00:00"
        MockTR.return_value = tr_instance

        result = generate_trend(["doc-1", "doc-2", "doc-3"])
        assert result["r7_warning"] is False
        assert result["governance_flags"] == []


# ── Period sorting ─────────────────────────────────────────────────────────────

def test_periods_sorted_chronologically():
    """Periods must be sorted lexicographically (2024Q3 < 2024Q4 < 2025Q1)."""
    from services.trend import generate_trend

    doc_ids = ["doc-b", "doc-a", "doc-c"]
    doc_periods = {"doc-a": "2025Q1", "doc-b": "2024Q3", "doc-c": "2024Q4"}

    def get_doc(document_id):
        d = _make_doc(document_id, doc_periods[document_id])
        return d

    def get_report(document_id):
        return _make_report(document_id, _dashboard({"revenue": {"direction": "up"}}))

    with patch("services.trend.PDFDocument") as MockDoc, \
         patch("services.trend.AIReport") as MockReport, \
         patch("services.trend.TrendReport") as MockTR:

        all_docs = [get_doc(d) for d in doc_ids]
        MockDoc.objects.return_value.first.side_effect = all_docs + [all_docs[0]]
        report_qs = MagicMock()
        report_qs.order_by.return_value.first.side_effect = [get_report(d) for d in doc_ids]
        MockReport.objects.return_value = report_qs

        tr_instance = MagicMock()
        tr_instance.trend_report_id = "tr-003"
        tr_instance.stock_id = "2330"
        tr_instance.document_ids = ["doc-b", "doc-c", "doc-a"]
        tr_instance.periods = ["2024Q3", "2024Q4", "2025Q1"]
        tr_instance.kpi_trends = []
        tr_instance.r7_warning = False
        tr_instance.governance_flags = []
        tr_instance.created_at = "2026-05-30T00:00:00+00:00"
        MockTR.return_value = tr_instance

        result = generate_trend(doc_ids)
        assert result["periods"] == ["2024Q3", "2024Q4", "2025Q1"]


# ── Input validation ──────────────────────────────────────────────────────────

def test_generate_trend_raises_on_empty_ids():
    from services.trend import generate_trend
    with pytest.raises(ValueError, match="不可為空"):
        generate_trend([])


def test_generate_trend_raises_when_document_not_found():
    from services.trend import generate_trend
    with patch("services.trend.PDFDocument") as MockDoc:
        MockDoc.objects.return_value.first.return_value = None
        with pytest.raises(ValueError, match="Document not found"):
            generate_trend(["nonexistent-id"])


def test_generate_trend_raises_when_report_not_found():
    from services.trend import generate_trend
    with patch("services.trend.PDFDocument") as MockDoc, \
         patch("services.trend.AIReport") as MockReport:
        MockDoc.objects.return_value.first.return_value = _make_doc("doc-x", "2025Q1")
        report_qs = MagicMock()
        report_qs.order_by.return_value.first.return_value = None
        MockReport.objects.return_value = report_qs
        with pytest.raises(ValueError, match="AIReport not found"):
            generate_trend(["doc-x"])
