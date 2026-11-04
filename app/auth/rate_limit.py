"""Database-backed rate limiting and lockout.

Fixed windows in the `rate_limits` table (multi-process safe, unlike an
in-memory dict). `check_and_hit` returns (allowed, retry_after_seconds).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.core.clock import SYSTEM_CLOCK
from app.storage.repositories import RateLimitRepository

_repo = RateLimitRepository()


def _now() -> datetime:
    return SYSTEM_CLOCK.now()


def check_and_hit(conn: sqlite3.Connection, scope_key: str, *, limit: int,
                  window_seconds: int) -> tuple[bool, int]:
    now = _now()
    row = _repo.get(conn, scope_key)
    if row is None:
        _repo.upsert(conn, scope_key=scope_key,
                     window_start=now.isoformat(), count=1)
        return True, 0
    start = datetime.fromisoformat(str(row["window_start"]))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if (now - start).total_seconds() >= window_seconds:
        _repo.upsert(conn, scope_key=scope_key,
                     window_start=now.isoformat(), count=1)
        return True, 0
    count = int(row["count"])
    if count >= limit:
        retry = int(window_seconds - (now - start).total_seconds()) + 1
        return False, max(retry, 1)
    _repo.upsert(conn, scope_key=scope_key,
                 window_start=row["window_start"], count=count + 1)
    return True, 0


def record_failure(conn: sqlite3.Connection, scope_key: str, *, limit: int,
                   window_seconds: int) -> tuple[bool, int]:
    """Count one failure; False means the scope just locked out."""
    return check_and_hit(conn, scope_key, limit=limit, window_seconds=window_seconds)


def is_locked(conn: sqlite3.Connection, scope_key: str, *, limit: int,
              window_seconds: int) -> bool:
    row = _repo.get(conn, scope_key)
    if row is None:
        return False
    start = datetime.fromisoformat(str(row["window_start"]))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if (_now() - start).total_seconds() >= window_seconds:
        return False
    return int(row["count"]) >= limit


def clear(conn: sqlite3.Connection, scope_key: str) -> None:
    _repo.reset(conn, scope_key)


def lockout_until(scope_key: str, *, window_seconds: int) -> datetime:
    return _now() + timedelta(seconds=window_seconds)
