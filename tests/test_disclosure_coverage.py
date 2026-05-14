"""
Unit tests for services/disclosure_coverage — Phase 9D

All tests are pure Python: no MongoDB, no HTTP, no external API calls.
Uses unittest.mock to patch Claude API and PDFDocument / PDFChunk.
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from models.disclosures import DISCLOSURE_REGISTRY, STATUS_CHOICES


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_claude_response(items: list[dict]) -> MagicMock:
    """Build a mock Claude API response containing a JSON items list."""
    payload = json.dumps({"items": items})
    msg = MagicMock()
    msg.content = [MagicMock(text=payload)]
    return msg


def _full_items(status: str = "found") -> list[dict]:
    """Return all 14 registry keys with a given status."""
    return [
        {
            "key": key,
            "label_zh": label,
            "status": status,
            "evidence_pages": ["5"],
            "note": "test note",
        }
        for key, label in DISCLOSURE_REGISTRY
    ]


def _mock_doc(document_id: str = "doc-1", status: str = "completed"):
    doc = MagicMock()
    doc.document_id = document_id
    doc.stock_id = "2330"
    doc.company_name = "台積電"
    doc.period = "2025Q1"
    doc.status = status
    return doc


def _mock_chunk(page: int = 1, text: str = "sample text"):
    chunk = MagicMock()
    chunk.page = page
    chunk.text = text
    return chunk


# ─────────────────────────────────────────────────────────────────────────────
# Registry tests (no mocking needed)
# ─────────────────────────────────────────────────────────────────────────────

def test_registry_has_14_items():
    assert len(DISCLOSURE_REGISTRY) == 14


def test_registry_keys_unique():
    keys = [k for k, _ in DISCLOSURE_REGISTRY]
    assert len(keys) == len(set(keys))


def test_status_choices_complete():
    expected = {"found", "found_incomplete", "not_found", "ambiguous", "not_applicable"}
    assert set(STATUS_CHOICES) == expected


# ─────────────────────────────────────────────────────────────────────────────
# Service unit tests (mock Claude + MongoDB)
# ─────────────────────────────────────────────────────────────────────────────

@patch("services.disclosure_coverage.DisclosureCoverageReport")
@patch("services.disclosure_coverage.PDFChunk")
@patch("services.disclosure_coverage.PDFDocument")
@patch("services.disclosure_coverage._get_client")
def test_all_14_keys_present_in_result(mock_client, mock_doc_cls, mock_chunk_cls, mock_report_cls):
    """Even if Claude returns all items, result must contain exactly 14 keys."""
    mock_doc_cls.objects.return_value.first.return_value = _mock_doc()
    mock_chunk_cls.objects.return_value.order_by.return_value.limit.return_value = [
        _mock_chunk()
    ]
    mock_client.return_value.messages.create.return_value = _make_claude_response(
        _full_items("found")
    )
    mock_report_cls.return_value.save = MagicMock()
    mock_report_cls.return_value.coverage_id = "cov-1"

    from services.disclosure_coverage import check_disclosure_coverage
    result = check_disclosure_coverage("doc-1")

    assert len(result["items"]) == 14
    returned_keys = {item["key"] for item in result["items"]}
    registry_keys = {k for k, _ in DISCLOSURE_REGISTRY}
    assert returned_keys == registry_keys


@patch("services.disclosure_coverage.DisclosureCoverageReport")
@patch("services.disclosure_coverage.PDFChunk")
@patch("services.disclosure_coverage.PDFDocument")
@patch("services.disclosure_coverage._get_client")
def test_missing_keys_filled_with_ambiguous(mock_client, mock_doc_cls, mock_chunk_cls, mock_report_cls):
    """If Claude omits some keys, they must be filled with ambiguous status."""
    mock_doc_cls.objects.return_value.first.return_value = _mock_doc()
    mock_chunk_cls.objects.return_value.order_by.return_value.limit.return_value = [
        _mock_chunk()
    ]
    # Claude only returns 3 of 14 items
    partial_items = _full_items("found")[:3]
    mock_client.return_value.messages.create.return_value = _make_claude_response(partial_items)
    mock_report_cls.return_value.save = MagicMock()
    mock_report_cls.return_value.coverage_id = "cov-2"

    from services.disclosure_coverage import check_disclosure_coverage
    result = check_disclosure_coverage("doc-1")

    assert len(result["items"]) == 14
    ambiguous_items = [i for i in result["items"] if i["status"] == "ambiguous"]
    assert len(ambiguous_items) == 11  # 14 - 3 returned = 11 filled as ambiguous


@patch("services.disclosure_coverage.DisclosureCoverageReport")
@patch("services.disclosure_coverage.PDFChunk")
@patch("services.disclosure_coverage.PDFDocument")
@patch("services.disclosure_coverage._get_client")
def test_not_applicable_not_counted_in_not_found(mock_client, mock_doc_cls, mock_chunk_cls, mock_report_cls):
    """not_applicable items must NOT increment not_found_count."""
    mock_doc_cls.objects.return_value.first.return_value = _mock_doc()
    mock_chunk_cls.objects.return_value.order_by.return_value.limit.return_value = [
        _mock_chunk()
    ]
    items = _full_items("not_applicable")
    mock_client.return_value.messages.create.return_value = _make_claude_response(items)
    mock_report_cls.return_value.save = MagicMock()
    mock_report_cls.return_value.coverage_id = "cov-3"

    from services.disclosure_coverage import check_disclosure_coverage
    result = check_disclosure_coverage("doc-1")

    assert result["not_found_count"] == 0
    assert result["not_applicable_count"] == 14


@patch("services.disclosure_coverage.DisclosureCoverageReport")
@patch("services.disclosure_coverage.PDFChunk")
@patch("services.disclosure_coverage.PDFDocument")
@patch("services.disclosure_coverage._get_client")
def test_found_count_accurate(mock_client, mock_doc_cls, mock_chunk_cls, mock_report_cls):
    """found_count must equal number of items with status=found."""
    mock_doc_cls.objects.return_value.first.return_value = _mock_doc()
    mock_chunk_cls.objects.return_value.order_by.return_value.limit.return_value = [
        _mock_chunk()
    ]
    # 5 found, 9 not_found
    items = _full_items("found")[:5] + [
        {"key": k, "label_zh": l, "status": "not_found", "evidence_pages": [], "note": ""}
        for k, l in DISCLOSURE_REGISTRY[5:]
    ]
    mock_client.return_value.messages.create.return_value = _make_claude_response(items)
    mock_report_cls.return_value.save = MagicMock()
    mock_report_cls.return_value.coverage_id = "cov-4"

    from services.disclosure_coverage import check_disclosure_coverage
    result = check_disclosure_coverage("doc-1")

    assert result["found_count"] == 5
    assert result["not_found_count"] == 9


@patch("services.disclosure_coverage.PDFChunk")
@patch("services.disclosure_coverage.PDFDocument")
@patch("services.disclosure_coverage._get_client")
def test_invalid_json_raises_runtime_error(mock_client, mock_doc_cls, mock_chunk_cls):
    """Malformed Claude response must raise RuntimeError."""
    mock_doc_cls.objects.return_value.first.return_value = _mock_doc()
    mock_chunk_cls.objects.return_value.order_by.return_value.limit.return_value = [
        _mock_chunk()
    ]
    bad_msg = MagicMock()
    bad_msg.content = [MagicMock(text="這不是 JSON，根本無法解析 !!!")]
    mock_client.return_value.messages.create.return_value = bad_msg

    from services.disclosure_coverage import check_disclosure_coverage
    with pytest.raises(RuntimeError, match="Coverage 回傳格式無法解析"):
        check_disclosure_coverage("doc-1")


@patch("services.disclosure_coverage.PDFDocument")
def test_document_not_found_raises_value_error(mock_doc_cls):
    """Missing document must raise ValueError."""
    mock_doc_cls.objects.return_value.first.return_value = None

    from services.disclosure_coverage import check_disclosure_coverage
    with pytest.raises(ValueError, match="Document not found"):
        check_disclosure_coverage("nonexistent-doc")


@patch("services.disclosure_coverage.PDFDocument")
def test_not_ingested_raises_value_error(mock_doc_cls):
    """Document with status != completed must raise ValueError."""
    mock_doc_cls.objects.return_value.first.return_value = _mock_doc(status="uploaded")

    from services.disclosure_coverage import check_disclosure_coverage
    with pytest.raises(ValueError, match="not ingested"):
        check_disclosure_coverage("doc-1")
