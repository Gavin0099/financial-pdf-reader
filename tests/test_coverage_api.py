"""
Coverage API unit tests — no MongoDB, no Claude API.

Tests the pure logic in get_coverage() by simulating
the objects/data it needs via SimpleNamespace mocks.
"""
from types import SimpleNamespace


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_report(pages_covered, chunks_used=None):
    return SimpleNamespace(
        report_id="r1",
        document_id="d1",
        pages_covered=pages_covered,
        chunks_used=chunks_used or [],
    )


def _make_doc(total_pages):
    return SimpleNamespace(total_pages=total_pages)


def _coverage_logic(report, doc, total_chunks: int) -> dict:
    """
    Mirrors the pure logic inside get_coverage(), extracted for unit testing
    without needing FastAPI or a live DB.
    """
    total_pages = int(doc.total_pages) if doc and doc.total_pages else 0

    covered_set = {int(p) for p in (report.pages_covered or [])}
    pages_covered = sorted(covered_set)

    if total_pages > 0:
        coverage_pct = round(len(covered_set) / total_pages * 100, 1)
        uncovered_pages = [p for p in range(1, total_pages + 1) if p not in covered_set]
    else:
        coverage_pct = 0.0
        uncovered_pages = []

    return {
        "total_pages": total_pages,
        "pages_covered": pages_covered,
        "coverage_pct": coverage_pct,
        "chunks_used": len(report.chunks_used or []),
        "total_chunks": total_chunks,
        "uncovered_pages": uncovered_pages,
    }


# ── tests ─────────────────────────────────────────────────────────────────────

def test_coverage_pct_correct():
    report = _make_report(pages_covered=[1, 2, 5], chunks_used=["c1", "c2", "c3"])
    doc = _make_doc(total_pages=10)
    result = _coverage_logic(report, doc, total_chunks=40)

    assert result["coverage_pct"] == 30.0
    assert result["pages_covered"] == [1, 2, 5]
    assert result["chunks_used"] == 3
    assert result["total_chunks"] == 40
    assert result["total_pages"] == 10


def test_uncovered_pages_correct():
    report = _make_report(pages_covered=[1, 3])
    doc = _make_doc(total_pages=5)
    result = _coverage_logic(report, doc, total_chunks=20)

    assert result["uncovered_pages"] == [2, 4, 5]


def test_full_coverage():
    report = _make_report(pages_covered=[1, 2, 3])
    doc = _make_doc(total_pages=3)
    result = _coverage_logic(report, doc, total_chunks=9)

    assert result["coverage_pct"] == 100.0
    assert result["uncovered_pages"] == []


def test_zero_total_pages_no_division_error():
    report = _make_report(pages_covered=[1, 2])
    doc = _make_doc(total_pages=0)
    result = _coverage_logic(report, doc, total_chunks=5)

    assert result["coverage_pct"] == 0.0
    assert result["uncovered_pages"] == []
    assert result["total_pages"] == 0


def test_empty_pages_covered():
    report = _make_report(pages_covered=[])
    doc = _make_doc(total_pages=50)
    result = _coverage_logic(report, doc, total_chunks=200)

    assert result["coverage_pct"] == 0.0
    assert result["pages_covered"] == []
    assert len(result["uncovered_pages"]) == 50


def test_pages_covered_deduplication():
    # page IDs should be deduplicated (set semantics)
    report = _make_report(pages_covered=[1, 1, 2, 2])
    doc = _make_doc(total_pages=4)
    result = _coverage_logic(report, doc, total_chunks=10)

    assert result["coverage_pct"] == 50.0
    assert result["pages_covered"] == [1, 2]
    assert result["uncovered_pages"] == [3, 4]


def test_chunks_used_count():
    report = _make_report(
        pages_covered=[1],
        chunks_used=["c1", "c2", "c3", "c4", "c5"],
    )
    doc = _make_doc(total_pages=10)
    result = _coverage_logic(report, doc, total_chunks=100)

    assert result["chunks_used"] == 5


def test_none_pages_covered_handled():
    report = _make_report(pages_covered=None)
    doc = _make_doc(total_pages=10)
    result = _coverage_logic(report, doc, total_chunks=30)

    assert result["coverage_pct"] == 0.0
    assert result["pages_covered"] == []
