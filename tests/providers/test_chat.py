"""Chat-completions core tests (Baseten/Glimmer shared path)."""

from __future__ import annotations

import pytest

from app.providers.chat import map_chat_http_error, parse_chat_response
from app.providers.types import ProviderError, ProviderErrorCategory, ProviderName
from tests.providers.helpers import chat_ok, error_envelope

MODEL = "meta-models/muse-spark-open-1026"


def test_parse_ok():
    result = parse_chat_response(chat_ok("hi"), requested_model=MODEL,
                                 provider=ProviderName.BASETEN)
    assert result.content_text == "hi"
    assert result.model == MODEL
    assert result.response_id == "chatcmpl_1"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.warnings == []


def test_parse_content_parts_joined():
    body = chat_ok("")
    body["choices"][0]["message"]["content"] = [
        {"type": "text", "text": "a"},
        {"type": "text", "text": "b"},
    ]
    result = parse_chat_response(body, requested_model=MODEL,
                                 provider=ProviderName.BASETEN)
    assert result.content_text == "ab"


def test_parse_null_content_is_empty():
    body = chat_ok("")
    body["choices"][0]["message"]["content"] = None
    result = parse_chat_response(body, requested_model=MODEL,
                                 provider=ProviderName.BASETEN)
    assert result.content_text == ""


def test_model_mismatch_warns():
    result = parse_chat_response(chat_ok("x", model="other"),
                                 requested_model=MODEL,
                                 provider=ProviderName.BASETEN)
    assert result.model == "other"
    assert len(result.warnings) == 1


def test_malformed_usage_warns():
    body = chat_ok("x")
    body["usage"] = {"prompt_tokens": "many"}
    result = parse_chat_response(body, requested_model=MODEL,
                                 provider=ProviderName.BASETEN)
    assert result.usage.input_tokens is None
    assert len(result.warnings) == 1


@pytest.mark.parametrize("mutate,category", [
    ("tool_calls", ProviderErrorCategory.MALFORMED),
    ("length", ProviderErrorCategory.INCOMPLETE),
    ("content_filter", ProviderErrorCategory.REFUSAL),
    ("weird_finish", ProviderErrorCategory.MALFORMED),
    ("no_choices", ProviderErrorCategory.MALFORMED),
    ("no_message", ProviderErrorCategory.MALFORMED),
])
def test_finish_and_shape_matrix(mutate, category):
    body = chat_ok("x")
    if mutate == "tool_calls":
        body["choices"][0]["message"]["tool_calls"] = [{"id": "c"}]
    elif mutate == "length":
        body["choices"][0]["finish_reason"] = "length"
    elif mutate == "content_filter":
        body["choices"][0]["finish_reason"] = "content_filter"
    elif mutate == "weird_finish":
        body["choices"][0]["finish_reason"] = "teleport"
    elif mutate == "no_choices":
        body["choices"] = []
    elif mutate == "no_message":
        del body["choices"][0]["message"]
    with pytest.raises(ProviderError) as exc_info:
        parse_chat_response(body, requested_model=MODEL,
                            provider=ProviderName.BASETEN)
    assert exc_info.value.category == category


def test_message_refusal_field_is_refusal():
    body = chat_ok("ignored")
    body["choices"][0]["message"]["content"] = None
    body["choices"][0]["message"]["refusal"] = "I cannot help with that"
    with pytest.raises(ProviderError) as exc_info:
        parse_chat_response(body, requested_model=MODEL,
                            provider=ProviderName.BASETEN)
    assert exc_info.value.category == ProviderErrorCategory.REFUSAL


@pytest.mark.parametrize("status,envelope,category", [
    (401, error_envelope("no"), ProviderErrorCategory.AUTH),
    (401, {"error": {"code": None, "type": "authentication_error"}},
     ProviderErrorCategory.AUTH),
    (402, {"error": {"code": "billing_not_configured"}},
     ProviderErrorCategory.CONFIG),
    (404, error_envelope("m"), ProviderErrorCategory.CONFIG),
    (429, error_envelope("slow"), ProviderErrorCategory.RATE_LIMIT),
    (400, error_envelope("bad"), ProviderErrorCategory.BAD_REQUEST),
    (400, error_envelope("no", code="moderation_blocked"),
     ProviderErrorCategory.REFUSAL),
    (400, {"error": {"code": None, "type": "rate_limit_error"}},
     ProviderErrorCategory.RATE_LIMIT),
    (500, error_envelope("boom"), ProviderErrorCategory.SERVER),
    (503, error_envelope("busy"), ProviderErrorCategory.SERVER),
    (504, {}, ProviderErrorCategory.INCOMPLETE),
    (418, {}, ProviderErrorCategory.BAD_REQUEST),
    (301, {}, ProviderErrorCategory.MALFORMED),
])
def test_chat_error_mapping(status, envelope, category):
    exc = map_chat_http_error(status, {}, envelope,
                              provider=ProviderName.GLIMMER)
    assert exc.category == category
