"""Approval service: challenge issuance + PIN-bound confirmation.

Confirmation re-verifies everything: session, challenge binding/expiry/
single-use, PIN, proposal hash/expiry, and the still-current ALLOW
verdict. Execution itself is delegated to the mock payment service in
the same transaction.
"""

from __future__ import annotations

import sqlite3

from app.auth import challenges, rate_limit
from app.auth.pin import verify_pin
from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.domain.enums import ActorType
from app.services import audit_service, mock_payment_service, proposal_service
from app.storage.database import transaction
from app.storage.repositories import VerdictRepository

_verdicts = VerdictRepository()


def issue_challenge(conn: sqlite3.Connection, settings: Settings,
                    proposal_id: str, *, session_id: str) -> dict:
    proposal = proposal_service.require_pending(conn, proposal_id)
    allowed, _ = rate_limit.check_and_hit(
        conn, f"challenge:{session_id}:{proposal_id}", limit=10,
        window_seconds=60)
    if not allowed:
        raise AppError(ErrorCode.RATE_LIMIT, "Challenge rate exceeded", status=429)
    challenge_id = challenges.issue(conn, settings,
                                    proposal_hash=str(proposal["proposal_hash"]),
                                    session_id=session_id)
    with transaction(conn):
        audit_service.record(conn, audit_service.CHALLENGE_CREATED,
                             case_id=str(proposal["case_id"]),
                             actor_type=ActorType.OWNER, actor_id=session_id,
                             payload={"proposal_id": proposal_id})
    return {"challenge_id": challenge_id,
            "proposal_hash": proposal["proposal_hash"],
            "expires_in_minutes": settings.challenge_duration_minutes,
            "proposal": proposal}


def confirm(conn: sqlite3.Connection, settings: Settings, proposal_id: str, *,
            challenge_id: str, pin: str, session_id: str) -> dict:
    proposal = proposal_service.require_pending(conn, proposal_id)
    case_id = str(proposal["case_id"])
    lock_key = f"confirm:{session_id}:{proposal_id}"
    try:
        if rate_limit.is_locked(conn, lock_key, limit=settings.login_max_attempts,
                                window_seconds=settings.lockout_minutes * 60):
            raise AppError(ErrorCode.RATE_LIMIT, "Too many attempts. Try again later.")
        challenges.load_valid(conn, challenge_id,
                              proposal_hash=str(proposal["proposal_hash"]),
                              session_id=session_id)
        if not verify_pin(settings.pin_hash, pin):
            allowed, _ = rate_limit.record_failure(
                conn, lock_key, limit=settings.login_max_attempts,
                window_seconds=settings.lockout_minutes * 60)
            challenges.record_failure(conn, challenge_id)
            with transaction(conn):
                audit_service.record(conn, audit_service.APPROVAL_FAILED,
                                     case_id=case_id,
                                     actor_type=ActorType.OWNER,
                                     actor_id=session_id,
                                     payload={"proposal_id": proposal_id,
                                              "reason": "pin-mismatch"})
            if not allowed:
                raise AppError(ErrorCode.RATE_LIMIT, "Too many attempts. Try again later.")
            raise AppError(ErrorCode.AUTH, "Approval failed", status=401)
        verdict = _verdicts.latest_for_case(conn, case_id)
        if verdict is None or verdict["verdict"] != "ALLOW_PROPOSAL":
            raise AppError(ErrorCode.POLICY_DENY,
                           "Current verdict does not allow a proposal")
        if str(verdict["verdict_id"]) != str(proposal["verdict_id"]):
            raise AppError(ErrorCode.POLICY_DENY,
                           "Proposal verdict is stale; reprocessing superseded it")
        payment = mock_payment_service.execute(
            conn, settings, proposal, challenge_id=challenge_id,
            session_id=session_id)
        rate_limit.clear(conn, lock_key)
        return payment
    except AppError as exc:
        if exc.code not in (ErrorCode.AUTH, ErrorCode.RATE_LIMIT):
            with transaction(conn):
                audit_service.record(conn, audit_service.APPROVAL_FAILED,
                                     case_id=case_id,
                                     actor_type=ActorType.OWNER,
                                     actor_id=session_id,
                                     payload={"proposal_id": proposal_id,
                                              "reason": exc.code})
        raise
