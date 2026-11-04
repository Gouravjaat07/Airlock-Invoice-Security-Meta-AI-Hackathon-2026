"""OpenAI-compatible chat/completions core (Baseten, Glimmer).

Both hosted Muse Spark Open and local runtimes serve this shape.
PDF bytes are NOT supported here (no file part exists); image parts
use `image_url` data URLs. Structured output uses `response_format`
json_schema where the endpoint honors it — local validation always
re-checks regardless. `read_chat_extraction` is the shared guarded
extraction call; the thin per-provider adapters only supply identity
and endpoint selection.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.adapters.readers import ReaderResult
from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.core.logging import get_logger
from app.providers.extraction import content_error, finalize_extraction
from app.providers.http import POOL, HttpClient, parse_retry_after
from app.providers.meta import (
    MAX_OUTPUT_TEXT_CHARS,
    RATE_LIMIT_CODES,
    envelope_error,
)
from app.providers.prompts import (
    EXTRACTION_INSTRUCTIONS,
    EXTRACTION_JSON_SCHEMA,
    EXTRACTION_PROMPT_VERSION,
)
from app.providers.resilience import call_guarded, utc_ms
from app.providers.types import (
    ProviderError,
    ProviderErrorCategory,
    ProviderName,
    Usage,
    to_app_error,
)
from app.storage.artifacts import (
    jpeg_dimensions,
    png_dimensions,
    sniff_media,
)

logger = get_logger("airlock.providers.chat")

# `strict: false` still constrains decoding to the schema (documented);
# `strict: true` would additionally require the strict subset (every
# key in `required`, no free-form maps), which the evidence block
# cannot satisfy. Local Pydantic validation stays authoritative.
STRUCTURED_STRICT = False


@dataclass
class ChatResult:
    content_text: str
    model: str
    response_id: str | None
    usage: Usage
    warnings: list[str] = field(default_factory=list)


def chat_client(*, pool_key: str, provider: ProviderName, base_url: str,
                credential: str | None, connect_timeout_s: float,
                read_timeout_s: float,
                transport: httpx.BaseTransport | None = None) -> HttpClient:
    return POOL.get(pool_key, provider=provider, base_url=base_url,
                    credential=credential,
                    connect_timeout_s=connect_timeout_s,
                    read_timeout_s=read_timeout_s, transport=transport)


def _refusal_shaped(lowered: str) -> bool:
    return ("policy" in lowered or "moderation" in lowered
            or "refus" in lowered or lowered == "content_policy_violation")


def map_chat_http_error(status: int, headers: httpx.Headers | dict,
                        parsed: Any, *, provider: ProviderName) -> ProviderError:
    """Map an OpenAI-compatible error status + envelope.

    Same category semantics as `map_http_error`; code matching stays
    substring-tolerant because hosted runtimes vary the exact codes.
    """
    code, typ = envelope_error(parsed)
    retry_after = parse_retry_after(headers)
    lowered = (code or "").lower()
    type_lower = (typ or "").lower()
    if (status in (401, 403) or "api_key" in lowered or "auth" in lowered
            or type_lower == "authentication_error"):
        return ProviderError(ProviderErrorCategory.AUTH,
                             "Provider rejected credentials", provider=provider)
    if status == 402 or type_lower == "billing_error":
        return ProviderError(ProviderErrorCategory.CONFIG,
                             "Provider billing issue; operator action required",
                             provider=provider)
    if status == 404:
        return ProviderError(ProviderErrorCategory.CONFIG,
                             "Provider reports unknown model or endpoint",
                             provider=provider)
    if (status == 429 or "rate" in lowered or "quota" in lowered
            or "billing" in lowered or lowered in RATE_LIMIT_CODES
            or type_lower == "rate_limit_error"):
        return ProviderError(ProviderErrorCategory.RATE_LIMIT,
                             "Provider rate limited", provider=provider,
                             retry_after_s=retry_after)
    if status == 408:
        return ProviderError(ProviderErrorCategory.TIMEOUT,
                             "Provider timed out", provider=provider)
    if status == 504 or "gateway_timeout" in lowered:
        return ProviderError(
            ProviderErrorCategory.INCOMPLETE,
            "Provider ran past its server time limit",
            provider=provider)
    if 400 <= status <= 499:
        if _refusal_shaped(lowered):
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


def parse_chat_response(body: Any, *, requested_model: str,
                        provider: ProviderName) -> ChatResult:
    warnings: list[str] = []
    if not isinstance(body, dict):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider returned a non-object response",
                            provider=provider)
    response_id = body.get("id")
    if response_id is not None and not isinstance(response_id, str):
        warnings.append("non-string response id ignored")
        response_id = None
    model = body.get("model")
    actual = model if isinstance(model, str) and model else requested_model
    if isinstance(model, str) and model and model != requested_model:
        warnings.append(f"model identity {model!r} differs from requested "
                        f"{requested_model!r}; using reported value")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider returned no choices", provider=provider)
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider choice is not an object",
                            provider=provider)
    finish = first.get("finish_reason")
    if finish not in (None, "stop"):
        if finish == "length":
            raise ProviderError(ProviderErrorCategory.INCOMPLETE,
                                "Provider output truncated", provider=provider)
        if finish == "content_filter":
            raise ProviderError(ProviderErrorCategory.REFUSAL,
                                "Provider refused the content",
                                provider=provider)
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            f"Unexpected finish reason: {finish!r}",
                            provider=provider)
    message = first.get("message")
    if not isinstance(message, dict):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider choice has no message", provider=provider)
    if message.get("tool_calls"):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Unexpected provider tool call", provider=provider)
    if message.get("refusal"):
        raise ProviderError(ProviderErrorCategory.REFUSAL,
                            "Provider refused the content",
                            provider=provider)
    content = message.get("content")
    if content is None:
        content = ""
    if isinstance(content, list):  # content-part lists: join text parts
        texts = [p.get("text", "") for p in content
                 if isinstance(p, dict) and isinstance(p.get("text"), str)]
        content = "".join(texts)
    if not isinstance(content, str):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider message content is not text",
                            provider=provider)
    if len(content) > MAX_OUTPUT_TEXT_CHARS:
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider output exceeded size limit",
                            provider=provider)
    usage = Usage(provider_request_id=response_id)
    raw_usage = body.get("usage")
    if isinstance(raw_usage, dict):
        in_tok = raw_usage.get("prompt_tokens")
        out_tok = raw_usage.get("completion_tokens")
        in_ok = isinstance(in_tok, int) and not isinstance(in_tok, bool) and in_tok >= 0
        out_ok = isinstance(out_tok, int) and not isinstance(out_tok, bool) and out_tok >= 0
        if (in_tok is not None and not in_ok) or (out_tok is not None and not out_ok):
            warnings.append("malformed usage metadata ignored")
        usage = Usage(provider_request_id=response_id,
                      input_tokens=in_tok if in_ok else None,
                      output_tokens=out_tok if out_ok else None)
    return ChatResult(content_text=content, model=actual,
                      response_id=response_id, usage=usage, warnings=warnings)


def _image_part(data: bytes, *, adapter_label: str
                ) -> tuple[dict[str, Any], tuple[int, int] | None]:
    """Chat-protocol image part (images only — no PDF file part exists)."""
    media_type, _ext = sniff_media(data, "invoice")
    if media_type == "application/pdf":
        raise AppError(ErrorCode.API_UNAVAILABLE,
                       f"{adapter_label} supports invoice images only; "
                       "PDF input is not available on this provider")
    encoded = base64.b64encode(data).decode("ascii")
    if media_type == "image/png":
        return ({"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                png_dimensions(data))
    if media_type == "image/jpeg":
        return ({"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                jpeg_dimensions(data))
    raise AppError(ErrorCode.API_UNAVAILABLE,
                   "Extraction provider does not support this media type")


def read_chat_extraction(*, adapter_label: str, log_name: str,
                         provider: ProviderName, model: str, base_url: str,
                         credential: str | None, pool_key: str,
                         settings: Settings, artifact_bytes: bytes,
                         transport: httpx.BaseTransport | None = None,
                         ) -> ReaderResult:
    """Shared invoice-extraction call for chat-protocol readers.

    One code path (request shape, guarded call, finalize) serves every
    OpenAI-compatible extraction adapter; the thin per-provider classes
    only supply identity and endpoint selection.
    """
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    image_part, image_dims = _image_part(artifact_bytes,
                                         adapter_label=adapter_label)
    operation_id = new_id("op")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": EXTRACTION_INSTRUCTIONS},
            {"role": "user", "content": [
                {"type": "text",
                 "text": "Extract the invoice fields from the attached "
                         "document as JSON."},
                image_part]}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "invoice_extraction",
                                            "schema": EXTRACTION_JSON_SCHEMA,
                                            "strict": STRUCTURED_STRICT}},
        "max_tokens": settings.spark_max_output_tokens,
    }
    client = chat_client(
        pool_key=pool_key, provider=provider, base_url=base_url,
        credential=credential,
        connect_timeout_s=settings.provider_connect_timeout_s,
        read_timeout_s=settings.extraction_timeout_s,
        transport=transport)
    started = utc_ms()

    def _attempt(_attempt_no: int) -> Any:
        status, headers, body = client.post_json(
            "/chat/completions", payload, operation_id=operation_id)
        if status != 200:
            raise map_chat_http_error(status, headers, body,
                                      provider=provider)
        return parse_chat_response(body, requested_model=model,
                                   provider=provider)

    try:
        chat, attempts = call_guarded(
            provider, operation_id, _attempt,
            max_inflight=settings.provider_max_inflight,
            max_retries=settings.provider_max_retries)
    except ProviderError as exc:
        if transport is not None:
            client.close()
        if exc.category == ProviderErrorCategory.REFUSAL:
            # A refusal is deterministic for this content: schema
            # failure (R8 DENY), not a retryable transport error.
            raise content_error(exc) from exc
        raise to_app_error(exc) from exc
    if transport is not None:
        client.close()
    duration = utc_ms() - started
    usage = Usage(provider_request_id=chat.usage.provider_request_id,
                  input_tokens=chat.usage.input_tokens,
                  output_tokens=chat.usage.output_tokens,
                  duration_ms=duration, attempts=attempts)
    logger.info("%s extraction op=%s request=%s attempts=%d",
                log_name, operation_id, chat.response_id, attempts)
    try:
        reader_result, _ = finalize_extraction(
            chat.content_text, provider=provider, model=chat.model,
            prompt_version=EXTRACTION_PROMPT_VERSION,
            artifact_sha256=digest, page_count=1, image_dims=image_dims,
            usage=usage, request_id=chat.response_id)
    except ProviderError as exc:
        raise content_error(exc) from exc
    return reader_result
