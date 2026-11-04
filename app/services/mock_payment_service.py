"""Mock-only payment executor.

Writes a MOCK payment record to the local database. No network, no
provider, no credentials, no real-money behavior -- the result is always
labelled MOCK. Idempotent on the proposal hash: retries and concurrent
confirmations yield exactly one payment.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.adapters.payments import MOCK_LABEL
from app.auth import challenges
from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.domain.enums import ActorType, CaseState
from app.pipeline.propose import verify_proposal_hash
from app.pipeline.state_machine import check_transition
from app.services import audit_service
from app.storage.database import transaction
from app.storage.repositories import (
    CaseRepository,
    InvoiceIndexRepository,
    PaymentRepository,
    ProposalRepository,
)

_cases = CaseRepository()
_proposals = ProposalRepository()
_payments = PaymentRepository()
_index = InvoiceIndexRepository()


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def execute(conn: sqlite3.Connection, settings: Settings, proposal: dict, *,
            challenge_id: str, session_id: str) -> dict:
    proposal_id = str(proposal["proposal_id"])
    case_id = str(proposal["case_id"])
    proposal_hash = str(proposal["proposal_hash"])

    # Fast idempotent path: a retry after a committed payment returns it.
    existing = _payments.get_by_idempotency(conn, proposal_hash)
    if existing is not None:
        with transaction(conn):
            audit_service.record(
                conn, audit_service.APPROVAL_SUCCEEDED, case_id=case_id,
                actor_type=ActorType.OWNER, actor_id=session_id,
                payload={"proposal_id": proposal_id,
                         "payment_id": existing["payment_id"],
                         "retry": True})
        return _view(existing)

    with transaction(conn):
        fresh = _proposals.get(conn, proposal_id)
        if fresh is None or fresh["status"] != "PENDING":
            raise AppError(ErrorCode.STATE_TRANSITION,
                           "Proposal is no longer payable")
        if not verify_proposal_hash(fresh):
            raise AppError(ErrorCode.CONFLICT, "Proposal failed integrity verification")
        if SYSTEM_CLOCK.now() >= _parse_ts(str(fresh["expires_at"])):
            _proposals.set_status(conn, proposal_id, "EXPIRED")
            raise AppError(ErrorCode.EXPIRED, "Proposal expired", status=410)
        challenges.load_valid(conn, challenge_id, proposal_hash=proposal_hash,
                              session_id=session_id)
        challenges.consume(conn, challenge_id)
        # Second idempotency check inside the transaction (concurrent race).
        raced = _payments.get_by_idempotency(conn, proposal_hash)
        if raced is not None:
            raise AppError(ErrorCode.DUPLICATE,
                           "Payment already recorded for this proposal")
        now = SYSTEM_CLOCK.now().isoformat()
        payment_id = new_id("pay")
        try:
            _payments.create(conn, payment_id=payment_id,
                             proposal_id=proposal_id,
                             idempotency_key=proposal_hash,
                             proposal_hash=proposal_hash, case_id=case_id,
                             amount=str(fresh["amount"]),
                             currency=str(fresh["currency"]), now=now)
        except sqlite3.IntegrityError as exc:
            # Unique-violation race on the idempotency key.
            raise AppError(ErrorCode.DUPLICATE,
                           "Payment already recorded for this proposal") from exc
        _proposals.set_status(conn, proposal_id, "CONFIRMED")
        case = _cases.get(conn, case_id)
        assert case is not None
        for nxt in (CaseState.CONFIRMED, CaseState.EXECUTED):
            check_transition(CaseState(case["state"]), nxt)
            ok = _cases.update_state(conn, case_id=case_id, state=nxt.value,
                                     now=now,
                                     expected_version=int(case["version"]))
            if not ok:
                raise AppError(ErrorCode.CONFLICT, "Case modified concurrently")
            case = _cases.get(conn, case_id)
            assert case is not None
        _cases.mark_completed(conn, case_id=case_id, now=now)
        for row in conn.execute(
                "SELECT dup_key FROM invoice_index WHERE case_id = ? AND status = 'proposed'",
                (case_id,)).fetchall():
            _index.mark_paid(conn, str(row[0]))
        audit_service.record(conn, audit_service.APPROVAL_SUCCEEDED,
                             case_id=case_id, actor_type=ActorType.OWNER,
                             actor_id=session_id,
                             payload={"proposal_id": proposal_id})
        audit_service.record(conn, audit_service.MOCK_PAYMENT_EXECUTED,
                             case_id=case_id, actor_type=ActorType.SYSTEM,
                             payload={"payment_id": payment_id,
                                      "proposal_id": proposal_id,
                                      "mock": True})
    stored = _payments.get(conn, payment_id)
    assert stored is not None
    return _view(stored)


def _view(payment: dict) -> dict:
    return {
        "payment_id": payment["payment_id"],
        "proposal_id": payment["proposal_id"],
        "case_id": payment["case_id"],
        "amount": payment["amount"],
        "currency": payment["currency"],
        "executed_at": payment["executed_at"],
        "status": payment["status"],
        "label": MOCK_LABEL,
        "mock": True,
    }


def get_payment(conn: sqlite3.Connection, payment_id: str) -> dict:
    row = _payments.get(conn, payment_id)
    if row is None:
        raise AppError(ErrorCode.SCHEMA, "Payment not found", status=404)
    return _view(row)


def list_for_case(conn: sqlite3.Connection, case_id: str) -> list[dict]:
    return [_view(row) for row in _payments.list_for_case(conn, case_id)]
