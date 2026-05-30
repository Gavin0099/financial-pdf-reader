"""
Shared pytest fixtures — mock mongoengine so pure-Python unit tests
can import service/model modules without a live MongoDB connection.
"""
import sys
import types


def _make_mongoengine_stub():
    """Return a minimal mongoengine stub that satisfies model imports."""
    me = types.ModuleType("mongoengine")

    class _Field:
        def __init__(self, *a, **kw):
            pass

    class _BaseDoc:
        meta = {}
        objects = None
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
        def save(self):
            pass

    for name in (
        "Document", "EmbeddedDocument",
        "StringField", "IntField", "FloatField", "BooleanField",
        "DateTimeField", "ListField", "DictField",
        "EmbeddedDocumentField", "ReferenceField",
    ):
        cls = _BaseDoc if name in ("Document", "EmbeddedDocument") else _Field
        setattr(me, name, cls)

    me.connect = lambda *a, **kw: None
    return me


# Install stubs before any test module imports them
if "mongoengine" not in sys.modules:
    sys.modules["mongoengine"] = _make_mongoengine_stub()

# Also stub out database connection module so service imports don't fail
_db_mod = types.ModuleType("database")
_db_client = types.ModuleType("database.mongo")
_db_client_mod = types.ModuleType("database.mongo.client")
_db_client_mod.connect_mongodb = lambda: None
sys.modules.setdefault("database", _db_mod)
sys.modules.setdefault("database.mongo", _db_client)
sys.modules.setdefault("database.mongo.client", _db_client_mod)


def _make_anthropic_stub():
    """
    Minimal stub for the `anthropic` package.
    Allows service modules to be imported without the real SDK installed.
    Tests that actually call the API must mock the client separately.
    """
    mod = types.ModuleType("anthropic")

    class APIError(Exception):
        pass

    class _Message:
        def __init__(self):
            self.content = []

    class Anthropic:
        def __init__(self, *a, **kw):
            pass

        @property
        def messages(self):
            raise NotImplementedError("Real Anthropic client not available in tests")

    mod.Anthropic = Anthropic
    mod.APIError = APIError
    return mod


if "anthropic" not in sys.modules:
    sys.modules["anthropic"] = _make_anthropic_stub()

# dotenv stub — config.config calls load_dotenv() at import time
if "dotenv" not in sys.modules:
    _dotenv = types.ModuleType("dotenv")
    _dotenv.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = _dotenv


# ── Synthetic PDF generator (pure Python, zero deps) ─────────────────────────

def _make_pdf(page_texts: list[str]) -> bytes:
    """
    Build a minimal valid multi-page PDF from a list of ASCII page strings.
    Uses Helvetica (built-in Type1 font). No external dependencies.

    Object layout:
      1          = Catalog
      2          = Pages (parent)
      3+2*i      = Page[i]   (i = 0..n-1)
      4+2*i      = Content stream[i]
    """
    n = len(page_texts)
    assert n > 0, "need at least one page"

    def pid(i: int) -> int:  return 3 + 2 * i
    def cid(i: int) -> int:  return 4 + 2 * i

    total_objs = 2 + 2 * n

    def _escape(text: str) -> str:
        return (text
                .replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
                .replace("\r", " ")
                .replace("\n", " "))

    font_res = (
        b"<< /Font << /F1 << /Type /Font /Subtype /Type1"
        b" /BaseFont /Helvetica >> >> >>"
    )
    kids = " ".join(f"{pid(i)} 0 R" for i in range(n))

    obj_data: dict[int, bytes] = {}

    obj_data[1] = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj_data[2] = (
        f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {n} >>\nendobj\n"
    ).encode()

    for i, raw in enumerate(page_texts):
        safe = _escape("".join(c for c in raw if ord(c) < 128)[:250])
        stream = f"BT /F1 9 Tf 50 750 Td ({safe}) Tj ET\n".encode("ascii")

        obj_data[cid(i)] = (
            f"{cid(i)} 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"endstream\nendobj\n"
        )
        obj_data[pid(i)] = (
            f"{pid(i)} 0 obj\n<< /Type /Page /Parent 2 0 R"
            f" /MediaBox [0 0 612 792]"
            f" /Contents {cid(i)} 0 R /Resources ".encode()
            + font_res
            + b" >>\nendobj\n"
        )

    # Serialise in ID order, tracking byte offsets for xref
    header = b"%PDF-1.4\n"
    parts: list[bytes] = [header]
    offsets: dict[int, int] = {}

    for obj_id in range(1, total_objs + 1):
        offsets[obj_id] = sum(len(p) for p in parts)
        parts.append(obj_data[obj_id])

    xref_pos = sum(len(p) for p in parts)

    # xref entries must be exactly 20 bytes each (10 offset + SP + 5 gen + SP + f/n + SP + LF)
    xref = f"xref\n0 {total_objs + 1}\n0000000000 65535 f \n".encode()
    for obj_id in range(1, total_objs + 1):
        xref += f"{offsets[obj_id]:010d} 00000 n \n".encode()

    trailer = (
        f"trailer\n<< /Size {total_objs + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()

    return b"".join(parts) + xref + trailer


# ── Session-scoped fixture: 3 synthetic financial PDFs ────────────────────────

_FIXTURE_SPECS = {
    "tsmc_2025q4": [
        "Quarterly report for semiconductor company 2025Q4. "
        "Net revenue increased 12 percent year over year driven by advanced node demand.",
        "Gross profit and gross margin expanded due to better product mix and higher utilization. "
        "Gross margin reached 57 percent.",
        "Operating income grew reflecting revenue growth and cost control. "
        "Operating profit margin was 45 percent compared to 42 percent prior year.",
        "EPS earnings per share basic was 3.20 compared to 2.80 in prior year. "
        "Diluted earnings per share were 3.18.",
        "Risk factors include geopolitical uncertainty, supply chain risk, and foreign currency risk. "
        "Exchange rate and foreign currency movements affected revenue.",
    ],
    "foxconn_2025q4": [
        "Annual consolidated financial statements for electronics manufacturer.",
        "Net revenue and revenue from contracts with customers totalled 6.8 trillion.",
        "Operating income and operating profit showed improvement on cost reduction.",
        "Cash flow from operating activities was 120 billion positive. "
        "Free cash flow after capital expenditure was 80 billion.",
        "Accounts receivable trade receivable days outstanding improved to 45 days.",
        "Inventory turnover improved. Inventory and work in progress declined.",
        "Debt and liability structure: short-term borrowings were 200 billion. "
        "Long-term debt and corporate bond mature in 2027.",
        "Customer demand recovery expected in consumer electronics segment. "
        "Industry outlook remains cautiously optimistic.",
    ],
    "mediatek_2025q4": [
        "Semiconductor IC design company quarterly earnings release 2025Q4.",
        "Revenue increased driven by smartphone and IoT product lines. "
        "Net revenue grew 18 percent year on year.",
        "Gross margin improved due to product mix shift toward premium segment. "
        "Gross profit contribution increased.",
        "EPS earnings per share diluted was 45.2 NTD. "
        "Basic earnings per share was 45.5 NTD.",
        "Cash flow from operating activities remained strong at 38 billion. "
        "Cash and cash equivalents balance was 150 billion.",
        "Risk factors: customer concentration risk, market competition, "
        "uncertainty in geopolitical environment and supply chain.",
    ],
}


import pytest


@pytest.fixture(scope="session")
def synthetic_pdf_paths(tmp_path_factory):
    """
    Write 3 synthetic financial PDFs to a temp dir and return a dict of
    name → pathlib.Path. Used by test_real_fixture_smoke.py.
    """
    base = tmp_path_factory.mktemp("fixtures")
    paths = {}
    for name, page_texts in _FIXTURE_SPECS.items():
        pdf_bytes = _make_pdf(page_texts)
        p = base / f"{name}.pdf"
        p.write_bytes(pdf_bytes)
        paths[name] = p
    return paths
