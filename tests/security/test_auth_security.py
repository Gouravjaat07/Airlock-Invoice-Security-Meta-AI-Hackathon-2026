"""Security tests: lockout, expiry, replay, tamper, CSRF, rate limits."""

from __future__ import annotations

import sqlite3

from tests.conftest import upload_case


def test_pin_lockout_after_five_failures(app_client):
    for _ in range(5):
        response = app_client.post("/api/v1/auth/login",
                                   json={"pin": "wrong-pin"})
        assert response.status_code == 401
    locked = app_client.post("/api/v1/auth/login",
                             json={"pin": "wrong-pin"})
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "E_RATE_LIMIT"


def test_lockout_survives_header_rotation(app_client):
    """Regression (F1): rotating X-Forwarded-For must not bypass lockout."""
    for index in range(5):
        response = app_client.post(
            "/api/v1/auth/login", json={"pin": "wrong-pin"},
            headers={"X-Forwarded-For": f"10.9.9.{index}"})
        assert response.status_code == 401
    locked = app_client.post(
        "/api/v1/auth/login", json={"pin": "wrong-pin"},
        headers={"X-Forwarded-For": "10.9.9.99"})
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "E_RATE_LIMIT"


def test_expired_session_rejected(app_client, test_pin, settings):
    response = app_client.post("/api/v1/auth/login", json={"pin": test_pin})
    assert response.status_code == 200
    conn = sqlite3.connect(settings.db_path)
    try:
        conn.execute("UPDATE auth_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
        conn.commit()
    finally:
        conn.close()
    me = app_client.get("/api/v1/auth/me")
    assert me.status_code == 401


def test_challenge_bound_to_proposal(authed_client, test_pin):
    first = upload_case(authed_client, "invoices/clean.pdf")
    body = authed_client.post(
        f"/api/v1/cases/{first['case']['id']}/process").json()
    proposal_id = body["proposal"]["proposal_id"]
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    # Forge: use the challenge against a different proposal id path.
    response = authed_client.post(
        "/api/v1/proposals/prop_forged/challenge", json={})
    assert response.status_code == 404
    # Tamper with the stored proposal amount, then confirm must fail hash.
    import sqlite3 as _sqlite
    from app.config import get_settings
    settings = get_settings()
    conn = _sqlite.connect(settings.db_path)
    try:
        conn.execute("UPDATE proposals SET amount='9999.99' WHERE proposal_id=?",
                     (proposal_id,))
        conn.commit()
    finally:
        conn.close()
    confirm = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"], "pin": test_pin})
    assert confirm.status_code in (401, 409)


def test_challenge_single_use(authed_client, test_pin):
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process").json()
    proposal_id = body["proposal"]["proposal_id"]
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    ok = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": test_pin})
    assert ok.status_code == 200
    # A new challenge on a CONFIRMED proposal is refused.
    again = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={})
    assert again.status_code in (409, 410)


def test_expired_challenge_refused(authed_client, test_pin):
    import sqlite3 as _sqlite
    from app.config import get_settings
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process").json()
    proposal_id = body["proposal"]["proposal_id"]
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    settings = get_settings()
    from app.core.security import hash_token as _hash_token
    conn = _sqlite.connect(settings.db_path)
    try:
        conn.execute("UPDATE auth_challenges SET expires_at='2000-01-01T00:00:00+00:00'"
                     " WHERE challenge_hash=?",
                     (_hash_token(challenge["challenge_id"]),))
        conn.commit()
    finally:
        conn.close()
    response = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": test_pin})
    assert response.status_code == 410


def test_wrong_pin_confirmation_fails(authed_client):
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process").json()
    proposal_id = body["proposal"]["proposal_id"]
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    response = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": "wrong-pin"})
    assert response.status_code == 401


def test_csrf_enforced_for_cookie_mutations(app_client, test_pin):
    login = app_client.post("/api/v1/auth/login", json={"pin": test_pin})
    assert login.status_code == 200
    # No CSRF header on a cookie-authenticated mutation -> refused.
    response = app_client.post("/api/v1/vendors", json={
        "name": "CSRF Victim", "bank_reference": "SYN-X"})
    assert response.status_code in (401, 403)


def test_bearer_auth_skips_csrf(app_client, test_pin):
    login = app_client.post("/api/v1/auth/login", json={"pin": test_pin})
    assert login.status_code == 200
    raw_cookie = login.headers.get("set-cookie", "")
    token = raw_cookie.split("airlock_session=")[1].split(";")[0]
    app_client.cookies.clear()  # drop the cookie: pure Bearer request
    response = app_client.post("/api/v1/vendors",
                               headers={"Authorization": f"Bearer {token}"},
                               json={"name": "Bearer Vendor",
                                     "bank_reference": "SYN-BEARER-1"})
    assert response.status_code == 200, response.text


def test_session_rate_limit(app_client, test_pin, settings):
    settings.per_session_requests_per_minute = 3
    try:
        app_client.post("/api/v1/auth/login", json={"pin": test_pin})
        statuses = [app_client.get("/api/v1/auth/me").status_code
                    for _ in range(6)]
        assert 429 in statuses
    finally:
        settings.per_session_requests_per_minute = 30


def test_no_secrets_in_audit(app_client, authed_client, test_pin):
    created = upload_case(authed_client, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    authed_client.post(f"/api/v1/cases/{case_id}/process")
    events = authed_client.get(f"/api/v1/audit/{case_id}").json()["events"]
    blob = repr(events)
    assert test_pin not in blob
    assert "SYN-ACME-0001" not in blob  # raw bank reference never persisted
