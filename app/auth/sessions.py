"""Opaque owner sessions: issuance, validation, revocation.

Only token/CSRF hashes are stored. Validation checks expiry, revocation,
and idle touch. Failures are generic (no oracle for token guessing).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.auth import rate_limit
from app.auth.pin import verify_pin
from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id, new_token
from app.core.security import constant_time_equal, hash_token
from app.storage.database import transaction
from app.storage.repositories import SessionRepository

_sessions = SessionRepository()


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


LOGIN_LOCK_SCOPE = "login:owner"
"""Global failed-PIN lockout scope.

Single-owner prototype: the lockout MUST NOT be keyed by client IP or
`X-Forwarded-For` (both are trivially rotated by a local caller, and no
trusted proxy is configured in Phase 2). A global bucket cannot be
bypassed by request variation; the trade-off (lockout DoS by a local
attacker) is documented in docs/phase2/AUTH.md.
"""


def login(conn: sqlite3.Connection, settings: Settings,
          pin: str) -> tuple[str, str, str]:
    """Verify PIN (rate-limited) and issue (session_id, token, csrf).

    Raises AppError(E_AUTH/E_RATE_LIMIT) with generic messages.
    """
    lock_key = LOGIN_LOCK_SCOPE
    if rate_limit.is_locked(conn, lock_key, limit=settings.login_max_attempts,
                            window_seconds=settings.lockout_minutes * 60):
        raise AppError(ErrorCode.RATE_LIMIT,
                       "Too many attempts. Try again later.", status=429)
    if not verify_pin(settings.pin_hash, pin):
        allowed, _ = rate_limit.record_failure(
            conn, lock_key, limit=settings.login_max_attempts,
            window_seconds=settings.lockout_minutes * 60)
        if not allowed:
            raise AppError(ErrorCode.RATE_LIMIT,
                           "Too many attempts. Try again later.", status=429)
        raise AppError(ErrorCode.AUTH, "Invalid credentials", status=401)
    rate_limit.clear(conn, lock_key)
    now = SYSTEM_CLOCK.now()
    expires = now + timedelta(minutes=settings.session_duration_minutes)
    session_id = new_id("sess")
    token = new_token()
    csrf = new_token(16)
    with transaction(conn):
        _sessions.create(conn, session_id=session_id,
                         token_hash=hash_token(token),
                         csrf_hash=hash_token(csrf),
                         now=now.isoformat(), expires_at=expires.isoformat())
    return session_id, token, csrf


def validate_session(conn: sqlite3.Connection, settings: Settings,
                     token: str | None) -> dict:
    if not token:
        raise AppError(ErrorCode.AUTH, "Authentication required", status=401)
    row = _sessions.get_by_token_hash(conn, hash_token(token))
    if row is None or not constant_time_equal(str(row["token_hash"]), hash_token(token)):
        raise AppError(ErrorCode.AUTH, "Invalid session", status=401)
    if row["revoked_at"] is not None:
        raise AppError(ErrorCode.AUTH, "Session revoked", status=401)
    if SYSTEM_CLOCK.now() >= _parse_ts(str(row["expires_at"])):
        raise AppError(ErrorCode.AUTH, "Session expired", status=401)
    _sessions.touch(conn, str(row["session_id"]), SYSTEM_CLOCK.now().isoformat())
    allowed, _ = rate_limit.check_and_hit(
        conn, f"session:{row['session_id']}",
        limit=settings.per_session_requests_per_minute, window_seconds=60)
    if not allowed:
        raise AppError(ErrorCode.RATE_LIMIT, "Rate limit exceeded", status=429)
    return row


def validate_csrf(session: dict, csrf_token: str | None, *, via_cookie: bool) -> None:
    """CSRF token required for cookie-authenticated mutations."""
    if not via_cookie:
        return
    if not csrf_token or not constant_time_equal(str(session["csrf_hash"]),
                                                 hash_token(csrf_token)):
        raise AppError(ErrorCode.AUTH, "Invalid CSRF token", status=403)


def logout(conn: sqlite3.Connection, session_id: str) -> None:
    with transaction(conn):
        _sessions.revoke(conn, session_id, SYSTEM_CLOCK.now().isoformat())


def rotate_csrf(conn: sqlite3.Connection, session_id: str) -> str:
    """Issue a fresh CSRF token for a validated session (old one dies).

    Session restore after a browser refresh needs this: only the CSRF
    *hash* is stored, so the previous raw token is unrecoverable. The
    caller must have validated the session first; the response is
    same-origin readable only by the session owner (SOP).
    """
    csrf = new_token(16)
    with transaction(conn):
        _sessions.set_csrf_hash(conn, session_id, hash_token(csrf))
    return csrf
