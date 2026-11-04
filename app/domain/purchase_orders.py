"""Purchase-order domain shape."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class PurchaseOrder:
    po_id: str
    vendor_id: str
    po_reference: str
    currency: str
    original_amount: Decimal
    remaining_amount: Decimal
    status: str = "open"
    version: int = 1
