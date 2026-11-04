"""Proposal service: safe views of deterministic proposals."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.pipeline.propose import verify_proposal_hash
from app.storage.repositories import ProposalRepository

_proposals = ProposalRepository()


def list_proposals(conn: sqlite3.Connection, *, limit: int,
                   offset: int) -> list[dict]:
    """Newest-first proposal rows for the owner console list view.

    Read-only display: row integrity is enforced on access/approval
    (get_proposal/require_pending), not here, so one corrupt row cannot
    break the whole listing.
    """
    return _proposals.list(conn, limit=limit, offset=offset)


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_proposal(conn: sqlite3.Connection, proposal_id: str) -> dict:
    row = _proposals.get(conn, proposal_id)
    if row is None:
        raise AppError(ErrorCode.SCHEMA, "Proposal not found", status=404)
    if not verify_proposal_hash(row):
        raise AppError(ErrorCode.CONFLICT, "Proposal failed integrity verification")
    return row


def require_pending(conn: sqlite3.Connection, proposal_id: str) -> dict:
    row = get_proposal(conn, proposal_id)
    if row["status"] != "PENDING":
        raise AppError(ErrorCode.STATE_TRANSITION,
                       f"Proposal is {row['status']}; only PENDING proposals can be approved")
    if SYSTEM_CLOCK.now() >= _parse_ts(str(row["expires_at"])):
        _proposals.set_status(conn, proposal_id, "EXPIRED")
        raise AppError(ErrorCode.EXPIRED, "Proposal expired", status=410)
    return row
