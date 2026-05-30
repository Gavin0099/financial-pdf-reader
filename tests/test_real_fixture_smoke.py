"""
Real-fixture ingestion smoke tests — 3C.

Tests the extract → chunk → classify pipeline on synthetic PDFs without
calling Claude or connecting to MongoDB. Skipped if pdfplumber is not
installed (local dev), runs in CI where requirements.txt is installed.

Four invariants under test:
  1. Pipeline produces at least one chunk per fixture
  2. Every chunk carries page >= 1
  3. No chunk has section=None (fallback must be "unknown")
  4. total_pages from extract_pages() matches the fixture's intended page count
"""
import pytest

pdfplumber = pytest.importorskip("pdfplumber")  # skip entire file if missing

# These imports run only when pdfplumber is available (and anthropic is too in CI).
from services.pdf_ingestion import extract_pages, chunk_page
from services.classification import classify_chunk

# Maps fixture name → expected page count (matches _FIXTURE_SPECS in conftest.py)
_EXPECTED_PAGES = {
    "tsmc_2025q4": 5,
    "foxconn_2025q4": 8,
    "mediatek_2025q4": 6,
}

_FIXTURE_NAMES = list(_EXPECTED_PAGES.keys())


def _run_pipeline(pdf_path) -> list[dict]:
    """
    Replicate what ingest_pdf() does, without MongoDB.
    Returns list of dicts: {"page": int, "text": str, "section": str}.
    """
    pages = extract_pages(str(pdf_path))
    results = []
    for page_data in pages:
        for chunk_data in chunk_page(page_data["page"], page_data["text"]):
            section, _ = classify_chunk(chunk_data["text"], use_llm_fallback=False)
            results.append({
                "page": chunk_data["page"],
                "text": chunk_data["text"],
                "section": section,
            })
    return results


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_chunks_produced(synthetic_pdf_paths, name):
    """Pipeline must yield at least one chunk per fixture."""
    chunks = _run_pipeline(synthetic_pdf_paths[name])
    assert len(chunks) > 0, f"{name}: no chunks produced"


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_all_chunks_have_valid_page(synthetic_pdf_paths, name):
    """Every chunk must have page >= 1. No page=None, no page=0."""
    chunks = _run_pipeline(synthetic_pdf_paths[name])
    bad = [c for c in chunks if c["page"] is None or c["page"] < 1]
    assert bad == [], (
        f"{name}: {len(bad)} chunk(s) with invalid page: "
        + str([c["page"] for c in bad])
    )


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_no_chunk_has_none_section(synthetic_pdf_paths, name):
    """
    classify_chunk must never return None — fallback is 'unknown'.
    This is the precondition for coverage_pct and section-aware retrieval.
    """
    chunks = _run_pipeline(synthetic_pdf_paths[name])
    bad = [c for c in chunks if c["section"] is None]
    assert bad == [], f"{name}: {len(bad)} chunk(s) with section=None"


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_total_pages_matches_fixture(synthetic_pdf_paths, name):
    """extract_pages() must return exactly as many pages as the fixture has."""
    pages = extract_pages(str(synthetic_pdf_paths[name]))
    expected = _EXPECTED_PAGES[name]
    assert len(pages) == expected, (
        f"{name}: expected {expected} pages, got {len(pages)}"
    )


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_at_least_one_section_classified(synthetic_pdf_paths, name):
    """
    At least one chunk per fixture should match a keyword section
    (not everything 'unknown'). Verifies that the rule-based classifier
    actually fires on English financial keywords.
    """
    chunks = _run_pipeline(synthetic_pdf_paths[name])
    non_unknown = [c for c in chunks if c["section"] != "unknown"]
    assert len(non_unknown) > 0, (
        f"{name}: all {len(chunks)} chunks landed in 'unknown' — "
        "check SECTION_KEYWORDS for English keyword coverage"
    )
