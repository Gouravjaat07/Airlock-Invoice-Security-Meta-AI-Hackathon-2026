"""Proposal-bound one-time approval challenges.

A challenge binds (proposal_hash, session_id) with a short expiry and is
consumed transactionally at confirmation. Challenges never transfer
across proposals, sessions, or cases.

The bearer (`ch_...`) is returned once at issuance; only its SHA-256 is
stored (migration 003), like session/CSRF tokens.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_token
from app.core.security import constant_time_equal, hash_token
from app.storage.database import transaction
from app.storage.repositories import ChallengeRepository

repo = ChallengeRepository()


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def issue(conn: sqlite3.Connection, settings: Settings, *, proposal_hash: str,
          session_id: str) -> str:
    """Create a challenge; returns the high-entropy challenge id (bearer)."""
    now = SYSTEM_CLOCK.now()
    expires = now + timedelta(minutes=settings.challenge_duration_minutes)
    challenge_id = f"ch_{new_token(24)}"
    with transaction(conn):
        repo.create(conn, challenge_hash=hash_token(challenge_id),
                    proposal_hash=proposal_hash,
                    session_id=session_id, now=now.isoformat(),
                    expires_at=expires.isoformat())
    return challenge_id


def load_valid(conn: sqlite3.Connection, challenge_id: str, *,
               proposal_hash: str, session_id: str) -> dict:
    """Load a challenge valid for this exact proposal+session, unexpired/unused."""
    row = repo.get(conn, hash_token(challenge_id))
    if row is None:
        raise AppError(ErrorCode.AUTH, "Invalid approval challenge", status=401)
    if not constant_time_equal(str(row["proposal_hash"]), proposal_hash) \
            or not constant_time_equal(str(row["session_id"]), session_id):
        raise AppError(ErrorCode.AUTH, "Challenge does not match this approval",
                       status=401)
    if row["used_at"] is not None:
        raise AppError(ErrorCode.AUTH, "Challenge already used", status=401)
    if SYSTEM_CLOCK.now() >= _parse_ts(str(row["expires_at"])):
        raise AppError(ErrorCode.EXPIRED, "Approval challenge expired", status=410)
    return row


def consume(conn: sqlite3.Connection, challenge_id: str) -> None:
    """Mark used inside the caller's transaction; fails when already used."""
    if not repo.mark_used(conn, hash_token(challenge_id),
                           SYSTEM_CLOCK.now().isoformat()):
        raise AppError(ErrorCode.AUTH, "Challenge already used", status=401)


def record_failure(conn: sqlite3.Connection, challenge_id: str) -> None:
    """Count one failed attempt against the challenge (hash at boundary)."""
    repo.increment_failures(conn, hash_token(challenge_id))
