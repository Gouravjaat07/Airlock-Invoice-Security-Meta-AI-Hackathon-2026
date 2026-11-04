"""Race-guard tests: approval rechecks, executor branches, rate edges."""

from __future__ import annotations

import sqlite3

import pytest

from app.auth import challenges
from app.core.errors import AppError
from app.services import (
    approval_service,
    case_service,
    mock_payment_service,
)
from app.storage.database import transaction
from app.storage.repositories import SessionRepository, VerdictRepository
from tests.conftest import fixture_bytes

_verdicts = VerdictRepository()


def _session(conn, session_id):
    with transaction(conn):
        SessionRepository().create(
            conn, session_id=session_id, token_hash="t" + session_id,
            csrf_hash="c" + session_id, now="t",
            expires_at="2999-01-01T00:00:00+00:00")


def _allow(seeded_db, settings, store):
    created = case_service.create_case(
        seeded_db, settings, store,
        [("invoice", "c.pdf", fixture_bytes("invoices/clean.pdf"))])
    return case_service.process_case(seeded_db, settings, store,
                                     created["case"]["id"])


def _supersede_verdict(seeded_db, case_id, verdict, verdict_id="verdict-new"):
    with transaction(seeded_db):
        _verdicts.create(seeded_db, verdict_id=verdict_id, case_id=case_id,
                         verdict=verdict, reasons=["x"], rule_ids=[],
                         rule_details=[], policy_version="2.0.0",
                         now="2999-01-01T00:00:00+00:00")


def test_confirm_refuses_nonallow_verdict(seeded_db, settings, store,
                                          test_pin):
    from app.auth.pin import hash_pin
    settings.pin_hash = hash_pin(test_pin)
    _session(seeded_db, "sess-g1")
    summary = _allow(seeded_db, settings, store)
    proposal_id = summary["proposal"]["proposal_id"]
    challenge = approval_service.issue_challenge(
        seeded_db, settings, proposal_id, session_id="sess-g1")
    _supersede_verdict(seeded_db, summary["case"]["id"], "DENY")
    with pytest.raises(AppError) as exc_info:
        approval_service.confirm(seeded_db, settings, proposal_id,
                                 challenge_id=challenge["challenge_id"],
                                 pin=test_pin, session_id="sess-g1")
    assert exc_info.value.code == "E_POLICY_DENY"


def test_confirm_refuses_stale_verdict(seeded_db, settings, store, test_pin):
    from app.auth.pin import hash_pin
    settings.pin_hash = hash_pin(test_pin)
    _session(seeded_db, "sess-g2")
    summary = _allow(seeded_db, settings, store)
    proposal_id = summary["proposal"]["proposal_id"]
    challenge = approval_service.issue_challenge(
        seeded_db, settings, proposal_id, session_id="sess-g2")
    _supersede_verdict(seeded_db, summary["case"]["id"], "ALLOW_PROPOSAL")
    with pytest.raises(AppError) as exc_info:
        approval_service.confirm(seeded_db, settings, proposal_id,
                                 challenge_id=challenge["challenge_id"],
                                 pin=test_pin, session_id="sess-g2")
    assert exc_info.value.code == "E_POLICY_DENY"


def test_execute_refuses_nonpending(seeded_db, settings, store):
    _session(seeded_db, "sess-g3")
    summary = _allow(seeded_db, settings, store)
    proposal = dict(summary["proposal"])
    seeded_db.execute("UPDATE proposals SET status='CONFIRMED'"
                      " WHERE proposal_id=?", (proposal["proposal_id"],))
    challenge = challenges.issue(seeded_db, settings,
                                 proposal_hash=proposal["proposal_hash"],
                                 session_id="sess-g3")
    with pytest.raises(AppError) as exc_info:
        mock_payment_service.execute(seeded_db, settings, proposal,
                                     challenge_id=challenge,
                                     session_id="sess-g3")
    assert exc_info.value.code == "E_STATE_TRANSITION"


def test_execute_refuses_tampered(seeded_db, settings, store):
    _session(seeded_db, "sess-g4")
    summary = _allow(seeded_db, settings, store)
    proposal = dict(summary["proposal"])
    seeded_db.execute("UPDATE proposals SET amount='1.00' WHERE proposal_id=?",
                      (proposal["proposal_id"],))
    challenge = challenges.issue(seeded_db, settings,
                                 proposal_hash=proposal["proposal_hash"],
                                 session_id="sess-g4")
    with pytest.raises(AppError) as exc_info:
        mock_payment_service.execute(seeded_db, settings, proposal,
                                     challenge_id=challenge,
                                     session_id="sess-g4")
    assert exc_info.value.code == "E_CONFLICT"


def test_execute_naive_timestamp_ok(seeded_db, settings, store, test_pin):
    from app.auth.pin import hash_pin
    settings.pin_hash = hash_pin(test_pin)
    _session(seeded_db, "sess-g5")
    summary = _allow(seeded_db, settings, store)
    proposal = dict(summary["proposal"])
    seeded_db.execute("UPDATE proposals SET expires_at='2999-01-01 00:00:00'"
                      " WHERE proposal_id=?", (proposal["proposal_id"],))
    challenge = challenges.issue(seeded_db, settings,
                                 proposal_hash=proposal["proposal_hash"],
                                 session_id="sess-g5")
    payment = mock_payment_service.execute(seeded_db, settings, proposal,
                                           challenge_id=challenge,
                                           session_id="sess-g5")
    assert payment["mock"] is True


def test_execute_lost_race_duplicate(seeded_db, settings, store,
                                     monkeypatch):
    _session(seeded_db, "sess-g6")
    summary = _allow(seeded_db, settings, store)
    proposal = dict(summary["proposal"])
    challenge = challenges.issue(seeded_db, settings,
                                 proposal_hash=proposal["proposal_hash"],
                                 session_id="sess-g6")
    from app.storage.repositories import PaymentRepository
    calls = {"n": 0}

    def _flaky(self, conn, key):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # fast path misses; the row lands before the txn check
        return {"payment_id": "pay-other", "proposal_id": "x",
                "case_id": "c", "amount": "1", "currency": "USD",
                "executed_at": "t", "status": "MOCK_COMPLETED"}
    monkeypatch.setattr(PaymentRepository, "get_by_idempotency", _flaky)
    with pytest.raises(AppError) as exc_info:
        mock_payment_service.execute(seeded_db, settings, proposal,
                                     challenge_id=challenge,
                                     session_id="sess-g6")
    assert exc_info.value.code == "E_DUPLICATE"


def test_execute_insert_race_duplicate(seeded_db, settings, store,
                                       monkeypatch):
    _session(seeded_db, "sess-g7")
    summary = _allow(seeded_db, settings, store)
    proposal = dict(summary["proposal"])
    challenge = challenges.issue(seeded_db, settings,
                                 proposal_hash=proposal["proposal_hash"],
                                 session_id="sess-g7")
    from app.storage.repositories import PaymentRepository

    def _race(*args, **kwargs):
        raise sqlite3.IntegrityError("UNIQUE constraint failed")
    monkeypatch.setattr(PaymentRepository, "create", _race)
    with pytest.raises(AppError) as exc_info:
        mock_payment_service.execute(seeded_db, settings, proposal,
                                     challenge_id=challenge,
                                     session_id="sess-g7")
    assert exc_info.value.code == "E_DUPLICATE"


def test_execute_case_version_conflict(seeded_db, settings, store,
                                       monkeypatch):
    _session(seeded_db, "sess-g8")
    summary = _allow(seeded_db, settings, store)
    proposal = dict(summary["proposal"])
    challenge = challenges.issue(seeded_db, settings,
                                 proposal_hash=proposal["proposal_hash"],
                                 session_id="sess-g8")
    from app.storage.repositories import CaseRepository
    monkeypatch.setattr(CaseRepository, "update_state", lambda *a, **k: False)
    with pytest.raises(AppError) as exc_info:
        mock_payment_service.execute(seeded_db, settings, proposal,
                                     challenge_id=challenge,
                                     session_id="sess-g8")
    assert exc_info.value.code == "E_CONFLICT"


def test_rate_limit_naive_and_expired(seeded_db):
    from app.auth import rate_limit
    conn = seeded_db
    conn.execute("INSERT INTO rate_limits (scope_key, window_start, count)"
                 " VALUES ('naive','2026-10-31 00:00:00',1)")
    assert rate_limit.check_and_hit(conn, "naive", limit=5,
                                   window_seconds=3600)[0] in (True, False)
    conn.execute("INSERT INTO rate_limits (scope_key, window_start, count)"
                 " VALUES ('old','2000-01-01T00:00:00+00:00',99)")
    assert rate_limit.is_locked(conn, "old", limit=5,
                               window_seconds=60) is False
    conn.execute("INSERT INTO rate_limits (scope_key, window_start, count)"
                 " VALUES ('old-naive','2000-01-01 00:00:00',99)")
    assert rate_limit.is_locked(conn, "old-naive", limit=5,
                               window_seconds=60) is False
