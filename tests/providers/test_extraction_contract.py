"""Meta extraction contract: prompt, schema, aliases, evidence, validation.

Regression for the live frontend rejection (date/currency/quantity
errors): the prompt must demand the exact output contract the Pydantic
schema enforces, known field aliases must fail with an explicit error
(never silent drops), and the required `evidence` block must not break
validation.
"""

from __future__ import annotations

import json

import pytest

from app.core.errors import AppError
from app.pipeline.validate import validate_extraction
from app.providers.extraction import finalize_extraction
from app.providers.prompts import (
    EXTRACTION_INSTRUCTIONS,
    EXTRACTION_JSON_SCHEMA,
    EXTRACTION_PROMPT_VERSION,
)
from app.providers.types import ProviderError, ProviderName, Usage
from app.schemas.invoice import InvoiceExtraction
from tests.providers.helpers import valid_extraction_json

META = ProviderName.META


def _finalize(payload: dict) -> dict:
    result, _ = finalize_extraction(
        json.dumps(payload), provider=META, model="muse-spark-1.3",
        prompt_version=EXTRACTION_PROMPT_VERSION,
        artifact_sha256="ab" * 32, page_count=2, image_dims=None,
        usage=Usage(), request_id=None)
    return result.payload


def test_prompt_version_bumped_for_contract_fix():
    assert EXTRACTION_PROMPT_VERSION == "airlock-extraction/5"


def test_prompt_demands_exact_output_contract():
    text = EXTRACTION_INSTRUCTIONS
    assert "YYYY-MM-DD" in text
    assert "3 uppercase" in text or "3-letter uppercase" in text
    assert "ISO 4217 alphabetic" in text
    assert "display name" in text or "display-name" in text
    assert "ambiguous" in text.lower()
    assert "quantity" in text
    assert "qty" in text  # aliases explicitly forbidden
    assert "JSON" in text


def test_json_schema_field_names_match_pydantic():
    schema_required = set(EXTRACTION_JSON_SCHEMA["required"])
    model_fields = set(InvoiceExtraction.model_fields)
    assert schema_required <= model_fields
    for name in ("vendor_name", "invoice_number", "issue_date", "due_date",
                 "currency", "subtotal", "tax", "total", "line_items"):
        assert name in schema_required
    item_required = set(EXTRACTION_JSON_SCHEMA["properties"]["line_items"]
                        ["items"]["required"])
    assert item_required == {"description", "quantity", "unit_price"}


def test_evidence_block_grounded_stripped_and_valid():
    payload = json.loads(valid_extraction_json())
    payload["evidence"] = {"pages": {"total": 2, "vendor_name": 1}}
    result, _ = finalize_extraction(
        json.dumps(payload), provider=META, model="muse-spark-1.3",
        prompt_version=EXTRACTION_PROMPT_VERSION,
        artifact_sha256="ab" * 32, page_count=2, image_dims=None,
        usage=Usage(), request_id=None)
    # Grounded pages are preserved for fact provenance...
    assert result.evidence_pages == {"total": 2, "vendor_name": 1}
    # ...but the block itself must not break Pydantic validation.
    assert "evidence" not in result.payload
    extraction = validate_extraction(result.payload)
    assert str(extraction.total) == payload["total"]


def test_evidence_with_bad_page_dropped_with_warning():
    payload = json.loads(valid_extraction_json())
    payload["evidence"] = {"pages": {"total": 99}}
    result, model = finalize_extraction(
        json.dumps(payload), provider=META, model="muse-spark-1.3",
        prompt_version=EXTRACTION_PROMPT_VERSION,
        artifact_sha256="ab" * 32, page_count=2, image_dims=None,
        usage=Usage(), request_id=None)
    assert result.evidence_pages is None
    assert "evidence" not in result.payload
    assert any("evidence" in warning for warning in model.warnings)
    validate_extraction(result.payload)  # still schema-valid


def test_qty_alias_fails_with_explicit_error():
    payload = json.loads(valid_extraction_json())
    item = payload["line_items"][0]
    del item["quantity"]
    item["qty"] = "10"
    with pytest.raises(ProviderError) as exc_info:
        _finalize(payload)
    assert "quantity" in exc_info.value.message


def test_unit_price_alias_fails_with_explicit_error():
    payload = json.loads(valid_extraction_json())
    item = payload["line_items"][0]
    del item["unit_price"]
    item["price"] = "100.00"
    with pytest.raises(ProviderError) as exc_info:
        _finalize(payload)
    assert "unit_price" in exc_info.value.message


def test_top_level_alias_fails_with_explicit_error():
    payload = json.loads(valid_extraction_json())
    payload["vendor"] = payload.pop("vendor_name")
    with pytest.raises(ProviderError) as exc_info:
        _finalize(payload)
    assert "vendor_name" in exc_info.value.message


def test_unknown_fields_still_dropped_not_fatal():
    payload = json.loads(valid_extraction_json())
    payload["verdict"] = "APPROVE"
    cleaned = _finalize(payload)
    assert "verdict" not in cleaned
    validate_extraction(cleaned)


def test_date_contract_rejects_natural_language():
    base = json.loads(valid_extraction_json())
    for bad in ("November 4, 2026", "04/11/2026", "2026-11-4", "11-04-2026"):
        payload = dict(base, issue_date=bad)
        with pytest.raises(AppError) as exc_info:
            validate_extraction(payload)
        assert any(detail["code"] == "issue_date"
                   for detail in exc_info.value.details)
    good = dict(base, issue_date="2026-11-04", due_date="2026-12-04")
    extraction = validate_extraction(good)
    assert extraction.issue_date.isoformat() == "2026-11-04"


def test_currency_contract_rejects_marks_and_names():
    base = json.loads(valid_extraction_json())
    for bad in ("$", "US", "USDD", "", "Dollars", "Bitcoin"):
        payload = dict(base, currency=bad)
        with pytest.raises(AppError) as exc_info:
            validate_extraction(payload)
        assert any(detail["code"] == "currency"
                   for detail in exc_info.value.details)
    assert validate_extraction(dict(base, currency="USD")).currency == "USD"


def test_currency_contract_normalizes_safe_variants():
    # Lowercase codes and unambiguous names/symbols normalize
    # deterministically; ambiguous `$` alone never becomes USD.
    base = json.loads(valid_extraction_json())
    assert validate_extraction(dict(base, currency="usd")).currency == "USD"
    assert validate_extraction(
        dict(base, currency="US Dollars")).currency == "USD"
    assert validate_extraction(dict(base, currency="US$")).currency == "USD"
    with pytest.raises(AppError) as exc_info:
        validate_extraction(dict(base, currency="$"))
    detail = next(d for d in exc_info.value.details
                  if d["code"] == "currency")
    assert "Ambiguous" in detail["message"]
    assert "ISO 4217" in detail["message"]


def test_quantity_contract_requires_plain_decimal():
    base = json.loads(valid_extraction_json())
    payload = json.loads(json.dumps(base))
    del payload["line_items"][0]["quantity"]
    with pytest.raises(AppError) as exc_info:
        validate_extraction(payload)
    assert any("quantity" in detail["code"]
               for detail in exc_info.value.details)
    payload = json.loads(json.dumps(base))
    payload["line_items"][0]["quantity"] = "10"
    from decimal import Decimal
    assert validate_extraction(payload).line_items[0].quantity == Decimal("10")
    for bad in ("ten", "1,0", ""):
        payload = json.loads(json.dumps(base))
        payload["line_items"][0]["quantity"] = bad
        with pytest.raises(AppError):
            validate_extraction(payload)
