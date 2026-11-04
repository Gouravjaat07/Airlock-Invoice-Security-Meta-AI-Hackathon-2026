"""End-to-end workflows W1-W16 over the real API + database."""

from __future__ import annotations

import json
import sqlite3


from tests.conftest import upload_case


def _process(client, case_id):
    response = client.post(f"/api/v1/cases/{case_id}/process")
    assert response.status_code == 200, response.text
    return response.json()


def _approve(client, pin, proposal_id):
    challenge = client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    return client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"], "pin": pin})


def _audit_ok(client, case_id):
    events = client.get(f"/api/v1/audit/{case_id}").json()["events"]
    assert events
    return client.post("/api/v1/audit/verify").json()["ok"] is True


def test_w01_clean_full_flow(authed_client, test_pin):
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    payment = _approve(authed_client, test_pin,
                       body["proposal"]["proposal_id"]).json()
    assert payment["mock"] is True
    assert _audit_ok(authed_client, created["case"]["id"])


def test_w02_bank_changed_denies(authed_client, test_pin):
    created = upload_case(authed_client, "invoices/changed-bank.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "DENY"
    assert "R2" in json.loads(body["verdict"]["rule_ids_json"])
    assert body["proposal"] is None
    assert "ALLOW" not in (body["explanation"] or "")
    assert _audit_ok(authed_client, created["case"]["id"])


def test_w03_arithmetic_denies(authed_client):
    created = upload_case(authed_client, "invoices/arithmetic-mismatch.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "DENY"


def test_w04_duplicate_denies(authed_client):
    first = upload_case(authed_client, "invoices/clean.pdf")
    _process(authed_client, first["case"]["id"])
    second = upload_case(authed_client, "invoices/clean.pdf")
    body = _process(authed_client, second["case"]["id"])
    assert body["verdict"]["verdict"] == "DENY"


def test_w05_over_cap_escalates(authed_client):
    created = upload_case(authed_client, "invoices/over-cap.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "ESCALATE"
    assert body["proposal"] is None


def test_w06_invalid_due_escalates(authed_client):
    created = upload_case(authed_client, "invoices/invalid-due.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "ESCALATE"


def test_w07_ambiguous_vendor_escalates(authed_client):
    created = upload_case(authed_client, "invoices/ambiguous-vendor.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "ESCALATE"
    assert "R10" in json.loads(body["verdict"]["rule_ids_json"])


def test_w08_sam_conflict_escalates(authed_client):
    created = upload_case(authed_client, "invoices/sam-conflict.pdf",
                          delivery="delivery/sam-conflict.png")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "ESCALATE"
    assert "fraud" not in (body["explanation"] or "").lower()


def test_w09_missing_field_denies(authed_client):
    created = upload_case(authed_client, "invoices/missing-field.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "DENY"


def test_w10_verifier_error_denies(authed_client):
    created = upload_case(authed_client, "invoices/verifier-timeout.pdf",
                          delivery="delivery/verifier-timeout.png")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "DENY"


def test_w11_prompt_injection_inert(authed_client, test_pin):
    created = upload_case(authed_client, "invoices/injection-visible.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    assert body["proposal"]["vendor_id"] == "ven-acme-flour"


def test_w12_owner_correction(authed_client):
    created = upload_case(authed_client,
                          "invoices/arithmetic-mismatch.pdf")
    body = _process(authed_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "DENY"
    total = next(f for f in body["facts"] if f["field"] == "total")
    fixed = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/facts/{total['id']}/edit",
        json={"value": "1240.00"}).json()
    assert fixed["verdict"]["verdict"] == "ALLOW_PROPOSAL"


def test_w13_approval_replay_single_payment(authed_client, test_pin):
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = _process(authed_client, created["case"]["id"])
    proposal_id = body["proposal"]["proposal_id"]
    first = _approve(authed_client, test_pin, proposal_id)
    assert first.status_code == 200
    payments = authed_client.get(
        f"/api/v1/cases/{created['case']['id']}/payments/mock").json()
    assert len(payments["payments"]) == 1


def test_w14_proposal_tampering_blocked(authed_client, test_pin, settings):
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = _process(authed_client, created["case"]["id"])
    proposal_id = body["proposal"]["proposal_id"]
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    conn = sqlite3.connect(settings.db_path)
    try:
        conn.execute("UPDATE proposals SET amount='1.00' WHERE proposal_id=?",
                     (proposal_id,))
        conn.commit()
    finally:
        conn.close()
    response = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": test_pin})
    assert response.status_code in (401, 409)


def test_w15_expired_challenge_blocked(authed_client, test_pin, settings):
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = _process(authed_client, created["case"]["id"])
    proposal_id = body["proposal"]["proposal_id"]
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    from app.core.security import hash_token
    conn = sqlite3.connect(settings.db_path)
    try:
        conn.execute("UPDATE auth_challenges SET expires_at='2000-01-01T00:00:00+00:00'"
                     " WHERE challenge_hash=?",
                     (hash_token(challenge["challenge_id"]),))
        conn.commit()
    finally:
        conn.close()
    response = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": test_pin})
    assert response.status_code == 410


def test_w16_unavailable_provider_labeled(app_client):
    created = upload_case(app_client, "invoices/clean.pdf")
    body = _process(app_client, created["case"]["id"])
    assert body["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    # No live-model claims anywhere in the deterministic output.
    blob = json.dumps(body)
    assert "Muse Spark" not in blob and "Glimmer" not in blob
