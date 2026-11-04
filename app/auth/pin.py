"""Argon2id PIN hashing and verification.

The raw PIN is never stored or logged. No default PIN exists: without a
configured hash, authentication fails closed. The argon2 dependency is
imported lazily so non-auth code paths work without it installed; any
actual PIN operation requires it.
"""

from __future__ import annotations


def _hasher():
    try:
        from argon2 import PasswordHasher
    except ImportError as exc:
        raise RuntimeError(
            "argon2-cffi is required for PIN operations. Install it with: "
            "pip install -e \".[dev]\"") from exc
    return PasswordHasher()


def hash_pin(pin: str) -> str:
    if not pin or len(pin) < 4:
        raise ValueError("PIN must be at least 4 characters")
    return _hasher().hash(pin)


def verify_pin(stored_hash: str | None, candidate: str) -> bool:
    if not stored_hash or not candidate:
        return False
    try:
        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError
    except ImportError:
        return False  # fail closed when the dependency is unavailable
    try:
        return bool(PasswordHasher().verify(stored_hash, candidate))
    except VerifyMismatchError:
        return False
    except Exception:
        return False
