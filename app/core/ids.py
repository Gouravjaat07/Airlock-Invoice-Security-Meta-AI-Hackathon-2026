"""Server-generated opaque identifiers.

All ids are unguessable random tokens (URL-safe) or time-ordered
human-readable ids with a random suffix. Client input is never used
as an identifier or storage key.
"""

from __future__ import annotations

import secrets
import time


def new_id(prefix: str) -> str:
    """Time-ordered id: <prefix>_<base36 millis>_<random 8 hex>."""
    millis = int(time.time() * 1000)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    value = millis
    while value > 0:
        value, rem = divmod(value, 36)
        encoded = digits[rem] + encoded
    return f"{prefix}_{encoded or '0'}_{secrets.token_hex(4)}"


def new_token(nbytes: int = 32) -> str:
    """Unguessable opaque token (session, challenge, CSRF)."""
    return secrets.token_urlsafe(nbytes)
