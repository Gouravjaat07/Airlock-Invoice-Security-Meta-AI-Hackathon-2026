"""Vendor domain: normalization and trusted-record shape."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

_WS_RUN = re.compile(r"\s+")
# Punctuation stripped for name matching (kept out of the stored norm form).
_PUNCT = re.compile(r"[!\"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~]+")


def normalize_vendor_name(name: str) -> str:
    """Deterministic vendor-name normalization.

    NFKC, casefold, collapse whitespace, strip, remove punctuation runs.
    Fuzzy matching is never used to approve; ambiguity escalates (R10).
    """
    text = unicodedata.normalize("NFKC", name)
    text = text.casefold()
    text = _WS_RUN.sub(" ", text).strip()
    text = _PUNCT.sub("", text)
    return _WS_RUN.sub(" ", text).strip()


@dataclass
class CatalogueItem:
    item_id: str
    label: str
    tolerance: int = 0


@dataclass
class Vendor:
    vendor_id: str
    name: str
    name_norm: str
    active_bank_fingerprint: str
    catalogue: list[CatalogueItem] = field(default_factory=list)
    per_invoice_cap: Decimal | None = None
    status: str = "active"
    version: int = 1
