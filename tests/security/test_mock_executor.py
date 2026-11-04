"""Security tests: mock executor preconditions, idempotency, concurrency."""

from __future__ import annotations

import threading

from tests.conftest import upload_case


def _approve(authed_client, test_pin, invoice="invoices/clean.pdf"):
    created = upload_case(authed_client, invoice)
    body = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process").json()
    proposal_id = body["proposal"]["proposal_id"]
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
    payment = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/confirm",
        json={"challenge_id": challenge["challenge_id"],
              "pin": test_pin}).json()
    return created["case"]["id"], proposal_id, payment


def test_no_proposal_no_payment(authed_client):
    created = upload_case(authed_client, "invoices/changed-bank.pdf")
    body = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process").json()
    assert body["verdict"]["verdict"] == "DENY"
    assert body["proposal"] is None
    assert body["payments"] == []


def test_escalate_no_payment(authed_client):
    created = upload_case(authed_client, "invoices/over-cap.pdf")
    body = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process").json()
    assert body["verdict"]["verdict"] == "ESCALATE"
    assert body["proposal"] is None


def test_payment_label_and_shape(authed_client, test_pin):
    _, _, payment = _approve(authed_client, test_pin)
    assert payment["mock"] is True
    assert payment["label"] == "MOCK PAYMENT \u2014 NO MONEY TRANSFERRED"
    assert payment["status"] == "MOCK_COMPLETED"
    assert payment["amount"] == "1240.00"


def test_idempotent_retry_returns_same_payment(authed_client, test_pin):
    case_id, proposal_id, payment = _approve(authed_client, test_pin)
    # Confirming again with a fresh challenge attempt is refused cleanly.
    challenge = authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={})
    assert challenge.status_code in (409, 410)
    listed = authed_client.get(
        f"/api/v1/cases/{case_id}/payments/mock").json()["payments"]
    assert len(listed) == 1
    assert listed[0]["payment_id"] == payment["payment_id"]


def test_concurrent_confirm_single_payment(authed_client, test_pin):
    import sqlite3 as _sqlite
    from app.config import get_settings
    created = upload_case(authed_client, "invoices/clean.pdf")
    body = authed_client.post(
        f"/api/v1/cases/{created['case']['id']}/process").json()
    proposal_id = body["proposal"]["proposal_id"]
    # Two challenges (both valid); race the two confirmations.
    challenges = [authed_client.post(
        f"/api/v1/proposals/{proposal_id}/challenge", json={}).json()
        ["challenge_id"] for _ in range(2)]
    results: list = []
    bodies: list = []
    settings = get_settings()

    def confirm(challenge_id):
        from app.main import create_app
        from tests.asgi_harness import ASGIClient
        client = ASGIClient(create_app())
        raw = authed_client.cookies.get("airlock_session")
        client.cookies["airlock_session"] = raw
        csrf = authed_client.headers["X-CSRF-Token"]
        response = client.post(
            f"/api/v1/proposals/{proposal_id}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={"challenge_id": challenge_id, "pin": test_pin})
        results.append(response.status_code)
        try:
            bodies.append(response.json())
        except Exception:
            bodies.append({})

    threads = [threading.Thread(target=confirm, args=(challenge,))
               for challenge in challenges]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    # Winner 200s; loser either 409s (saw CONFIRMED) or idempotently 200s
    # with the SAME payment. Exactly one payment row either way.
    assert sorted(results) in ([200, 200], [200, 409], [200, 401]), results
    if sorted(results) == [200, 200]:
        assert bodies[0].get("payment_id") == bodies[1].get("payment_id")
    conn = _sqlite.connect(settings.db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM mock_payments").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_no_network_in_executor_path(authed_client, test_pin, monkeypatch):
    import socket
    def _blocked(*args, **kwargs):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", _blocked)
    _, _, payment = _approve(authed_client, test_pin)
    assert payment["mock"] is True
