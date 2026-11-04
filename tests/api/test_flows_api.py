"""API tests: auth lifecycle, vendors, proposals, payments, audit, eval."""

from __future__ import annotations

from tests.conftest import upload_case


def test_login_wrong_pin_generic(app_client):
    response = app_client.post("/api/v1/auth/login", json={"pin": "wrong-pin"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "E_AUTH"


def test_login_sets_httponly_cookie(app_client, test_pin):
    response = app_client.post("/api/v1/auth/login", json={"pin": test_pin})
    assert response.status_code == 200
    cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie
    assert "airlock_session=" in cookie
    assert "token" not in response.json()  # raw token never in body


def test_me_and_logout(authed_client):
    me = authed_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    out = authed_client.post("/api/v1/auth/logout")
    assert out.status_code == 200
    me2 = authed_client.get("/api/v1/auth/me")
    assert me2.status_code == 401


def test_vendor_crud(authed_client):
    created = authed_client.post("/api/v1/vendors", json={
        "name": "Test Vendor Seven",
        "bank_reference": "SYN-TEST-0007",
        "catalogue": [{"item_id": "w1", "label": "Widget", "tolerance": 0}],
        "per_invoice_cap": "500.00"}).json()
    assert created["vendor_id"]
    assert created["active_bank_fingerprint"].startswith("v1:")
    assert "bank_reference" not in created
    listed = authed_client.get("/api/v1/vendors").json()["vendors"]
    assert any(v["vendor_id"] == created["vendor_id"] for v in listed)
    updated = authed_client.patch(
        f"/api/v1/vendors/{created['vendor_id']}",
        json={"status": "inactive"}).json()
    assert updated["status"] == "inactive"


def test_vendor_create_requires_auth(app_client):
    response = app_client.post("/api/v1/vendors", json={
        "name": "Nope", "bank_reference": "SYN-X"})
    assert response.status_code == 401


def test_vendor_duplicate_name_rejected(authed_client):
    payload = {"name": "ACME flour CO!", "bank_reference": "SYN-DUP"}
    response = authed_client.post("/api/v1/vendors", json=payload)
    assert response.status_code == 409


def test_bank_change_workflow(authed_client):
    response = authed_client.post(
        "/api/v1/vendors/ven-acme-flour/bank-change-requests",
        json={"bank_reference": "SYN-ACME-NEW"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    listed = authed_client.get(
        "/api/v1/vendors/ven-acme-flour/bank-change-requests").json()
    assert len(listed["changes"]) == 1


def test_full_approval_flow(authed_client, test_pin):
    created = upload_case(authed_client, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    body = authed_client.post(f"/api/v1/cases/{case_id}/process").json()
    proposal_id = body["proposal"]["proposal_id"]
    shown = authed_client.get(f"/api/v1/proposals/{proposal_id}").json()
    assert shown["amount"] == "1240.00"
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    payment = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": test_pin}).json()
    assert payment["mock"] is True
    assert "MOCK" in payment["label"]
    fetched = authed_client.get(
        f"/api/v1/payments/mock/{payment['payment_id']}").json()
    assert fetched["payment_id"] == payment["payment_id"]
    listed = authed_client.get(
        f"/api/v1/cases/{case_id}/payments/mock").json()["payments"]
    assert len(listed) == 1


def test_challenge_replay_fails(authed_client, test_pin):
    created = upload_case(authed_client, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    body = authed_client.post(f"/api/v1/cases/{case_id}/process").json()
    proposal_id = body["proposal"]["proposal_id"]
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    first = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": test_pin})
    assert first.status_code == 200
    replay = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": test_pin})
    assert replay.status_code in (401, 409)
    listed = authed_client.get(
        f"/api/v1/cases/{case_id}/payments/mock").json()["payments"]
    assert len(listed) == 1


def test_audit_and_verify(authed_client):
    created = upload_case(authed_client, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    authed_client.post(f"/api/v1/cases/{case_id}/process")
    events = authed_client.get(f"/api/v1/audit/{case_id}").json()["events"]
    assert len(events) > 5
    assert events == sorted(events, key=lambda e: e["id"])
    verify = authed_client.post("/api/v1/audit/verify").json()
    assert verify["ok"] is True


def test_evaluation_run(authed_client):
    response = authed_client.post("/api/v1/evaluation/run", json={
        "scenarios": ["clean", "changed-bank", "over-cap"]})
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["matched"] == 3
    run_id = summary["run_id"]
    assert authed_client.get(f"/api/v1/evaluation/runs/{run_id}").status_code == 200
    results = authed_client.get(
        f"/api/v1/evaluation/results/{run_id}").json()["results"]
    assert len(results) == 3


def test_evaluation_requires_auth(app_client):
    response = app_client.post("/api/v1/evaluation/run",
                               json={"scenarios": ["clean"]})
    assert response.status_code == 401
