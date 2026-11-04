"""Unit tests: Decimal arithmetic, money parsing, proposal hashing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.proposals import proposal_digest
from app.pipeline.corroborate import check_arithmetic, quantize_money
from app.schemas.invoice import InvoiceExtraction, LineItem, parse_money


def extraction(**overrides):
    data = {
        "vendor_name": "Acme Flour Co",
        "invoice_number": "INV-1",
        "issue_date": "2026-10-01",
        "due_date": "2026-10-31",
        "currency": "USD",
        "subtotal": "1200.00",
        "tax": "40.00",
        "total": "1240.00",
        "bank_reference": "SYN-ACME-0001",
        "line_items": [
            {"description": "a", "quantity": "10", "unit_price": "100.00"},
            {"description": "b", "quantity": "20", "unit_price": "10.00"},
        ],
    }
    data.update(overrides)
    return InvoiceExtraction.model_validate(data)


def test_exact_arithmetic_passes():
    ok, detail = check_arithmetic(extraction(), 2)
    assert ok and detail == "exact"


def test_cent_mismatch_fails():
    ok, _ = check_arithmetic(extraction(total="1240.01"), 2)
    assert not ok


def test_classic_float_trap_is_exact():
    ext = extraction(
        subtotal="0.30", tax="0.00", total="0.30",
        line_items=[{"description": "a", "quantity": "1", "unit_price": "0.10"},
                    {"description": "b", "quantity": "1", "unit_price": "0.20"}])
    assert check_arithmetic(ext, 2)[0]


def test_many_line_items():
    items = [{"description": f"item {i}", "quantity": "3",
              "unit_price": "1.11"} for i in range(150)]
    ext = extraction(subtotal="499.50", tax="0.00", total="499.50",
                     line_items=items)
    assert check_arithmetic(ext, 2)[0]


def test_large_totals():
    ext = extraction(subtotal="999999999.99", tax="0.00",
                     total="999999999.99",
                     line_items=[{"description": "a", "quantity": "1",
                                  "unit_price": "999999999.99"}])
    assert check_arithmetic(ext, 2)[0]


def test_negative_rejected_by_schema():
    with pytest.raises(Exception):
        extraction(line_items=[{"description": "a", "quantity": "-1",
                                "unit_price": "1.00"}])


def test_float_input_rejected():
    with pytest.raises(ValueError, match="binary float"):
        parse_money(0.1)


def test_nan_infinity_rejected():
    with pytest.raises(ValueError):
        parse_money("NaN")
    with pytest.raises(ValueError):
        parse_money("Infinity")


def test_excessive_precision_rejected():
    with pytest.raises(ValueError, match="precision"):
        parse_money("1.0000001")


def test_bool_rejected():
    with pytest.raises(ValueError):
        parse_money(True)


def test_quantize_rounding():
    assert quantize_money(Decimal("1.005"), 2) == Decimal("1.00")  # ROUND_HALF_EVEN
    assert quantize_money(Decimal("1.015"), 2) == Decimal("1.02")


def test_proposal_hash_stable_and_sensitive():
    kwargs = {"proposal_id": "prop_1", "case_id": "case_1",
              "vendor_id": "ven-acme-flour", "amount": "1240.00",
              "currency": "USD", "due_date": "2026-10-31",
              "invoice_reference": "INV-1", "verdict_id": "verdict_1",
              "policy_version": "2.0.0"}
    first = proposal_digest(**kwargs)
    assert proposal_digest(**kwargs) == first
    for field in ("vendor_id", "amount", "currency", "due_date",
                  "invoice_reference"):
        mutated = dict(kwargs, **{field: kwargs[field] + "X"})
        assert proposal_digest(**mutated) != first


def test_unknown_fields_rejected():
    with pytest.raises(Exception):
        LineItem.model_validate({"description": "a", "quantity": "1",
                                 "unit_price": "1.00", "admin": True})
