"""Meta Model API client core: Responses API + shared error mapping.

Implements the documented `POST /v1/responses` contract (2026-11-01):
Bearer auth, `store:false` (no server-side retention), structured
output via `text.format`, SSE streaming, `{error:{...}}` envelopes.
Task layers (Spark/SAM/voice) own request building and result parsing;
this module owns transport, retries plumbing, and safe error mapping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings
from app.core.logging import get_logger
from app.providers.http import POOL, HttpClient, parse_retry_after
from app.providers.types import (
    ProviderError,
    ProviderErrorCategory,
    ProviderName,
    Usage,
)

logger = get_logger("airlock.providers.meta")

MAX_OUTPUT_TEXT_CHARS = 500_000


@dataclass
class ParsedResponse:
    response_id: str | None
    status: str
    model: str | None
    output_text: str
    usage: Usage
    error_code: str | None = None
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)


def meta_client(settings: Settings, *, read_timeout_s: float,
                transport: httpx.BaseTransport | None = None) -> HttpClient:
    if settings.model_api_key is None:
        # Fail closed even under `python -O` (no assert for security gates).
        raise ProviderError(ProviderErrorCategory.CONFIG,
                            "MODEL_API_KEY is not configured",
                            provider=ProviderName.META)
    return POOL.get(f"meta:{read_timeout_s}", provider=ProviderName.META,
                    base_url=settings.meta_api_base,
                    credential=settings.model_api_key,
                    connect_timeout_s=settings.provider_connect_timeout_s,
                    read_timeout_s=read_timeout_s, transport=transport)


def envelope_error(parsed: Any) -> tuple[str | None, str | None]:
    """Split a `{error:{code,type}}` envelope (either field may be null)."""
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            typ = err.get("type")
            return (str(code) if code is not None else None,
                    str(typ) if typ is not None else None)
    return None, None


RATE_LIMIT_CODES = frozenset({
    "rate_limit_exceeded", "quota_exceeded", "billing_limit",
    "insufficient_quota",
})


def map_http_error(status: int, headers: httpx.Headers | dict, parsed: Any, *,
                   provider: ProviderName) -> ProviderError:
    """Map an HTTP error status + envelope to a typed ProviderError.

    Follows the documented contract (dev.meta.ai/docs/error-handling):
    status first, then the stable `type`, then `code` (`code` is often
    null on validation errors). 504/gateway_timeout is NOT retried —
    the same request would time out again. Unknown statuses fail
    closed without retries.
    """
    code, typ = envelope_error(parsed)
    retry_after = parse_retry_after(headers)
    lowered = (code or "").lower()
    type_lower = (typ or "").lower()
    if (status in (401, 403) or lowered == "invalid_api_key"
            or type_lower == "authentication_error"):
        return ProviderError(ProviderErrorCategory.AUTH,
                             "Provider rejected credentials", provider=provider)
    if status == 402 or type_lower == "billing_error":
        return ProviderError(ProviderErrorCategory.CONFIG,
                             "Provider billing issue; operator action required",
                             provider=provider)
    if status == 404:
        if lowered == "model_not_found":
            return ProviderError(ProviderErrorCategory.CONFIG,
                                 "Provider reports unknown model",
                                 provider=provider)
        return ProviderError(ProviderErrorCategory.BAD_REQUEST,
                             "Provider reports unknown endpoint",
                             provider=provider)
    if (status == 429 or type_lower == "rate_limit_error"
            or lowered in RATE_LIMIT_CODES):
        return ProviderError(ProviderErrorCategory.RATE_LIMIT,
                             "Provider rate limited", provider=provider,
                             retry_after_s=retry_after)
    if status == 408:
        return ProviderError(ProviderErrorCategory.TIMEOUT,
                             "Provider timed out", provider=provider)
    if status == 504 or lowered == "gateway_timeout":
        return ProviderError(
            ProviderErrorCategory.INCOMPLETE,
            "Provider ran past its server time limit",
            provider=provider)
    if 400 <= status <= 499:
        if lowered == "content_policy_violation":
            return ProviderError(ProviderErrorCategory.REFUSAL,
                                 "Provider refused the content",
                                 provider=provider)
        return ProviderError(ProviderErrorCategory.BAD_REQUEST,
                             "Provider rejected the request", provider=provider)
    if 500 <= status <= 599:
        return ProviderError(ProviderErrorCategory.SERVER,
                             "Provider server error", provider=provider,
                             retry_after_s=retry_after)
    return ProviderError(ProviderErrorCategory.MALFORMED,
                         f"Unexpected provider status: {status}",
                         provider=provider)


def _usage_from(payload: Any, warnings: list[str]) -> Usage:
    if not isinstance(payload, dict):
        return Usage()
    def _nonneg_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value >= 0:
            return value
        return None
    in_tok = _nonneg_int(payload.get("input_tokens"))
    out_tok = _nonneg_int(payload.get("output_tokens"))
    if (payload.get("input_tokens") is not None and in_tok is None) or \
       (payload.get("output_tokens") is not None and out_tok is None):
        warnings.append("malformed usage metadata ignored")
    return Usage(input_tokens=in_tok, output_tokens=out_tok)


def parse_response_object(body: Any, *, requested_model: str,
                          provider: ProviderName) -> ParsedResponse:
    """Validate one Responses API object into normalized parts."""
    warnings: list[str] = []
    if not isinstance(body, dict):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider returned a non-object response",
                            provider=provider)
    status = body.get("status")
    if not isinstance(status, str) or not status:
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider response missing status",
                            provider=provider)
    response_id = body.get("id")
    if response_id is not None and not isinstance(response_id, str):
        warnings.append("non-string response id ignored")
        response_id = None
    model = body.get("model")
    actual_model = model if isinstance(model, str) and model else None
    if actual_model is not None and actual_model != requested_model:
        warnings.append(f"model identity {actual_model!r} differs from "
                        f"requested {requested_model!r}; using reported value")
    usage = _usage_from(body.get("usage"), warnings)
    if usage.provider_request_id is None and response_id:
        usage = Usage(provider_request_id=response_id,
                      input_tokens=usage.input_tokens,
                      output_tokens=usage.output_tokens)

    if status == "failed":
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        code = err.get("code")
        code_s = str(code) if code is not None else None
        if (code_s or "").lower() == "content_policy_violation":
            raise ProviderError(ProviderErrorCategory.REFUSAL,
                                "Provider refused the content",
                                provider=provider,
                                provider_request_id=response_id)
        raise ProviderError(ProviderErrorCategory.SERVER,
                            "Provider reported response failure",
                            provider=provider,
                            provider_request_id=response_id)
    if status == "incomplete":
        raise ProviderError(ProviderErrorCategory.INCOMPLETE,
                            "Provider returned an incomplete response",
                            provider=provider,
                            provider_request_id=response_id)
    if status not in ("completed", "queued", "in_progress"):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            f"Unexpected provider status: {status}",
                            provider=provider)
    if status != "completed":
        # Non-streaming calls must return terminal objects; anything else
        # is a protocol violation (streaming has its own accumulator).
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            f"Non-terminal provider status: {status}",
                            provider=provider)

    output = body.get("output")
    if not isinstance(output, list):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider response missing output items",
                            provider=provider)
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            raise ProviderError(ProviderErrorCategory.MALFORMED,
                                "Provider output item is not an object",
                                provider=provider)
        kind = item.get("type")
        if kind == "reasoning":
            continue  # never requested, never persisted
        if kind == "function_call":
            raise ProviderError(ProviderErrorCategory.MALFORMED,
                                "Unexpected provider tool call",
                                provider=provider)
        if kind != "message":
            warnings.append(f"unknown output item {kind!r} ignored")
            continue
        content = item.get("content")
        if not isinstance(content, list):
            raise ProviderError(ProviderErrorCategory.MALFORMED,
                                "Provider message content is not a list",
                                provider=provider)
        for part in content:
            if not isinstance(part, dict):
                raise ProviderError(ProviderErrorCategory.MALFORMED,
                                    "Provider content part is not an object",
                                    provider=provider)
            part_type = part.get("type")
            if part_type == "output_text":
                text = part.get("text")
                if not isinstance(text, str):
                    raise ProviderError(ProviderErrorCategory.MALFORMED,
                                        "Provider text part is not a string",
                                        provider=provider)
                texts.append(text)
            elif part_type == "refusal":
                raise ProviderError(ProviderErrorCategory.REFUSAL,
                                    "Provider refused the content",
                                    provider=provider,
                                    provider_request_id=response_id)
            else:
                warnings.append(f"unknown content part {part_type!r} ignored")
    joined = "".join(texts)
    if len(joined) > MAX_OUTPUT_TEXT_CHARS:
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider output exceeded size limit",
                            provider=provider)
    return ParsedResponse(response_id=response_id, status=status,
                          model=actual_model or requested_model,
                          output_text=joined, usage=usage, warnings=warnings)


def _stream_json(data: str, *, provider: ProviderName,
                 what: str = "Malformed stream event") -> Any:
    try:
        return json.loads(data)
    except ValueError:
        raise ProviderError(ProviderErrorCategory.MALFORMED, what,
                            provider=provider)


def _stream_error(data: str, *, provider: ProviderName) -> ProviderError:
    """Map a terminal mid-stream `error` event (shutdown/overload codes
    are retryable; the caller retries the full request)."""
    payload = _stream_json(data, provider=provider,
                           what="Malformed stream error event")
    code: str | None = None
    type_lower = ""
    if isinstance(payload, dict):
        raw_code = payload.get("code")
        if raw_code is None and isinstance(payload.get("error"), dict):
            raw_code = payload["error"].get("code")
            raw_type = payload["error"].get("type")
        else:
            raw_type = payload.get("type")
        code = str(raw_code).lower() if raw_code is not None else None
        type_lower = str(raw_type).lower() if raw_type is not None else ""
    if code in RATE_LIMIT_CODES or type_lower == "rate_limit_error":
        return ProviderError(ProviderErrorCategory.RATE_LIMIT,
                             "Provider rate limited mid-stream",
                             provider=provider)
    if code == "content_policy_violation":
        return ProviderError(ProviderErrorCategory.REFUSAL,
                             "Provider refused the content",
                             provider=provider)
    return ProviderError(ProviderErrorCategory.SERVER,
                         "Provider stream failed", provider=provider)


def accumulate_sse_text(events: Any, *, requested_model: str,
                        provider: ProviderName) -> ParsedResponse:
    """Fold a Responses SSE event stream into one ParsedResponse.

    `events` yields (event_name, data) pairs from `HttpClient.stream_sse`.
    Handles output-text deltas, completion/failure envelopes, terminal
    error events, and usage. Event typing is accepted from the SSE
    `event:` line (SDK-style streams) or from the `type` field inside
    the JSON body (docs examples read the body only) — whichever one
    the stream provides.
    """
    warnings: list[str] = []
    chunks: list[str] = []
    total = 0
    final_object: dict | None = None
    for event_name, data in events:
        if data == "[DONE]":
            continue  # end-of-stream marker
        etype = event_name
        payload: Any = None
        if etype is None:
            payload = _stream_json(data, provider=provider)
            if isinstance(payload, dict):
                maybe = payload.get("type")
                etype = maybe if isinstance(maybe, str) else None
        if etype == "response.output_text.delta":
            if payload is None:
                payload = _stream_json(data, provider=provider)
            delta = payload.get("delta") if isinstance(payload, dict) else None
            if not isinstance(delta, str):
                raise ProviderError(ProviderErrorCategory.MALFORMED,
                                    "Malformed stream delta",
                                    provider=provider)
            total += len(delta)
            if total > MAX_OUTPUT_TEXT_CHARS:
                raise ProviderError(ProviderErrorCategory.MALFORMED,
                                    "Provider stream exceeded size limit",
                                    provider=provider)
            chunks.append(delta)
        elif etype in ("response.completed", "response.failed",
                       "response.incomplete"):
            if payload is None:
                payload = _stream_json(
                    data, provider=provider,
                    what="Malformed stream envelope")
            response = payload.get("response") if isinstance(payload,
                                                             dict) else None
            if not isinstance(response, dict):
                raise ProviderError(ProviderErrorCategory.MALFORMED,
                                    "Stream completion missing response",
                                    provider=provider)
            final_object = response
        elif etype == "error":
            raise _stream_error(data, provider=provider)
        elif etype is None or etype.startswith("response."):
            continue  # lifecycle/heartbeat events carry no text
        else:
            warnings.append(f"unknown stream event {etype!r} ignored")
    if final_object is None:
        raise ProviderError(ProviderErrorCategory.INCOMPLETE,
                            "Provider stream ended without completion",
                            provider=provider)
    parsed = parse_response_object(final_object,
                                   requested_model=requested_model,
                                   provider=provider)
    lane = "".join(chunks)
    # The lane text (deltas) is authoritative for streamed content; the
    # envelope carries status/usage. Prefer whichever is non-empty.
    text = lane if lane else parsed.output_text
    return ParsedResponse(response_id=parsed.response_id,
                          status=parsed.status, model=parsed.model,
                          output_text=text, usage=parsed.usage,
                          warnings=[*parsed.warnings, *warnings])


__all__ = [
    "MAX_OUTPUT_TEXT_CHARS",
    "ParsedResponse",
    "RATE_LIMIT_CODES",
    "accumulate_sse_text",
    "envelope_error",
    "map_http_error",
    "meta_client",
    "parse_response_object",
]
