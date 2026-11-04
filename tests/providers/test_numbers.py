"""Decimal candidate normalization tests (locale matrix)."""

from __future__ import annotations

import pytest

from app.providers.numbers import (
    UncertainNumberError,
    normalize_decimal_candidate,
    normalize_extraction_numbers,
)


@pytest.mark.parametrize("raw,expected", [
    ("1240.00", "1240.00"),
    ("1000", "1000"),
    (1000, "1000"),
    ("  42.5 ", "42.5"),
    ("$1,234.56", "1234.56"),
    ("Rs. 5,000.00", "5000.00"),
    ("1.234,56", "1234.56"),
    ("1,234,567.89", "1234567.89"),
    ("1.234.567,89", "1234567.89"),
    ("1,00,000.00", "100000.00"),  # Indian grouping
    ("12,34,567", "1234567"),  # Indian grouping, no decimals
    ("1,00,000", "100000"),
    ("(1,234.56)", "-1234.56"),
    ("-42.00", "-42.00"),
    ("+42.00", "42.00"),
    ("0.99", "0.99"),
    ("1 234,56", "1234.56"),
    ("999999999999.99", "999999999999.99"),
    ("0.000001", "0.000001"),
])
def test_unambiguous_amounts(raw, expected):
    assert normalize_decimal_candidate(raw) == expected


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "abc",
    "12.34.56",
    "1,2,3",
    "1,234",  # grouping or decimal: ambiguous
    "1.234",  # grouping or decimal: ambiguous
    "1,23,45,67",  # invalid grouping shape
    "12,345,67",  # mixed grouping shape
    "1,23.45",
    "NaN",
    "Infinity",
    "$",
    "(12.00",
    True,
    False,
    None,
    12.5,
    "1.2.3,4",
    "--5",
])
def test_ambiguous_or_invalid_amounts(raw):
    with pytest.raises(UncertainNumberError):
        normalize_decimal_candidate(raw)


def test_normalize_extraction_numbers_drops_uncertain():
    payload = {
        "subtotal": "1,000.00",
        "tax": "1,234",  # ambiguous → dropped
        "total": "2,234.00",
        "line_items": [
            {"description": "a", "quantity": "2", "unit_price": "1.234"},
            {"description": "b", "quantity": "x", "unit_price": "5.00"},
        ],
    }
    cleaned, dropped = normalize_extraction_numbers(payload)
    assert cleaned["subtotal"] == "1000.00"
    assert "tax" not in cleaned
    assert cleaned["line_items"][0]["quantity"] == "2"
    assert "unit_price" not in cleaned["line_items"][0]
    assert "quantity" not in cleaned["line_items"][1]
    assert sorted(dropped) == ["line_items[0].unit_price",
                               "line_items[1].quantity", "tax"]
