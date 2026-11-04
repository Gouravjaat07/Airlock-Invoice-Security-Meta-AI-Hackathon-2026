"""Clock abstraction (injectable for expiry tests)."""

from __future__ import annotations

from datetime import datetime, timezone


class Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


SYSTEM_CLOCK = Clock()


def utc_now_iso() -> str:
    return SYSTEM_CLOCK.now().isoformat()
