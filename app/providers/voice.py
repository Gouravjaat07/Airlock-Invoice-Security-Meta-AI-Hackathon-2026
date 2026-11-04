"""Muse Voice Transcribe adapter (Meta Model API, file mode).

Stored recordings are transcribed with `POST /v1/asr/transcribe`
(multipart `request` JSON + `audio` file). WAV must be RIFF mono 16-bit
PCM within app caps; anything else is rejected, never converted.
Transcripts are T2: evidence only, never authentication/approval/policy.

Realtime WebSocket mode is intentionally NOT implemented: Airlock has
no realtime user-facing requirement.

`PUSH_TO_TALK` returns no `turns` array entries by design (single
utterance); turn validation still applies whenever turns arrive.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx

from app.adapters.transcription import Transcript
from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.core.logging import get_logger
from app.providers.audio import parse_wav
from app.providers.extraction import content_error
from app.providers.meta import map_http_error, meta_client
from app.providers.prompts import VOICE_TRANSCRIBE_MODE
from app.providers.resilience import call_guarded, utc_ms
from app.providers.types import (
    ProviderError,
    ProviderErrorCategory,
    ProviderName,
    TranscriptTurn,
    Usage,
    to_app_error,
)

logger = get_logger("airlock.providers.voice")

ADAPTER_ID = "meta-voice"
ADAPTER_VERSION = "3.0.0"

MAX_TRANSCRIPT_CHARS = 500_000
MAX_TURNS = 10_000


def _normalize_turn_id(raw_id: Any) -> str | None:
    """Documented `turnId` is an integer; non-empty strings are also
    accepted defensively. Returns the canonical string form, else None."""
    if isinstance(raw_id, bool):
        return None
    if isinstance(raw_id, int):
        return str(raw_id) if raw_id >= 0 else None
    if isinstance(raw_id, str) and raw_id:
        return raw_id
    return None


def _validate_turns(raw: Any, *, provider: ProviderName) -> list[TranscriptTurn]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Transcript turns are not a list",
                            provider=provider)
    if len(raw) > MAX_TURNS:
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Transcript turn count exceeded",
                            provider=provider)
    turns: list[TranscriptTurn] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ProviderError(ProviderErrorCategory.MALFORMED,
                                "Transcript turn is not an object",
                                provider=provider)
        turn_id = _normalize_turn_id(entry.get("turnId"))
        start = entry.get("startMs")
        end = entry.get("endMs")
        text = entry.get("transcript")
        speaker = entry.get("speaker")
        if (turn_id is None
                or isinstance(start, bool) or not isinstance(start, int)
                or start < 0
                or isinstance(end, bool) or not isinstance(end, int)
                or end < start
                or not isinstance(text, str)):
            raise ProviderError(ProviderErrorCategory.MALFORMED,
                                "Transcript turn has invalid fields",
                                provider=provider)
        if turn_id in seen:
            raise ProviderError(ProviderErrorCategory.MALFORMED,
                                "Transcript has a duplicate turn id",
                                provider=provider)
        seen.add(turn_id)
        if speaker is not None and (not isinstance(speaker, str) or not speaker):
            raise ProviderError(ProviderErrorCategory.MALFORMED,
                                "Transcript speaker label invalid",
                                provider=provider)
        turns.append(TranscriptTurn(turn_id=turn_id, start_ms=start,
                                   end_ms=end, text=text, speaker=speaker))
    return turns


class MetaVoiceTranscriber:
    """File transcription via the Meta Model API."""

    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, settings: Settings, *,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def transcribe(self, voice_bytes: bytes) -> Transcript:
        settings = self.settings
        digest = hashlib.sha256(voice_bytes).hexdigest()
        fmt = parse_wav(voice_bytes)  # strict format gate first
        if fmt.duration_s > settings.max_audio_seconds:
            raise AppError(ErrorCode.UPLOAD, "Audio exceeds duration limit")
        operation_id = new_id("op")
        request_doc = {"mode": VOICE_TRANSCRIBE_MODE,
                       "model": settings.voice_model,
                       "audioEncoding": "WAV"}
        client = meta_client(settings, read_timeout_s=settings.voice_timeout_s,
                             transport=self._transport)
        started = utc_ms()

        def _attempt(_attempt_no: int) -> Any:
            status, headers, body = client.post_multipart(
                f"/asr/transcribe?sessionId={operation_id}",
                data={"request": json.dumps(request_doc)},
                files={"audio": ("voice.wav", voice_bytes, "audio/wav")},
                operation_id=operation_id,
                extra_headers={"Accept": "application/json"})
            if status != 200:
                raise map_http_error(status, headers, body,
                                     provider=ProviderName.META)
            return body

        try:
            body, attempts = call_guarded(
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
        warnings: list[str] = []
        if not isinstance(body, dict):
            raise content_error(ProviderError(
                ProviderErrorCategory.MALFORMED,
                "Transcription response is not an object",
                provider=ProviderName.META))
        text = body.get("transcript")
        if not isinstance(text, str):
            raise content_error(ProviderError(
                ProviderErrorCategory.MALFORMED,
                "Transcription response missing transcript",
                provider=ProviderName.META))
        if len(text) > MAX_TRANSCRIPT_CHARS:
            raise content_error(ProviderError(
                ProviderErrorCategory.MALFORMED,
                "Transcript exceeded size limit",
                provider=ProviderName.META))
        try:
            turns = _validate_turns(body.get("turns"),
                                    provider=ProviderName.META)
        except ProviderError as exc:
            raise content_error(exc) from exc
        if body.get("turns") is None:
            warnings.append("no turn boundaries returned")
        if not text.strip():
            warnings.append("empty transcript returned")
        session_id = body.get("sessionId")
        request_id = session_id if isinstance(session_id, str) else operation_id
        usage = Usage(provider_request_id=request_id, duration_ms=duration,
                      attempts=attempts)
        logger.info("voice transcription op=%s turns=%d chars=%d attempts=%d",
                    operation_id, len(turns), len(text), attempts)
        return Transcript(
            text=text, artifact_sha256=digest,
            turns=tuple({"turn_id": t.turn_id, "start_ms": t.start_ms,
                         "end_ms": t.end_ms, "text": t.text,
                         "speaker": t.speaker} for t in turns),
            request_id=request_id, model_id=settings.voice_model,
            usage=usage.as_dict(), warnings=tuple(warnings))
