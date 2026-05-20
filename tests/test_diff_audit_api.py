from fastapi import FastAPI
from fastapi.testclient import TestClient

from apis.v1.routers import diff as diff_router
import auth.jwt_bearer as jwt_bearer


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(diff_router.router, prefix="/api/v1/reports")
    return app


def test_diff_audit_endpoint_requires_auth():
    client = TestClient(_app())
    res = client.get("/api/v1/reports/diff/dr-1/audit")
    assert res.status_code in (401, 403)


def test_diff_audit_endpoint_success(monkeypatch):
    client = TestClient(_app())
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)
    monkeypatch.setattr(
        diff_router,
        "run_diff_audit",
        lambda diff_report_id: {
            "diff_report_id": diff_report_id,
            "passed": True,
            "violation_count": 0,
            "warnings": [],
            "violations": [],
        },
    )

    res = client.get(
        "/api/v1/reports/diff/dr-1/audit",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["diff_report_id"] == "dr-1"
    assert payload["passed"] is True
    assert payload["violation_count"] == 0


def test_diff_audit_endpoint_not_found(monkeypatch):
    client = TestClient(_app())
    monkeypatch.setattr(jwt_bearer, "verify_jwt", lambda token: True)

    def _raise(_: str):
        raise ValueError("DiffReport not found: diff_report_id=dr-404")

    monkeypatch.setattr(diff_router, "run_diff_audit", _raise)

    res = client.get(
        "/api/v1/reports/diff/dr-404/audit",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert res.status_code == 404
    assert "DiffReport not found" in res.json()["detail"]

