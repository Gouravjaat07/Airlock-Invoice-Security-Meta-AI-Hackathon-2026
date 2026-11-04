"""SAM 3.1 delivery segmenter (Meta Model API, Responses SSE).

Sends one concept request (noun phrase from the trusted catalogue
label) with the delivery image/video inline, accumulates the streamed
special-token lane, parses it with the documented grammar, and
decodes every mask raster with the official codec port
(`app.providers.sam_mask`). The validated result is a track-aware
object count plus bounded box evidence with decoded mask areas —
geometry only, never a quantity verdict. R7 keeps its deterministic
fail-safe semantics; SAM output alone never satisfies it.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import httpx

from app.adapters.vision import SamEvidence
from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.core.logging import get_logger
from app.providers.extraction import content_error
from app.providers.http import _HttpStatusSignal
from app.providers.meta import (
    accumulate_sse_text,
    map_http_error,
    meta_client,
)
from app.providers.prompts import SAM_PROMPT_VERSION, sam_concept_prompt
from app.providers.resilience import call_guarded, utc_ms
from app.providers.sam_mask import (
    MAX_LANE_PIXELS,
    MaskDecodeError,
    decode_mask_to_raster,
)
from app.providers.sam_parse import (
    SamGrammarError,
    distinct_count,
    parse_lane,
)
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

logger = get_logger("airlock.providers.sam")

ADAPTER_ID = "meta-sam"
ADAPTER_VERSION = "3.0.0"

MAX_STORED_BOXES = 500


class MetaSamSegmenter:
    """Delivery segmentation via SAM 3.1."""

    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, settings: Settings, *,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def _media_part(self, data: bytes) -> tuple[dict[str, Any],
                                                tuple[int, int] | None]:
        media_type, _ext = sniff_media(data, "delivery")
        encoded = base64.b64encode(data).decode("ascii")
        if media_type == "image/png":
            return ({"type": "input_image",
                     "image_url": f"data:image/png;base64,{encoded}"},
                    png_dimensions(data))
        if media_type == "image/jpeg":
            return ({"type": "input_image",
                     "image_url": f"data:image/jpeg;base64,{encoded}"},
                    jpeg_dimensions(data))
        if media_type == "video/mp4":
            # Dimensions are header-unknown for MP4; the lane's own w/h is
            # consistency-checked instead (single media size required).
            return ({"type": "input_video",
                     "video_url": f"data:video/mp4;base64,{encoded}"}, None)
        raise AppError(ErrorCode.API_UNAVAILABLE,
                       "Segmentation provider does not support this media type")

    def count(self, delivery_bytes: bytes, *, catalogue_item_id: str,
              catalogue_label: str) -> SamEvidence:
        settings = self.settings
        digest = hashlib.sha256(delivery_bytes).hexdigest()
        part, expected_dims = self._media_part(delivery_bytes)
        concept = sam_concept_prompt(catalogue_label)
        if not concept:
            raise AppError(ErrorCode.API_UNAVAILABLE,
                           "Catalogue label is unusable as a concept prompt")
        operation_id = new_id("op")
        payload = {
            "model": settings.sam_model,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": concept},
                part]}],
            "store": False,
            "stream": True,
            # Compact masks (documented `metadata.mask_encoding`); the
            # parser still accepts `lossless` per record (read the
            # marker, never assume the request was honored).
            "metadata": {"mask_encoding": "one_bit"},
        }
        client = meta_client(settings, read_timeout_s=settings.sam_timeout_s,
                             transport=self._transport)
        started = utc_ms()

        def _attempt(_attempt_no: int) -> Any:
            try:
                events = client.stream_sse("/responses", payload,
                                           operation_id=operation_id)
                return accumulate_sse_text(
                    events, requested_model=settings.sam_model,
                    provider=ProviderName.META)
            except _HttpStatusSignal as sig:
                parsed: Any = None
                try:
                    parsed = json.loads(bytes(sig.body).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    parsed = None
                raise map_http_error(sig.status, sig.headers, parsed,
                                     provider=ProviderName.META)

        try:
            parsed, attempts = call_guarded(
                ProviderName.META, operation_id, _attempt,
                max_inflight=settings.provider_max_inflight,
                max_retries=settings.provider_max_retries)
        except ProviderError as exc:
            if self._transport is not None:
                client.close()
            raise to_app_error(exc) from exc
        if self._transport is not None:
            client.close()
        duration = utc_ms() - started
        try:
            lane = parse_lane(parsed.output_text)
        except SamGrammarError as exc:
            raise content_error(ProviderError(
                ProviderErrorCategory.MALFORMED,
                f"Segmentation output failed grammar validation: {exc}",
                provider=ProviderName.META,
                provider_request_id=parsed.response_id)) from exc
        warnings = list(parsed.warnings)
        sizes = {(box.width, box.height) for frame in lane.frames
                 for box in frame.boxes}
        if len(sizes) > 1:
            raise content_error(ProviderError(
                ProviderErrorCategory.MALFORMED,
                "Segmentation lane reports inconsistent media sizes",
                provider=ProviderName.META,
                provider_request_id=parsed.response_id))
        if expected_dims is not None and sizes and sizes != {expected_dims}:
            raise content_error(ProviderError(
                ProviderErrorCategory.MALFORMED,
                "Segmentation lane media size mismatches the artifact",
                provider=ProviderName.META,
                provider_request_id=parsed.response_id))
        total = distinct_count(lane)
        if total < settings.sam_count_min or total > settings.sam_count_max:
            raise AppError(ErrorCode.API_UNAVAILABLE,
                           f"SAM count {total} outside configured range")
        boxes: list[dict[str, Any]] = []
        decoded_pixels = 0
        for frame in lane.frames:
            for box, mask in zip(frame.boxes, frame.masks):
                decoded_pixels += mask.raster_h * mask.raster_w
                if decoded_pixels > MAX_LANE_PIXELS:
                    raise content_error(ProviderError(
                        ProviderErrorCategory.MALFORMED,
                        "Segmentation masks exceed the decode budget",
                        provider=ProviderName.META,
                        provider_request_id=parsed.response_id))
                marker = "~" if mask.encoding == "lossless" else "!"
                try:
                    raster = decode_mask_to_raster(
                        encoding=mask.encoding, width=mask.raster_w,
                        height=mask.raster_h, payload=marker + mask.payload)
                except MaskDecodeError as exc:
                    raise content_error(ProviderError(
                        ProviderErrorCategory.MALFORMED,
                        "Segmentation mask failed validation",
                        provider=ProviderName.META,
                        provider_request_id=parsed.response_id)) from exc
                boxes.append({"object_id": box.object_id,
                              "frame": frame.index, "x1": box.x1,
                              "y1": box.y1, "x2": box.x2, "y2": box.y2,
                              "mask_area": len(raster),
                              "mask_pixels": sum(raster)})
        if len(boxes) > MAX_STORED_BOXES:
            warnings.append(f"{len(boxes) - MAX_STORED_BOXES} boxes omitted "
                            f"from the evidence record")
            boxes = boxes[:MAX_STORED_BOXES]
        usage = Usage(provider_request_id=parsed.response_id,
                      input_tokens=parsed.usage.input_tokens,
                      output_tokens=parsed.usage.output_tokens,
                      duration_ms=duration, attempts=attempts)
        logger.info("sam segmentation op=%s objects=%d frames=%d attempts=%d",
                    operation_id, total, len(lane.frames), attempts)
        return SamEvidence(
            count=total, catalogue_item_id=catalogue_item_id,
            catalogue_label=catalogue_label, artifact_sha256=digest,
            frames_observed=len(lane.frames), boxes=tuple(boxes),
            request_id=parsed.response_id, model_id=parsed.model,
            usage={**usage.as_dict(),
                   "prompt_version": SAM_PROMPT_VERSION},
            warnings=tuple(warnings))
