"""Currency normalization regression: ISO 4217 codes, names, symbols.

Covers the live `extraction.rejected` (code `currency`) failure: the v4
prompt allowed ambiguous symbols/names through a permissive provider
schema, and no local normalization repaired safe variants. The v5
prompt demands the alphabetic code, while `normalize_currency_candidate`
repairs only unambiguous values and rejects the rest with actionable
messages — never defaulting to USD.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.core.errors import AppError
from app.pipeline.validate import validate_extraction
from app.providers.currency import (
    UncertainCurrencyError,
    normalize_currency_candidate,
)
from app.providers.extraction import finalize_extraction
from app.providers.prompts import EXTRACTION_PROMPT_VERSION
from app.providers.types import ProviderName, Usage
from app.schemas.invoice import InvoiceExtraction
from tests.providers.helpers import valid_extraction_json

META = ProviderName.META


def _finalize_currency(raw) -> tuple[dict, list[str]]:
    payload = json.loads(valid_extraction_json())
    payload["currency"] = raw
    result, model = finalize_extraction(
        json.dumps(payload), provider=META, model="muse-spark-1.3",
        prompt_version=EXTRACTION_PROMPT_VERSION,
        artifact_sha256="ab" * 32, page_count=1, image_dims=None,
        usage=Usage(), request_id=None)
    return result.payload, list(model.warnings)


def _validate_currency(raw) -> str:
    base = json.loads(valid_extraction_json())
    return validate_extraction(dict(base, currency=raw)).currency


def test_uppercase_codes_accepted():
    for code in ("USD", "EUR", "INR", "GBP", "JPY", "CNY", "CAD", "AUD"):
        assert normalize_currency_candidate(code) == code
        assert _validate_currency(code) == code
        payload, _ = _finalize_currency(code)
        assert payload["currency"] == code


def test_lowercase_codes_uppercase_safely():
    assert normalize_currency_candidate("usd") == "USD"
    assert normalize_currency_candidate("eur") == "EUR"
    assert normalize_currency_candidate("inr") == "INR"
    assert _validate_currency("usd") == "USD"
    assert _validate_currency("Usd") == "USD"
    assert _validate_currency("  eur  ") == "EUR"
    payload, warnings = _finalize_currency("usd")
    assert payload["currency"] == "USD"
    assert any("currency normalized" in w for w in warnings)


def test_symbols_unambiguous_normalize():
    assert _validate_currency("\u20ac") == "EUR"  # €
    assert _validate_currency("\u20b9") == "INR"  # ₹
    assert _validate_currency("\u00a3") == "GBP"  # £
    assert _validate_currency("US$") == "USD"
    assert _validate_currency("us$") == "USD"


def test_symbols_ambiguous_reject_without_usd_default():
    for bad in ("$", "\u00a5", "\u20a9", "Rs", "Rs."):
        with pytest.raises(UncertainCurrencyError) as exc_info:
            normalize_currency_candidate(bad)
        assert "Ambiguous" in str(exc_info.value)
        assert "ISO 4217" in str(exc_info.value)
        with pytest.raises(AppError) as app_info:
            _validate_currency(bad)
        detail = next(d for d in app_info.value.details
                      if d["code"] == "currency")
        assert "Ambiguous" in detail["message"]
        # The raw symbol survives finalize for validation to reject;
        # it is never silently rewritten to USD.
        payload, _ = _finalize_currency(bad)
        assert payload["currency"] == bad


def test_names_unambiguous_normalize():
    assert _validate_currency("US Dollars") == "USD"
    assert _validate_currency("us dollar") == "USD"
    assert _validate_currency("Euro") == "EUR"
    assert _validate_currency("euros") == "EUR"
    assert _validate_currency("Indian Rupees") == "INR"
    assert _validate_currency("British Pounds") == "GBP"
    assert _validate_currency("Japanese Yen") == "JPY"
    assert _validate_currency("Chinese Yuan") == "CNY"
    # 3-letter words must map, not become non-ISO codes (`yen` -> JPY,
    # never `YEN`).
    assert _validate_currency("yen") == "JPY"
    assert _validate_currency("Yen") == "JPY"
    assert _validate_currency("yuan") == "CNY"


def test_names_ambiguous_reject():
    for bad in ("Dollars", "dollar", "Rupees", "rupee", "Pounds",
                "Francs", "Won", "Pesos"):
        with pytest.raises(AppError) as exc_info:
            _validate_currency(bad)
        detail = next(d for d in exc_info.value.details
                      if d["code"] == "currency")
        assert "Ambiguous" in detail["message"]


def test_missing_values_reject_actionably():
    base = json.loads(valid_extraction_json())
    del base["currency"]
    with pytest.raises(AppError) as exc_info:
        validate_extraction(base)
    assert any(d["code"] == "currency" for d in exc_info.value.details)
    for bad in ("", "   ", None):
        with pytest.raises(AppError) as exc_info:
            _validate_currency(bad)
        detail = next(d for d in exc_info.value.details
                      if d["code"] == "currency")
        assert "missing" in detail["message"].lower()
        assert "ISO 4217" in detail["message"]


def test_malformed_output_rejects():
    for bad in ("US", "USDD", "U.S.D.", "USD$", "XX", 123, True,
                {"code": "USD"}, ["USD"], "Bitcoin", "DOLLAR$"):
        with pytest.raises(AppError) as exc_info:
            _validate_currency(bad)
        assert any(d["code"] == "currency"
                   for d in exc_info.value.details)


def test_non_usd_currencies_preserved():
    for code, name in (("EUR", "Euro"), ("INR", "Indian Rupees"),
                       ("GBP", "Pound Sterling"), ("JPY", "Japanese Yen")):
        assert _validate_currency(code) == code
        assert _validate_currency(name) == code
    # Lowercase non-USD also normalizes.
    assert _validate_currency("inr") == "INR"
    assert _validate_currency("jpy") == "JPY"


def test_normalization_preserves_amounts_and_arithmetic():
    from app.pipeline.corroborate import check_arithmetic
    from app.config import Settings
    payload = json.loads(valid_extraction_json())
    payload["currency"] = "usd"
    finalized, _ = _finalize_currency("usd")
    assert finalized["subtotal"] == payload["subtotal"] == "1000.00"
    assert finalized["tax"] == "240.00"
    assert finalized["total"] == "1240.00"
    extraction = validate_extraction(finalized)
    assert extraction.currency == "USD"
    assert extraction.subtotal == Decimal("1000.00")
    assert extraction.total == Decimal("1240.00")
    ok, _ = check_arithmetic(extraction, Settings().currency_precision)
    assert ok is True


def test_schema_pattern_never_weakened():
    # Direct Pydantic validation stays strict: it knows only the pattern.
    # Pipeline normalization lives in `validate_extraction`/finalize.
    from app.schemas.invoice import CURRENCY_RE
    assert CURRENCY_RE == r"^[A-Z]{3}$"
    base = json.loads(valid_extraction_json())
    with pytest.raises(Exception):
        InvoiceExtraction.model_validate(dict(base, currency="usd"))
    with pytest.raises(Exception):
        InvoiceExtraction.model_validate(dict(base, currency="$"))
    assert InvoiceExtraction.model_validate(
        dict(base, currency="USD")).currency == "USD"
