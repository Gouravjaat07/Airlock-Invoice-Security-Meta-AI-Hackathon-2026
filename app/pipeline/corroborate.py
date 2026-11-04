"""Deterministic corroboration engine.

Inputs: tainted extraction + trusted registry/PO/duplicate-index state +
optional SAM evidence + owner corrections. Output: field-level statuses
(CONFIRMED/CONFLICT/UNCONFIRMED/NOT_PROVIDED/NOT_APPLICABLE) with the
validators that actually ran. Model agreement is never confirmation.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.config import Settings
from app.core.security import bank_fingerprint, constant_time_equal
from app.domain.enums import FieldStatus
from app.domain.purchase_orders import PurchaseOrder
from app.pipeline.evidence import LaneOutcome, LaneStatus
from app.pipeline.registry import VendorMatch, normalize_invoice_number
from app.schemas.invoice import InvoiceExtraction
from app.storage.repositories import InvoiceIndexRepository, PurchaseOrderRepository

_index = InvoiceIndexRepository()
_pos = PurchaseOrderRepository()

MONEY_FIELDS = ("subtotal", "tax", "total")


@dataclass
class FieldOutcome:
    field: str
    status: FieldStatus
    validators: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class Corroboration:
    outcomes: dict[str, FieldOutcome]
    vendor_match: VendorMatch
    bank_match: bool | None  # None when no bank reference provided
    arithmetic_ok: bool | None
    duplicate_hit: dict | None
    po_record: PurchaseOrder | None
    po_ok: bool | None
    sam_ok: bool | None
    verifier_errors: list[str] = field(default_factory=list)


def quantize_money(value: Decimal, precision: int) -> Decimal:
    quantum = Decimal(1).scaleb(-precision)
    return value.quantize(quantum)


def check_arithmetic(extraction: InvoiceExtraction, precision: int) -> tuple[bool, str]:
    """Exact Decimal check: sum(qty*price)==subtotal and subtotal+tax==total."""
    try:
        line_sum = sum((item.quantity * item.unit_price for item in extraction.line_items),
                       Decimal("0"))
        subtotal = quantize_money(extraction.subtotal, precision)
        tax = quantize_money(extraction.tax, precision)
        total = quantize_money(extraction.total, precision)
        lines = quantize_money(line_sum, precision)
    except (InvalidOperation, ArithmeticError) as exc:  # pragma: no cover
        # Defensive: parse_money bounds magnitude/precision, so quantize
        # cannot fail on schema-valid input. Fail closed if it ever does.
        return False, f"arithmetic error: {exc}"
    if lines != subtotal:
        return False, f"line sum {lines} != subtotal {subtotal}"
    if subtotal + tax != total:
        return False, f"subtotal {subtotal} + tax {tax} != total {total}"
    return True, "exact"


def duplicate_key(*, vendor_id: str, invoice_number: str, total: Decimal,
                  issue_date: dt.date, precision: int) -> str:
    """Canonical R4 composite key (dup_key)."""
    number = normalize_invoice_number(invoice_number)
    amount = str(quantize_money(total, precision))
    return f"{vendor_id}|{number}|{amount}|{issue_date.isoformat()}"


def corroborate(conn: sqlite3.Connection, settings: Settings,
                extraction: InvoiceExtraction, vendor_match: VendorMatch,
                *, sam_count: int | None = None,
                sam_item_tolerance: int | None = None,
                sam_error: str | None = None,
                voice_conflicts: bool = False,
                presented_bank_fp: str | None = None,
                voice_lane: LaneOutcome | None = None,
                sam_lane: LaneOutcome | None = None) -> Corroboration:
    """`presented_bank_fp`: pre-computed fingerprint for the reprocess path
    (owner facts store fingerprints, never raw references)."""
    outcomes: dict[str, FieldOutcome] = {}
    verifier_errors: list[str] = []

    # Vendor identity (R1/R10 inputs).
    if vendor_match.vendor is not None:
        outcomes["vendor"] = FieldOutcome("vendor", FieldStatus.CONFIRMED,
                                          ["registry-exact"], "registry match")
    elif vendor_match.ambiguous:
        outcomes["vendor"] = FieldOutcome(
            "vendor", FieldStatus.CONFLICT, ["registry-ambiguity"],
            f"{len(vendor_match.candidates)} plausible vendors")
    else:
        outcomes["vendor"] = FieldOutcome("vendor", FieldStatus.UNCONFIRMED,
                                          ["registry-exact"], "no registry match")

    # Bank fingerprint (R2 input). Raw reference is transient; only compare.
    bank_match: bool | None = None
    if presented_bank_fp is not None and vendor_match.vendor is not None:
        bank_match = constant_time_equal(
            str(presented_bank_fp),
            str(vendor_match.vendor.get("active_bank_fingerprint")))
        outcomes["bank"] = FieldOutcome(
            "bank", FieldStatus.CONFIRMED if bank_match else FieldStatus.CONFLICT,
            ["bank-fingerprint"],
            "active fingerprint match" if bank_match else "fingerprint mismatch")
    elif extraction.bank_reference:
        if settings.bank_hash_key is None:
            verifier_errors.append("bank-verifier: missing fingerprint key (fail closed)")
            outcomes["bank"] = FieldOutcome("bank", FieldStatus.UNCONFIRMED,
                                            ["bank-key-missing"], "no key configured")
        elif vendor_match.vendor is None:
            outcomes["bank"] = FieldOutcome("bank", FieldStatus.UNCONFIRMED,
                                            ["bank-no-vendor"], "no vendor to compare")
        else:
            try:
                presented = bank_fingerprint(extraction.bank_reference, settings.bank_hash_key)
            except ValueError as exc:
                verifier_errors.append(f"bank-verifier: {exc}")
                outcomes["bank"] = FieldOutcome("bank", FieldStatus.UNCONFIRMED,
                                                ["bank-normalize"], "unfingerprintable")
            else:
                bank_match = constant_time_equal(
                    presented,
                    str(vendor_match.vendor.get("active_bank_fingerprint")))
                outcomes["bank"] = FieldOutcome(
                    "bank", FieldStatus.CONFIRMED if bank_match else FieldStatus.CONFLICT,
                    ["bank-fingerprint"],
                    "active fingerprint match" if bank_match else "fingerprint mismatch")
    else:
        outcomes["bank"] = FieldOutcome("bank", FieldStatus.NOT_PROVIDED, [],
                                        "no bank reference extracted")

    # Arithmetic (R3 input).
    arithmetic_ok, arith_detail = check_arithmetic(extraction, settings.currency_precision)
    for name in MONEY_FIELDS:
        outcomes[name] = FieldOutcome(
            name, FieldStatus.CONFIRMED if arithmetic_ok else FieldStatus.CONFLICT,
            ["arithmetic-exact"], arith_detail)

    # Duplicate index (R4 input).
    duplicate_hit = None
    if vendor_match.vendor is not None:
        key = duplicate_key(vendor_id=vendor_match.vendor["vendor_id"],
                            invoice_number=extraction.invoice_number,
                            total=extraction.total, issue_date=extraction.issue_date,
                            precision=settings.currency_precision)
        duplicate_hit = _index.get(conn, key)
        outcomes["duplicate"] = FieldOutcome(
            "duplicate",
            FieldStatus.CONFLICT if duplicate_hit else FieldStatus.CONFIRMED,
            ["duplicate-index"],
            "already proposed/paid" if duplicate_hit else "not seen before")
    else:
        outcomes["duplicate"] = FieldOutcome("duplicate", FieldStatus.UNCONFIRMED,
                                             ["duplicate-index"], "no vendor; cannot key")

    # Purchase order (R5 input).
    po_record = None
    po_ok: bool | None = None
    if extraction.po_reference and vendor_match.vendor is not None:
        po_record = _pos.get_by_reference(conn, vendor_match.vendor["vendor_id"],
                                          extraction.po_reference.strip())
        if po_record is not None:
            po_record = PurchaseOrder(
                po_id=str(po_record["po_id"]),
                vendor_id=str(po_record["vendor_id"]),
                po_reference=str(po_record["po_reference"]),
                currency=str(po_record["currency"]),
                original_amount=Decimal(str(po_record["original_amount"])),
                remaining_amount=Decimal(str(po_record["remaining_amount"])),
                status=str(po_record.get("status", "open")),
                version=int(po_record.get("version", 1)))
        if po_record is None:
            po_ok = False
            outcomes["po"] = FieldOutcome("po", FieldStatus.CONFLICT, ["po-lookup"],
                                          "claimed PO not found for vendor")
        elif po_record.status != "open":
            po_ok = False
            outcomes["po"] = FieldOutcome("po", FieldStatus.CONFLICT, ["po-status"],
                                          f"PO status is {po_record.status}")
        elif po_record.currency != extraction.currency:
            po_ok = False
            outcomes["po"] = FieldOutcome("po", FieldStatus.CONFLICT, ["po-currency"],
                                          "PO currency differs")
        else:
            remaining = po_record.remaining_amount
            po_ok = extraction.total <= remaining
            outcomes["po"] = FieldOutcome(
                "po", FieldStatus.CONFIRMED if po_ok else FieldStatus.CONFLICT,
                ["po-amount"], f"total vs remaining {remaining}")
    elif extraction.po_reference:
        outcomes["po"] = FieldOutcome("po", FieldStatus.UNCONFIRMED, ["po-lookup"],
                                      "no vendor; cannot resolve PO")
    else:
        outcomes["po"] = FieldOutcome("po", FieldStatus.NOT_PROVIDED, [], "no PO claimed")

    # SAM evidence (R7 input).
    sam_ok: bool | None = None
    if sam_error is not None:
        verifier_errors.append(f"sam-verifier: {sam_error}")
        outcomes["sam"] = FieldOutcome("sam", FieldStatus.UNCONFIRMED,
                                       ["sam-required-error"], sam_error)
    elif sam_count is None and sam_lane is not None and sam_lane.status in (
            LaneStatus.NOT_EVALUATED, LaneStatus.FAILED, LaneStatus.EMPTY):
        # Uploaded but unevaluated: explicitly NOT confirmation.
        outcomes["sam"] = FieldOutcome(
            "sam", FieldStatus.UNCONFIRMED, ["sam-not-evaluated"],
            sam_lane.detail or "delivery evidence was not evaluated")
    elif sam_count is None:
        outcomes["sam"] = FieldOutcome("sam", FieldStatus.NOT_PROVIDED, [],
                                       "no delivery evidence")
    else:
        tolerance = settings.catalogue_tolerance_default if sam_item_tolerance is None \
            else sam_item_tolerance
        invoiced = sum(int(item.quantity) if item.quantity == int(item.quantity) else -1
                       for item in extraction.line_items)
        if invoiced < 0:
            sam_ok = False
            outcomes["sam"] = FieldOutcome("sam", FieldStatus.CONFLICT, ["sam-count"],
                                           "fractional quantities cannot be count-compared")
        else:
            sam_ok = abs(sam_count - invoiced) <= tolerance
            outcomes["sam"] = FieldOutcome(
                "sam", FieldStatus.CONFIRMED if sam_ok else FieldStatus.CONFLICT,
                ["sam-count"], f"observed {sam_count} vs invoiced {invoiced} (tol {tolerance})")

    # Dates get a lightweight presence/conflict marker; R6 decides.
    outcomes["dates"] = FieldOutcome("dates", FieldStatus.UNCONFIRMED,
                                     ["date-policy"], "decided by R6")
    if voice_conflicts:
        detail = (voice_lane.detail if voice_lane and voice_lane.detail
                  else "voice note conflicts with invoice facts")
        outcomes["voice"] = FieldOutcome("voice", FieldStatus.CONFLICT,
                                         ["voice-compare"], detail)
    elif voice_lane is not None and voice_lane.status in (
            LaneStatus.NOT_EVALUATED, LaneStatus.FAILED, LaneStatus.EMPTY):
        # Uploaded but unevaluated: explicitly NOT confirmation.
        outcomes["voice"] = FieldOutcome(
            "voice", FieldStatus.UNCONFIRMED, ["voice-not-evaluated"],
            voice_lane.detail or "voice evidence was not evaluated")
    elif voice_lane is not None and voice_lane.status == LaneStatus.EVALUATED:
        outcomes["voice"] = FieldOutcome(
            "voice", FieldStatus.NOT_APPLICABLE, ["voice-compare"],
            "voice evidence evaluated; no conflict")
    else:
        outcomes["voice"] = FieldOutcome("voice", FieldStatus.NOT_APPLICABLE,
                                         [], "no conflicting voice evidence")

    return Corroboration(outcomes=outcomes, vendor_match=vendor_match,
                         bank_match=bank_match, arithmetic_ok=arithmetic_ok,
                         duplicate_hit=duplicate_hit, po_record=po_record,
                         po_ok=po_ok, sam_ok=sam_ok,
                         verifier_errors=verifier_errors)
