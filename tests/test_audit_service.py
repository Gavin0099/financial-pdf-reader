from types import SimpleNamespace

import pytest

import services.audit as audit_service


class _Query:
    def __init__(self, report):
        self._report = report

    def first(self):
        return self._report


def test_run_diff_audit_not_found(monkeypatch):
    class _DiffReportModel:
        @staticmethod
        def objects(**kwargs):
            return _Query(None)

    monkeypatch.setattr(audit_service, "DiffReport", _DiffReportModel)

    with pytest.raises(ValueError, match="DiffReport not found"):
        audit_service.run_diff_audit("dr-missing")


def test_run_diff_audit_pass_with_no_items(monkeypatch):
    report = SimpleNamespace(
        diff_report_id="dr-1",
        current_document_id="doc-current",
        previous_document_id="doc-prev",
        items=[],
    )

    class _DiffReportModel:
        @staticmethod
        def objects(**kwargs):
            return _Query(report)

    monkeypatch.setattr(audit_service, "DiffReport", _DiffReportModel)

    payload = audit_service.run_diff_audit("dr-1")
    assert payload["diff_report_id"] == "dr-1"
    assert payload["total_items"] == 0
    assert payload["passed"] is True
    assert payload["violation_count"] == 0


def test_run_diff_audit_flags_r6_violation(monkeypatch):
    report = SimpleNamespace(
        diff_report_id="dr-2",
        current_document_id="doc-current",
        previous_document_id="doc-prev",
        items=[
            SimpleNamespace(diff_id="d1", diff_type="tone_shift", tone_only=False),
            SimpleNamespace(diff_id="d2", diff_type="numeric_change", tone_only=False),
        ],
    )

    class _DiffReportModel:
        @staticmethod
        def objects(**kwargs):
            return _Query(report)

    monkeypatch.setattr(audit_service, "DiffReport", _DiffReportModel)

    payload = audit_service.run_diff_audit("dr-2")
    assert payload["passed"] is False
    assert payload["violation_count"] == 1
    assert payload["violations"][0]["rule"] == "R6"
    assert payload["violations"][0]["claim_id"] == "d1"

