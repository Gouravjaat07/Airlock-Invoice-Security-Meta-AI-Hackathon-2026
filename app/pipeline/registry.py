"""Trusted registry matching: exact/normalized vendor resolution.

Resolution is deterministic:
- R1 passes only on an exact normalized match with an active vendor.
- A vendor is *plausible* when its normalized name is within
  AMBIGUITY_DISTANCE edits of the extracted name (or exact).
- R10 escalates when more than one vendor is plausible -- including the
  branch-steering case where the invoice names one of two lookalikes
  exactly. Fuzzy candidates never resolve (fail closed, R1 DENY).
"""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass

from app.domain.vendors import normalize_vendor_name
from app.storage.repositories import VendorRepository

_vendors = VendorRepository()

AMBIGUITY_DISTANCE = 2


def levenshtein_cutoff(a: str, b: str, cutoff: int) -> int:
    """Edit distance with early exit above `cutoff` (small strings only)."""
    if abs(len(a) - len(b)) > cutoff:
        return cutoff + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            value = min(previous[j] + 1, current[j - 1] + 1,
                        previous[j - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > cutoff:
            return cutoff + 1
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class VendorMatch:
    vendor: dict | None
    candidates: list[dict]
    normalized: str

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


def resolve_vendor(conn: sqlite3.Connection, extracted_name: str) -> VendorMatch:
    normalized = normalize_vendor_name(extracted_name)
    exact = _vendors.get_by_norm(conn, normalized)
    vendor = exact if exact is not None and exact.get("status") == "active" else None
    candidates = [row for row in _vendors.all_active(conn)
                  if levenshtein_cutoff(normalized, str(row.get("name_norm", "")),
                                         AMBIGUITY_DISTANCE) <= AMBIGUITY_DISTANCE]
    if vendor is not None and all(c["vendor_id"] != vendor["vendor_id"]
                                  for c in candidates):
        candidates = [vendor, *candidates]
    return VendorMatch(vendor=vendor, candidates=candidates, normalized=normalized)


def normalize_invoice_number(value: str) -> str:
    """Canonical invoice-number form for the R4 duplicate key.

    NFKC collapses compatibility lookalikes (fullwidth digits, ligatures)
    so a duplicate cannot evade detection via Unicode variants; the
    result is whitespace-collapsed and uppercased.
    """
    text = unicodedata.normalize("NFKC", value)
    return " ".join(text.strip().split()).upper()
