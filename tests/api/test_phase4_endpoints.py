"""API tests: Phase 4 console endpoints (proposals, artifacts, dashboard,
audit recent, CSRF rotation) + extended fact projection."""

from __future__ import annotations

from tests.conftest import fixture_bytes, upload_case


def _process(app_client, case_id: str) -> dict:
    response = app_client.post(f"/api/v1/cases/{case_id}/process")
    assert response.status_code == 200, response.text
    return response.json()


def test_proposals_list_requires_auth(app_client):
    response = app_client.get("/api/v1/proposals")
    assert response.status_code == 401


def test_proposals_list_empty(authed_client):
    body = authed_client.get("/api/v1/proposals").json()
    assert body["proposals"] == []
    assert body["limit"] == 50 and body["offset"] == 0


def test_proposals_list_flow(authed_client):
    created = upload_case(authed_client, "invoices/clean.pdf")
    _process(authed_client, created["case"]["id"])
    body = authed_client.get("/api/v1/proposals").json()
    assert len(body["proposals"]) == 1
    proposal = body["proposals"][0]
    assert proposal["case_id"] == created["case"]["id"]
    assert proposal["status"] == "PENDING"
    assert proposal["amount"] == "1240.00"
    page = authed_client.get("/api/v1/proposals?limit=1&offset=1").json()
    assert page["proposals"] == []


def test_artifact_content_requires_auth(app_client):
    upload_case(app_client, "invoices/clean.pdf")
    case_id = app_client.get("/api/v1/cases").json()["cases"][0]["id"]
    detail = app_client.get(f"/api/v1/cases/{case_id}").json()
    artifact_id = detail["artifacts"][0]["id"]
    response = app_client.get(
        f"/api/v1/cases/{case_id}/artifacts/{artifact_id}/content")
    assert response.status_code == 401


def test_artifact_content_roundtrip(authed_client):
    created = upload_case(authed_client, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    artifact_id = created["artifacts"][0]["id"]
    response = authed_client.get(
        f"/api/v1/cases/{case_id}/artifacts/{artifact_id}/content")
    assert response.status_code == 200
    assert response.content == fixture_bytes("invoices/clean.pdf")
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_artifact_content_404s(authed_client):
    first = upload_case(authed_client, "invoices/clean.pdf")
    second = upload_case(authed_client, "invoices/clean.pdf")
    artifact_id = first["artifacts"][0]["id"]
    bad = authed_client.get(
        f"/api/v1/cases/{first['case']['id']}/artifacts/nope/content")
    assert bad.status_code == 404
    cross = authed_client.get(
        f"/api/v1/cases/{second['case']['id']}/artifacts/{artifact_id}/content")
    assert cross.status_code == 404


def test_dashboard_requires_auth(app_client):
    assert app_client.get("/api/v1/dashboard/summary").status_code == 401


def test_dashboard_counts(authed_client):
    first = upload_case(authed_client, "invoices/clean.pdf")
    upload_case(authed_client, "invoices/clean.pdf")
    _process(authed_client, first["case"]["id"])
    body = authed_client.get("/api/v1/dashboard/summary").json()
    assert sum(body["cases_by_state"].values()) == 2
    assert body["proposals_by_status"].get("PENDING") == 1
    assert body["payments_total"] == 0
    assert len(body["recent_cases"]) == 2
    assert set(body["recent_cases"][0]) == {
        "id", "state", "created_at", "updated_at"}


def test_audit_recent_requires_auth(app_client):
    assert app_client.get("/api/v1/audit/recent").status_code == 401


def test_audit_recent_shape(authed_client):
    created = upload_case(authed_client, "invoices/clean.pdf")
    _process(authed_client, created["case"]["id"])
    body = authed_client.get("/api/v1/audit/recent").json()
    assert "case_id" not in body  # not captured by /audit/{case_id}
    assert body["limit"] == 50 and body["offset"] == 0
    assert len(body["events"]) > 0
    assert all(isinstance(event["payload"], dict) for event in body["events"])
    assert any(event["case_id"] is None for event in body["events"])


def test_csrf_refresh_requires_auth(app_client):
    assert app_client.post("/api/v1/auth/csrf-refresh").status_code == 401


def test_csrf_rotation(app_client, test_pin):
    login = app_client.post("/api/v1/auth/login", json={"pin": test_pin})
    assert login.status_code == 200
    old = login.json()["csrf_token"]
    refresh = app_client.post("/api/v1/auth/csrf-refresh")
    assert refresh.status_code == 200
    new = refresh.json()["csrf_token"]
    assert new and new != old
    stale = app_client.post("/api/v1/cases/nope/reject",
                            headers={"X-CSRF-Token": old})
    assert stale.status_code == 403
    fresh = app_client.post("/api/v1/cases/nope/reject",
                            headers={"X-CSRF-Token": new})
    assert fresh.status_code == 404  # CSRF passed; case missing


def test_facts_carry_source_and_producer(authed_client):
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert len(body["facts"]) > 0
    fact = body["facts"][0]
    assert fact["source"]["artifact_id"]
    assert fact["source"]["artifact_kind"] == "invoice"
    assert fact["producer"]["adapter"]
    assert "model_id" in fact["producer"]
