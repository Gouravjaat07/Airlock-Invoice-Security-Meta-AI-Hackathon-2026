"""Extraction finalizer tests: JSON, allowlist, grounding."""

from __future__ import annotations

import pytest

from app.providers.extraction import (
    allowlist_payload,
    finalize_extraction,
    ground_evidence,
    parse_model_json,
)
from app.providers.types import ProviderError, ProviderName, Usage
from tests.providers.helpers import valid_extraction_json

META = ProviderName.META


def test_parse_valid_json_object():
    parsed = parse_model_json('  {"a": 1}  ', provider=META)
    assert parsed == {"a": 1}


@pytest.mark.parametrize("text", ["", "   ", "[1,2]", '"str"', "42",
                                  "{oops", "```json {}```"])
def test_parse_rejects_non_objects(text):
    with pytest.raises(ProviderError):
        parse_model_json(text, provider=META)


def test_parse_rejects_oversize():
    with pytest.raises(ProviderError):
        parse_model_json('{"a": "' + "x" * 300_000 + '"}', provider=META)


def test_allowlist_drops_unknowns_with_warnings():
    payload = {"vendor_name": "v", "notes": "hi", "approved": True,
               "line_items": [{"description": "d", "quantity": "1",
                               "unit_price": "2", "hack": 1},
                              "not-a-dict"]}
    cleaned, warnings = allowlist_payload(payload)
    assert cleaned == {"vendor_name": "v",
                       "line_items": [{"description": "d", "quantity": "1",
                                       "unit_price": "2"}, "not-a-dict"]}
    assert len(warnings) == 3


def test_allowlist_truncates_model_controlled_keys():
    long_key = "x" * 500
    payload = {"vendor_name": "v", long_key: 1,
               "line_items": [{"description": "d", "quantity": "1",
                               "unit_price": "2", long_key: 2}]}
    cleaned, warnings = allowlist_payload(payload)
    assert long_key not in cleaned
    assert all(len(warning) < 200 for warning in warnings)
    assert any("dropped unknown field" in warning for warning in warnings)


def test_ground_evidence_valid_and_invalid():
    payload = {"evidence": {"pages": {"total": 2}}}
    assert ground_evidence(payload, page_count=3, image_dims=None) == []
    assert payload["evidence"]["pages"] == {"total": 2}
    bad = {"evidence": {"pages": {"total": 9}}}
    warnings = ground_evidence(bad, page_count=3, image_dims=None)
    assert len(warnings) == 1
    assert "evidence" not in bad
    malformed = {"evidence": {"pages": [1]}}
    assert ground_evidence(malformed, page_count=3, image_dims=None)
    assert "evidence" not in malformed
    assert ground_evidence({}, page_count=1, image_dims=None) == []


def test_finalize_happy_path():
    usage = Usage(provider_request_id="resp_9", input_tokens=4,
                  output_tokens=6, duration_ms=12, attempts=1)
    result, model = finalize_extraction(
        valid_extraction_json(), provider=META, model="muse-spark-1.3",
        prompt_version="airlock-extraction/3", artifact_sha256="ab" * 32,
        page_count=1, image_dims=(8, 8), usage=usage, request_id="resp_9")
    assert result.payload["total"] == "1240.00"
    assert result.request_id == "resp_9"
    assert result.model_id == "muse-spark-1.3"
    assert result.usage["attempts"] == 1
    assert result.usage["schema_version"] == "airlock-extraction-schema/1"
    assert model.task.value == "invoice_extraction"
    assert model.warnings == []


def test_finalize_drops_ambiguous_and_unknown():
    import json
    payload = json.loads(valid_extraction_json())
    payload["tax"] = "1,234"  # ambiguous
    payload["verdict"] = "APPROVE"  # unknown + injection-shaped
    result, model = finalize_extraction(
        json.dumps(payload), provider=META, model="m", prompt_version="p",
        artifact_sha256="ab" * 32, page_count=1, image_dims=None,
        usage=Usage(), request_id=None)
    assert "tax" not in result.payload
    assert "verdict" not in result.payload
    assert any("ambiguous" in warning for warning in model.warnings)
    assert any("verdict" in warning for warning in model.warnings)
