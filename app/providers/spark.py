"""Muse Spark invoice reader (Meta Model API, Responses API).

Sends the invoice PDF/image inline (base64 data URL, no server-side
file retention), requests schema-constrained output via `text.format`,
and finalizes through the shared extraction path. Results are T2 and
must still pass registry, arithmetic, duplicate, and R1–R10 checks.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import httpx

from app.adapters.readers import ReaderResult
from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.core.logging import get_logger
from app.providers.extraction import content_error, finalize_extraction
from app.providers.meta import (
    map_http_error,
    meta_client,
    parse_response_object,
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
    count_pdf_pages,
    jpeg_dimensions,
    png_dimensions,
    sniff_media,
)

logger = get_logger("airlock.providers.spark")

ADAPTER_ID = "meta-spark"
ADAPTER_VERSION = "3.0.0"

SCHEMA_NAME = "invoice_extraction"


class SparkReader:
    """Live invoice extraction via the Meta Model API."""

    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, settings: Settings, *,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def _media_part(self, data: bytes) -> tuple[dict[str, Any], int,
                                                 tuple[int, int] | None]:
        media_type, _ext = sniff_media(data, "invoice")
        encoded = base64.b64encode(data).decode("ascii")
        if media_type == "application/pdf":
            part = {"type": "input_file",
                    "file_data": f"data:application/pdf;base64,{encoded}",
                    "filename": "invoice.pdf"}
            return part, count_pdf_pages(data), None
        if media_type == "image/png":
            part = {"type": "input_image",
                    "image_url": f"data:image/png;base64,{encoded}"}
            return part, 1, png_dimensions(data)
        if media_type == "image/jpeg":
            part = {"type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{encoded}"}
            return part, 1, jpeg_dimensions(data)
        raise AppError(ErrorCode.API_UNAVAILABLE,
                       "Extraction provider does not support this media type")

    def read(self, artifact_bytes: bytes) -> ReaderResult:
        settings = self.settings
        digest = hashlib.sha256(artifact_bytes).hexdigest()
        part, page_count, image_dims = self._media_part(artifact_bytes)
        operation_id = new_id("op")
        payload = {
            "model": settings.spark_model,
            "instructions": EXTRACTION_INSTRUCTIONS,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text",
                 "text": "Extract the invoice fields from the attached "
                         "document as JSON."},
                part]}],
            # `strict: false` still constrains decoding to the schema
            # (documented); `strict: true` would additionally require
            # the strict subset (every key in `required`), which the
            # evidence block cannot satisfy. Local validation stays
            # authoritative.
            "text": {"format": {"type": "json_schema",
                                "name": SCHEMA_NAME,
                                "schema": EXTRACTION_JSON_SCHEMA,
                                "strict": False}},
            "store": False,
            "max_output_tokens": settings.spark_max_output_tokens,
        }
        client = meta_client(settings,
                             read_timeout_s=settings.extraction_timeout_s,
                             transport=self._transport)
        started = utc_ms()

        def _attempt(_attempt_no: int) -> Any:
            status, headers, body = client.post_json(
                "/responses", payload, operation_id=operation_id)
            if status != 200:
                raise map_http_error(status, headers, body,
                                     provider=ProviderName.META)
            return parse_response_object(body,
                                         requested_model=settings.spark_model,
                                         provider=ProviderName.META)

        try:
            parsed, attempts = call_guarded(
                ProviderName.META, operation_id, _attempt,
                max_inflight=settings.provider_max_inflight,
                max_retries=settings.provider_max_retries)
        except ProviderError as exc:
            if self._transport is not None:
                client.close()
            if exc.category == ProviderErrorCategory.REFUSAL:
                # A refusal is deterministic for this content: schema
                # failure (R8 DENY), not a retryable transport error.
                raise content_error(exc) from exc
            raise to_app_error(exc) from exc
        if self._transport is not None:
            client.close()
        duration = utc_ms() - started
        usage = Usage(provider_request_id=parsed.usage.provider_request_id,
                      input_tokens=parsed.usage.input_tokens,
                      output_tokens=parsed.usage.output_tokens,
                      duration_ms=duration, attempts=attempts)
        logger.info("spark extraction op=%s request=%s attempts=%d",
                    operation_id, parsed.response_id, attempts)
        try:
            reader_result, _ = finalize_extraction(
                parsed.output_text, provider=ProviderName.META,
                model=parsed.model, prompt_version=EXTRACTION_PROMPT_VERSION,
                artifact_sha256=digest, page_count=page_count,
                image_dims=image_dims, usage=usage,
                request_id=parsed.response_id)
        except ProviderError as exc:
            raise content_error(exc) from exc
        return reader_result
