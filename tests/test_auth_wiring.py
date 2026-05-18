from fastapi import FastAPI
from fastapi.testclient import TestClient

from apis.v1.routers import diff as diff_router
from apis.v1.routers import patterns as patterns_router
from apis.v1.routers import summary as summary_router
import auth.jwt_bearer as jwt_bearer


def _app_with(router, prefix: str) -> FastAPI:
    app = FastAPI()
    app.include_router(router.router, prefix=prefix)
    return app


def test_summary_requires_token_and_accepts_valid_token(monkeypatch):
    app = _app_with(summary_router, "/api/v1/documents")
    client = TestClient(app)

    monkeypatch.setattr(
        summary_router,
        "generate_summary",
        lambda document_id: {"ok": True, "document_id": document_id},
    )
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)

    no_auth = client.post("/api/v1/documents/doc-1/summary")
    assert no_auth.status_code in (401, 403)

    auth = client.post(
        "/api/v1/documents/doc-1/summary",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert auth.status_code == 200
    assert auth.json()["ok"] is True


def test_diff_requires_token_and_accepts_valid_token(monkeypatch):
    app = _app_with(diff_router, "/api/v1/reports")
    client = TestClient(app)

    monkeypatch.setattr(
        diff_router,
        "generate_diff",
        lambda current_document_id, previous_document_id: {
            "ok": True,
            "current": current_document_id,
            "previous": previous_document_id,
        },
    )
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)

    no_auth = client.post(
        "/api/v1/reports/diff",
        json={"current_document_id": "a", "previous_document_id": "b"},
    )
    assert no_auth.status_code in (401, 403)

    auth = client.post(
        "/api/v1/reports/diff",
        json={"current_document_id": "a", "previous_document_id": "b"},
        headers={"Authorization": "Bearer valid-token"},
    )
    assert auth.status_code == 200
    assert auth.json()["ok"] is True


def test_patterns_requires_token_and_accepts_valid_token(monkeypatch):
    app = _app_with(patterns_router, "/api/v1/documents")
    client = TestClient(app)

    monkeypatch.setattr(
        patterns_router,
        "run_pattern_analysis",
        lambda document_id: {"ok": True, "document_id": document_id},
    )
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)

    no_auth = client.post("/api/v1/documents/doc-2/patterns/run")
    assert no_auth.status_code in (401, 403)

    auth = client.post(
        "/api/v1/documents/doc-2/patterns/run",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert auth.status_code == 200
    assert auth.json()["ok"] is True
