"""Strict extraction schema for invoice reader output.

Tainted (T2) even when schema-valid: structure never implies truth.
Money uses Decimal; NaN/Infinity/negative-where-forbidden are rejected.
Unknown critical fields are rejected (`extra="forbid"`).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_LINE_ITEMS = 200
MAX_TEXT_LEN = 500
CURRENCY_RE = r"^[A-Z]{3}$"


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=MAX_TEXT_LEN)
    quantity: Decimal = Field(ge=0)
    unit_price: Decimal = Field(ge=0)
    catalogue_item_id: str | None = Field(default=None, max_length=64)
    extracted_item_id: str | None = Field(default=None, max_length=64)

    @field_validator("quantity", "unit_price", mode="before")
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal:
        return parse_money(value, field_name="line item value")


def parse_money(value: object, *, field_name: str = "amount") -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    if isinstance(value, float):
        raise ValueError(f"{field_name} must not be a binary float")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if abs(parsed.as_tuple().exponent) > 6:
        raise ValueError(f"{field_name} has excessive precision")
    if abs(parsed) > Decimal("999999999999.99"):
        raise ValueError(f"{field_name} exceeds supported magnitude")
    return parsed


def parse_iso_date(value: object, *, field_name: str) -> dt.date:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string")
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc


class InvoiceExtraction(BaseModel):
    """Schema-validated (still tainted) reader output."""

    model_config = ConfigDict(extra="forbid")

    vendor_name: str = Field(min_length=1, max_length=MAX_TEXT_LEN)
    invoice_number: str = Field(min_length=1, max_length=64)
    issue_date: dt.date
    due_date: dt.date
    currency: str = Field(pattern=CURRENCY_RE)
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    bank_reference: str | None = Field(default=None, max_length=128)
    po_reference: str | None = Field(default=None, max_length=64)
    line_items: list[LineItem] = Field(min_length=1, max_length=MAX_LINE_ITEMS)

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def _money(cls, value: object) -> Decimal:
        return parse_money(value)

    @field_validator("issue_date", "due_date", mode="before")
    @classmethod
    def _date(cls, value: object) -> dt.date:
        return parse_iso_date(value, field_name="date")

    @field_validator("tax")
    @classmethod
    def _tax_non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("tax must be non-negative")
        return value

    @field_validator("subtotal", "total")
    @classmethod
    def _totals_non_negative(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("totals must be non-negative")
        return value
