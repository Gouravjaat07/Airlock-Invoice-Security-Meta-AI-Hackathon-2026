"""API tests: cases, errors, auth protection, rate limits."""

from __future__ import annotations

from tests.conftest import fixture_bytes, upload_case


def test_health(app_client):
    response = app_client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] >= 1
    assert body["policy_version"]


def test_openapi_available(app_client):
    response = app_client.get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/cases" in paths
    assert "/api/v1/auth/login" in paths


def test_create_and_process_clean(app_client):
    created = upload_case(app_client, "invoices/clean.pdf")
    assert created["case"]["state"] == "UPLOADED"
    case_id = created["case"]["id"]
    response = app_client.post(f"/api/v1/cases/{case_id}/process")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    assert body["proposal"]["amount"] == "1240.00"


def test_process_idempotent_over_api(app_client):
    created = upload_case(app_client, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    first = app_client.post(f"/api/v1/cases/{case_id}/process").json()
    second = app_client.post(f"/api/v1/cases/{case_id}/process").json()
    assert first["proposal"]["proposal_id"] == second["proposal"]["proposal_id"]


def test_upload_rejects_garbage(app_client):
    response = app_client.post(
        "/api/v1/cases",
        files=[("invoice", ("evil.pdf", b"MZ" + b"\x00" * 100,
                            "application/pdf"))])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "E_UPLOAD"


def test_upload_requires_invoice_field(app_client):
    response = app_client.post(
        "/api/v1/cases",
        files=[("delivery", ("d.png", fixture_bytes("delivery/sam-ok.png"),
                             "image/png"))])
    assert response.status_code == 400


def test_upload_rejects_unknown_field(app_client):
    response = app_client.post(
        "/api/v1/cases",
        files=[("invoice", ("c.pdf", fixture_bytes("invoices/clean.pdf"),
                            "application/pdf")),
               ("smuggle", ("s.pdf", fixture_bytes("invoices/clean.pdf"),
                            "application/pdf"))])
    assert response.status_code == 400


def test_case_not_found_envelope(app_client):
    response = app_client.get("/api/v1/cases/case-missing")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] and error["request_id"]


def test_reject_requires_auth(app_client):
    created = upload_case(app_client, "invoices/over-cap.pdf")
    case_id = created["case"]["id"]
    app_client.post(f"/api/v1/cases/{case_id}/process")
    response = app_client.post(f"/api/v1/cases/{case_id}/reject")
    assert response.status_code == 401


def test_reject_with_auth(authed_client):
    created = upload_case(authed_client, "invoices/over-cap.pdf")
    case_id = created["case"]["id"]
    authed_client.post(f"/api/v1/cases/{case_id}/process")
    response = authed_client.post(f"/api/v1/cases/{case_id}/reject")
    assert response.status_code == 200, response.text
    assert response.json()["case"]["state"] == "REJECTED"


def test_fact_edit_requires_auth(app_client):
    created = upload_case(app_client, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    body = app_client.post(f"/api/v1/cases/{case_id}/process").json()
    fact_id = body["facts"][0]["id"]
    response = app_client.post(
        f"/api/v1/cases/{case_id}/facts/{fact_id}/edit",
        json={"value": "x"})
    assert response.status_code == 401


def test_fact_edit_roundtrip(authed_client):
    created = upload_case(authed_client, "invoices/arithmetic-mismatch.pdf")
    case_id = created["case"]["id"]
    body = authed_client.post(f"/api/v1/cases/{case_id}/process").json()
    assert body["verdict"]["verdict"] == "DENY"
    total = next(f for f in body["facts"] if f["field"] == "total")
    response = authed_client.post(
        f"/api/v1/cases/{case_id}/facts/{total['id']}/edit",
        json={"value": "1240.00"})
    assert response.status_code == 200, response.text
    assert response.json()["verdict"]["verdict"] == "ALLOW_PROPOSAL"


def test_list_cases_pagination(app_client):
    upload_case(app_client, "invoices/clean.pdf")
    response = app_client.get("/api/v1/cases?limit=1&offset=0")
    assert response.status_code == 200
    assert len(response.json()["cases"]) == 1


def test_invalid_json_envelope(app_client):
    response = app_client.post("/api/v1/auth/login", content=b"{nope",
                               headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "E_SCHEMA"
