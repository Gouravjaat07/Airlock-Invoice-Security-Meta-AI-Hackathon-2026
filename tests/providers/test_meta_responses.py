
"""Meta Responses API contract tests (offline, stub transport).

Covers request construction, auth placement, response parsing,
structured-output handling, error mapping, SSE accumulation, retry
semantics, usage extraction, and secret redaction.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.providers.http import HttpClient, parse_retry_after
from app.providers.meta import (
    accumulate_sse_text,
    map_http_error,
    meta_client,
    parse_response_object,
)
from app.providers.types import ProviderError, ProviderErrorCategory, ProviderName
from tests.providers.helpers import (
    FAKE_KEY,
    error_envelope,
    provider_settings,
    responses_ok,
    stub_transport,
)

EXPECTED = "muse-spark-1.3"


def _client(handler, **kw) -> HttpClient:
    settings = provider_settings(**kw)
    return HttpClient(provider=ProviderName.META, base_url=settings.meta_api_base,
                      credential=settings.model_api_key,
                      connect_timeout_s=5, read_timeout_s=10,
                      transport=stub_transport(handler))


def test_request_shape_and_auth():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["ua"] = request.headers.get("user-agent")
        seen["op"] = request.headers.get("x-request-id")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=responses_ok("{}"))

    client = _client(handler)
    status, _, parsed = client.post_json(
        "/responses", {"model": EXPECTED, "input": "hi"}, operation_id="op_1")
    assert status == 200
    assert seen["url"].endswith("/responses")
    assert seen["auth"] == "Bearer " + FAKE_KEY
    assert seen["ua"].startswith("airlock-phase3/")
    assert seen["op"] == "op_1"
    assert parsed["status"] == "completed"


def test_parse_completed_response():
    parsed = parse_response_object(
        responses_ok("hello", usage={"input_tokens": 3, "output_tokens": 7}),
        requested_model=EXPECTED, provider=ProviderName.META)
    assert parsed.output_text == "hello"
    assert parsed.response_id == "resp_1"
    assert parsed.usage.input_tokens == 3
    assert parsed.usage.output_tokens == 7
    assert parsed.usage.provider_request_id == "resp_1"
    assert parsed.warnings == []


def test_parse_multi_part_concatenation():
    body = responses_ok("")
    body["output"][0]["content"] = [
        {"type": "output_text", "text": "a", "annotations": []},
        {"type": "output_text", "text": "b", "annotations": []},
    ]
    parsed = parse_response_object(body, requested_model=EXPECTED,
                                   provider=ProviderName.META)
    assert parsed.output_text == "ab"


def test_parse_skips_reasoning_and_unknown_items():
    body = responses_ok("ok")
    body["output"].append({"type": "reasoning", "id": "r"})
    body["output"].append({"type": "future_thing", "id": "f"})
    body["output"][0]["content"].append({"type": "future_part"})
    parsed = parse_response_object(body, requested_model=EXPECTED,
                                   provider=ProviderName.META)
    assert parsed.output_text == "ok"
    assert len(parsed.warnings) == 2


def test_parse_rejects_tool_call():
    body = responses_ok("")
    body["output"].append({"type": "function_call", "id": "c",
                           "name": "pay", "arguments": "{}"})
    with pytest.raises(ProviderError) as exc_info:
        parse_response_object(body, requested_model=EXPECTED,
                              provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.MALFORMED


def test_parse_rejects_refusal_part():
    body = responses_ok("")
    body["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
    with pytest.raises(ProviderError) as exc_info:
        parse_response_object(body, requested_model=EXPECTED,
                              provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.REFUSAL


def test_parse_failed_and_incomplete():
    failed = {"id": "r", "status": "failed", "model": EXPECTED,
              "output": [], "error": {"code": "server_error"}}
    with pytest.raises(ProviderError) as exc_info:
        parse_response_object(failed, requested_model=EXPECTED,
                              provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.SERVER
    refused = {"id": "r", "status": "failed", "model": EXPECTED,
               "output": [],
               "error": {"code": "content_policy_violation"}}
    with pytest.raises(ProviderError) as exc_info:
        parse_response_object(refused, requested_model=EXPECTED,
                              provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.REFUSAL
    incomplete = {"id": "r", "status": "incomplete", "model": EXPECTED,
                  "output": []}
    with pytest.raises(ProviderError) as exc_info:
        parse_response_object(incomplete, requested_model=EXPECTED,
                              provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.INCOMPLETE


@pytest.mark.parametrize("body", [
    [],
    {"status": "completed"},
    {"status": "completed", "output": {}},
    {"status": "completed", "output": [[]]},
    {"status": "completed", "output": [{"type": "message"}]},
    {"status": "completed",
     "output": [{"type": "message", "content": [{"type": "output_text"}]}]},
    {"status": "weird", "output": []},
    {"status": "in_progress", "output": []},
])
def test_parse_malformed_shapes(body):
    with pytest.raises(ProviderError) as exc_info:
        parse_response_object(body, requested_model=EXPECTED,
                              provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.MALFORMED


def test_model_mismatch_warns_and_records_actual():
    parsed = parse_response_object(responses_ok("x", model="other-9"),
                                   requested_model=EXPECTED,
                                   provider=ProviderName.META)
    assert parsed.model == "other-9"
    assert any("differs" in warning for warning in parsed.warnings)


def test_malformed_usage_is_warning_not_failure():
    parsed = parse_response_object(
        responses_ok("x", usage={"input_tokens": -1, "output_tokens": "many"}),
        requested_model=EXPECTED, provider=ProviderName.META)
    assert parsed.usage.input_tokens is None
    assert parsed.usage.output_tokens is None
    assert any("usage" in warning for warning in parsed.warnings)


@pytest.mark.parametrize("status,envelope,category", [
    (400, error_envelope("bad"), ProviderErrorCategory.BAD_REQUEST),
    (401, error_envelope("no", code="invalid_api_key"), ProviderErrorCategory.AUTH),
    (403, error_envelope("no"), ProviderErrorCategory.AUTH),
    (404, {}, ProviderErrorCategory.BAD_REQUEST),
    (404, error_envelope("m", code="model_not_found"), ProviderErrorCategory.CONFIG),
    (413, error_envelope("big", code="payload_too_large"),
     ProviderErrorCategory.BAD_REQUEST),
    (422, error_envelope("bad"), ProviderErrorCategory.BAD_REQUEST),
    (429, error_envelope("slow", code="rate_limit_exceeded"),
     ProviderErrorCategory.RATE_LIMIT),
    (500, error_envelope("boom"), ProviderErrorCategory.SERVER),
    (502, {}, ProviderErrorCategory.SERVER),
    (503, error_envelope("busy", code="service_overloaded"),
     ProviderErrorCategory.SERVER),
    (504, {}, ProviderErrorCategory.INCOMPLETE),
    (200, error_envelope("slow", code="gateway_timeout"),
     ProviderErrorCategory.INCOMPLETE),
    (402, error_envelope("pay", code="billing_not_configured"),
     ProviderErrorCategory.CONFIG),
    (402, {}, ProviderErrorCategory.CONFIG),
    (401, {"error": {"code": None, "type": "authentication_error"}},
     ProviderErrorCategory.AUTH),
    (400, {"error": {"code": None, "type": "rate_limit_error"}},
     ProviderErrorCategory.RATE_LIMIT),
    (400, {"error": {"code": None, "type": "billing_error"}},
     ProviderErrorCategory.CONFIG),
    (406, {}, ProviderErrorCategory.BAD_REQUEST),
    (418, {}, ProviderErrorCategory.BAD_REQUEST),
    (301, {}, ProviderErrorCategory.MALFORMED),
    (400, error_envelope("no", code="content_policy_violation"),
     ProviderErrorCategory.REFUSAL),
])
def test_http_error_mapping(status, envelope, category):
    exc = map_http_error(status, {}, envelope, provider=ProviderName.META)
    assert exc.category == category
    assert FAKE_KEY not in str(exc)


def test_rate_limit_carries_retry_after():
    exc = map_http_error(429, {"Retry-After": "7"}, {},
                         provider=ProviderName.META)
    assert exc.category == ProviderErrorCategory.RATE_LIMIT
    assert exc.retry_after_s == 7.0
    assert exc.retryable is True


def test_auth_is_not_retryable():
    exc = map_http_error(401, {}, {}, provider=ProviderName.META)
    assert exc.retryable is False


@pytest.mark.parametrize("headers,expected", [
    ({"Retry-After": "3"}, 3.0),
    ({"retry-after": "0"}, 0.0),
    ({"Retry-After": "9999"}, 300.0),
    ({"Retry-After": "-5"}, 0.0),
    ({"Retry-After": "bogus"}, None),
    ({"Retry-After": ""}, None),
    ({}, None),
])
def test_parse_retry_after(headers, expected):
    assert parse_retry_after(headers) == expected


def test_retry_after_http_date():
    parsed = parse_retry_after({"Retry-After": "Wed, 21 Oct 2030 07:28:00 GMT"})
    assert parsed is not None and 0.0 < parsed <= 300.0


def test_sse_accumulation():
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            "event: response.output_text.delta\n"
            'data: {"delta": "hel"}\n\n'
            "event: response.output_text.delta\n"
            'data: {"delta": "lo"}\n\n'
            ": heartbeat\n\n"
            "event: response.completed\n"
            f"data: {json.dumps({'response': responses_ok('hello')})}\n\n"
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=body.encode())

    client = _client(handler)
    chunks = list(client.stream_sse("/responses", {"model": EXPECTED,
                                                   "stream": True},
                                   operation_id="op_s"))
    assert ("response.output_text.delta", '{"delta": "hel"}') in chunks
    parsed = accumulate_sse_text(iter(chunks), requested_model=EXPECTED,
                                 provider=ProviderName.META)
    assert parsed.output_text == "hello"
    assert parsed.status == "completed"


def test_sse_missing_completion_is_incomplete():
    events = iter([("response.output_text.delta",
                    json.dumps({"delta": "x"}))])
    with pytest.raises(ProviderError) as exc_info:
        accumulate_sse_text(events, requested_model=EXPECTED,
                            provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.INCOMPLETE


def test_sse_malformed_delta():
    events = iter([("response.output_text.delta", "not-json")])
    with pytest.raises(ProviderError) as exc_info:
        accumulate_sse_text(events, requested_model=EXPECTED,
                            provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.MALFORMED


def test_sse_failure_envelope():
    failed = {"id": "r", "status": "failed", "model": EXPECTED,
              "output": [], "error": {"code": "server_error"}}
    events = iter([("response.failed", json.dumps({"response": failed}))])
    with pytest.raises(ProviderError) as exc_info:
        accumulate_sse_text(events, requested_model=EXPECTED,
                            provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.SERVER


def test_transport_timeout_and_unreachable():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    def refused_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client(timeout_handler)
    with pytest.raises(ProviderError) as exc_info:
        client.post_json("/responses", {}, operation_id="op")
    assert exc_info.value.category == ProviderErrorCategory.TIMEOUT
    client = _client(refused_handler)
    with pytest.raises(ProviderError) as exc_info:
        client.post_json("/responses", {}, operation_id="op")
    assert exc_info.value.category == ProviderErrorCategory.UNAVAILABLE


def test_malformed_json_body_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{oops")

    client = _client(handler)
    status, _, parsed = client.post_json("/responses", {},
                                         operation_id="op")
    assert status == 200
    assert parsed is None


def test_empty_404_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"")

    client = _client(handler)
    status, _, parsed = client.post_json("/nope", {}, operation_id="op")
    assert status == 404
    assert parsed is None
    exc = map_http_error(status, {}, parsed, provider=ProviderName.META)
    assert exc.category == ProviderErrorCategory.BAD_REQUEST


def test_no_secret_in_errors_or_logs(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json=error_envelope("boom"))

    client = _client(handler)
    with caplog.at_level("INFO", logger="airlock.providers.http"):
        status, _, _ = client.post_json("/responses", {"k": "v"},
                                        operation_id="op_log")
    assert status == 500
    for record in caplog.records:
        assert FAKE_KEY not in record.getMessage()
        assert "authorization" not in record.getMessage().lower()


def test_sse_data_only_events_use_body_type():
    # Docs examples type events inside the JSON body (no `event:` line).
    events = iter([
        (None, json.dumps({"type": "response.output_text.delta",
                           "delta": "hel"})),
        (None, json.dumps({"type": "response.output_text.delta",
                           "delta": "lo"})),
        (None, json.dumps({"type": "response.completed",
                           "response": responses_ok("hello")})),
    ])
    parsed = accumulate_sse_text(events, requested_model=EXPECTED,
                                 provider=ProviderName.META)
    assert parsed.output_text == "hello"
    assert parsed.status == "completed"


def test_sse_error_event_maps_transient():
    events = iter([
        (None, json.dumps({"type": "error", "code": "server_shutting_down"})),
    ])
    with pytest.raises(ProviderError) as exc_info:
        accumulate_sse_text(events, requested_model=EXPECTED,
                            provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.SERVER
    assert exc_info.value.retryable is True


def test_sse_error_event_maps_rate_limit():
    events = iter([
        ("error", json.dumps({"type": "error",
                              "code": "rate_limit_exceeded"})),
    ])
    with pytest.raises(ProviderError) as exc_info:
        accumulate_sse_text(events, requested_model=EXPECTED,
                            provider=ProviderName.META)
    assert exc_info.value.category == ProviderErrorCategory.RATE_LIMIT


def test_read_timeout_is_ambiguous_not_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("stalled mid-response")

    client = _client(handler)
    with pytest.raises(ProviderError) as exc_info:
        client.post_json("/responses", {}, operation_id="op")
    assert exc_info.value.category == ProviderErrorCategory.INCOMPLETE
    assert exc_info.value.retryable is False


def test_pool_timeout_stays_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.PoolTimeout("saturated")

    client = _client(handler)
    with pytest.raises(ProviderError) as exc_info:
        client.post_json("/responses", {}, operation_id="op")
    assert exc_info.value.category == ProviderErrorCategory.TIMEOUT
    assert exc_info.value.retryable is True


def test_response_size_cap_enforced_while_streaming(monkeypatch):
    import app.providers.http as http_module

    monkeypatch.setattr(http_module, "MAX_RESPONSE_BYTES", 16)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 64)

    client = _client(handler)
    with pytest.raises(ProviderError) as exc_info:
        client.post_json("/responses", {}, operation_id="op")
    assert exc_info.value.category == ProviderErrorCategory.MALFORMED


def test_meta_client_missing_key_fails_closed():
    settings = provider_settings(model_api_key=None)
    with pytest.raises(ProviderError) as exc_info:
        meta_client(settings, read_timeout_s=10)
    assert exc_info.value.category == ProviderErrorCategory.CONFIG
