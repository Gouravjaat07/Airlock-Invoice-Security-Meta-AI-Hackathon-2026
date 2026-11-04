"""Security primitives: token hashing, bank fingerprints, comparisons.

- Session/challenge tokens: SHA-256 of the opaque token is stored; the
  raw token is shown once at issuance and compared in constant time.
- Bank references: HMAC-SHA-256 with a dedicated secret key (never plain
  SHA-256 over low-entropy identifiers). Raw values are transient only.
"""

from __future__ import annotations

import hashlib
import hmac
import unicodedata

BANK_FINGERPRINT_VERSION = "v1"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def normalize_bank_reference(value: str) -> str:
    """Deterministic normalization before fingerprinting."""
    text = unicodedata.normalize("NFKC", value).strip().upper()
    return "".join(ch for ch in text if not ch.isspace() and ch != "-")


def bank_fingerprint(reference: str, key: bytes) -> str:
    """Keyed fingerprint `v1:<hex>`; raises ValueError on empty key/reference."""
    if not key:
        raise ValueError("bank fingerprint key is missing")
    normalized = normalize_bank_reference(reference)
    if not normalized:
        raise ValueError("bank reference is empty")
    digest = hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{BANK_FINGERPRINT_VERSION}:{digest}"
