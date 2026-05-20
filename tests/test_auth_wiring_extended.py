from fastapi import FastAPI
from fastapi.testclient import TestClient

from apis.v1.routers import documents as documents_router
from apis.v1.routers import classification as classification_router
from apis.v1.routers import tables as tables_router
from apis.v1.routers import data_source as data_source_router
from apis.v1.routers import disclosures as disclosures_router
import auth.jwt_bearer as jwt_bearer


def _app_with(router, prefix: str) -> FastAPI:
    app = FastAPI()
    app.include_router(router.router, prefix=prefix)
    return app


def test_documents_ingest_requires_token_and_accepts_valid_token(monkeypatch):
    app = _app_with(documents_router, "/api/v1/documents")
    client = TestClient(app)
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)
    monkeypatch.setattr(
        documents_router,
        "ingest_pdf",
        lambda document_id: {
            "document_id": document_id,
            "pages_extracted": 1,
            "chunks_created": 1,
            "status": "completed",
        },
    )

    no_auth = client.post("/api/v1/documents/doc-1/ingest")
    assert no_auth.status_code in (401, 403)

    auth = client.post(
        "/api/v1/documents/doc-1/ingest",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert auth.status_code == 200
    assert auth.json()["document_id"] == "doc-1"


def test_classification_requires_token_and_accepts_valid_token(monkeypatch):
    app = _app_with(classification_router, "/api/v1/documents")
    client = TestClient(app)
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)
    monkeypatch.setattr(
        classification_router,
        "classify_document",
        lambda document_id, use_llm_fallback=True: {"document_id": document_id, "ok": True},
    )

    no_auth = client.post("/api/v1/documents/doc-2/classify")
    assert no_auth.status_code in (401, 403)

    auth = client.post(
        "/api/v1/documents/doc-2/classify",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert auth.status_code == 200
    assert auth.json()["ok"] is True


def test_tables_extract_requires_token_and_accepts_valid_token(monkeypatch):
    app = _app_with(tables_router, "/api/v1/documents")
    client = TestClient(app)
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)
    monkeypatch.setattr(
        tables_router,
        "extract_tables",
        lambda document_id: {"document_id": document_id, "status": "ok"},
    )

    no_auth = client.post("/api/v1/documents/doc-3/extract-tables")
    assert no_auth.status_code in (401, 403)

    auth = client.post(
        "/api/v1/documents/doc-3/extract-tables",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert auth.status_code == 200
    assert auth.json()["status"] == "ok"


def test_data_source_fetch_requires_token_and_accepts_valid_token(monkeypatch):
    app = _app_with(data_source_router, "/api/v1/stocks")
    client = TestClient(app)
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)
    monkeypatch.setattr(
        data_source_router,
        "fetch_monthly_revenue",
        lambda stock_id, period: [{"stock_id": stock_id, "period": period}],
    )

    no_auth = client.post("/api/v1/stocks/2330/fetch-revenue?period=2026Q1")
    assert no_auth.status_code in (401, 403)

    auth = client.post(
        "/api/v1/stocks/2330/fetch-revenue?period=2026Q1",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert auth.status_code == 200
    assert auth.json()["stock_id"] == "2330"


def test_disclosure_coverage_requires_token_and_accepts_valid_token(monkeypatch):
    app = _app_with(disclosures_router, "/api/v1/documents")
    client = TestClient(app)
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)
    monkeypatch.setattr(
        disclosures_router,
        "check_disclosure_coverage",
        lambda document_id: {"document_id": document_id, "ok": True},
    )

    no_auth = client.post("/api/v1/documents/doc-4/disclosure-coverage")
    assert no_auth.status_code in (401, 403)

    auth = client.post(
        "/api/v1/documents/doc-4/disclosure-coverage",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert auth.status_code == 200
    assert auth.json()["ok"] is True

