"""Provider capability registry and explicit task router.

Selection is configuration-driven, one provider per task, no fallback
chains: a provider failure raises an explicit error, never silently
reroutes to another model or to fixtures.

Availability semantics: READY means "selected and eligible to
attempt" (static configuration check: selector valid, credential or
endpoint configured, breaker closed). It is NOT a live reachability
probe — the status endpoint performs no network I/O, so reachability
is learned from call outcomes (breaker) rather than from polling.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.providers.types import ProviderName, TaskKind


class Availability(str, Enum):
    READY = "ready"
    MISSING_CREDENTIAL = "missing_credential"
    MISCONFIGURED = "misconfigured"
    DISABLED = "disabled"  # not selected for this task
    BREAKER_OPEN = "breaker_open"  # recent repeated failures
    NOT_APPLICABLE = "not_applicable"  # fixture/mock in production


@dataclass(frozen=True)
class ProviderStatus:
    task: TaskKind
    provider: ProviderName
    model: str
    availability: Availability
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"task": self.task.value, "provider": self.provider.value,
                "model": self.model, "availability": self.availability.value,
                "reason": self.reason}


def _breaker_open(provider: ProviderName) -> bool:
    from app.providers.resilience import GUARDS
    return GUARDS.breaker(provider).is_open


def reader_status(settings: Settings) -> ProviderStatus:
    task = TaskKind.INVOICE_EXTRACTION
    selected = settings.reader_provider
    if selected == "fixture":
        if settings.environment == "production":
            return ProviderStatus(task, ProviderName.FIXTURE, "fixture",
                                  Availability.NOT_APPLICABLE,
                                  "fixture reader is dev/test only")
        if not settings.fixture_reader_enabled:
            return ProviderStatus(task, ProviderName.FIXTURE, "fixture",
                                  Availability.MISCONFIGURED,
                                  "AIRLOCK_FIXTURE_READER is off")
        return ProviderStatus(task, ProviderName.FIXTURE, "fixture",
                              Availability.READY, "fixture reader enabled")
    if selected == "spark":
        if not settings.model_api_key:
            return ProviderStatus(task, ProviderName.META,
                                  settings.spark_model,
                                  Availability.MISSING_CREDENTIAL,
                                  "MODEL_API_KEY is not configured")
        if _breaker_open(ProviderName.META):
            return ProviderStatus(task, ProviderName.META,
                                  settings.spark_model,
                                  Availability.BREAKER_OPEN,
                                  "recent repeated Meta API failures")
        return ProviderStatus(task, ProviderName.META, settings.spark_model,
                              Availability.READY, "Meta Model API configured")
    if selected == "spark-open":
        if not settings.baseten_api_key:
            return ProviderStatus(task, ProviderName.BASETEN,
                                  settings.baseten_spark_open_model,
                                  Availability.MISSING_CREDENTIAL,
                                  "BASETEN_API_KEY is not configured")
        if _breaker_open(ProviderName.BASETEN):
            return ProviderStatus(task, ProviderName.BASETEN,
                                  settings.baseten_spark_open_model,
                                  Availability.BREAKER_OPEN,
                                  "recent repeated Baseten failures")
        return ProviderStatus(task, ProviderName.BASETEN,
                              settings.baseten_spark_open_model,
                              Availability.READY, "Baseten configured")
    if selected == "glimmer":
        if _breaker_open(ProviderName.GLIMMER):
            return ProviderStatus(task, ProviderName.GLIMMER,
                                  settings.glimmer_model,
                                  Availability.BREAKER_OPEN,
                                  "recent repeated local runtime failures")
        return ProviderStatus(task, ProviderName.GLIMMER,
                              settings.glimmer_model, Availability.READY,
                              "local runtime selected; reachability is "
                              "learned from call outcomes")
    return ProviderStatus(task, ProviderName.FIXTURE, selected,
                          Availability.MISCONFIGURED,
                          f"unknown reader provider: {selected}")


def voice_status(settings: Settings) -> ProviderStatus:
    task = TaskKind.TRANSCRIPTION
    if settings.voice_provider == "mock":
        if settings.environment == "production":
            return ProviderStatus(task, ProviderName.MOCK, "mock",
                                  Availability.NOT_APPLICABLE,
                                  "mock voice is dev/test only")
        if not settings.fixture_reader_enabled:
            return ProviderStatus(task, ProviderName.MOCK, "mock",
                                  Availability.MISCONFIGURED,
                                  "AIRLOCK_FIXTURE_READER is off")
        return ProviderStatus(task, ProviderName.MOCK, "mock",
                              Availability.READY, "mock voice enabled")
    if settings.voice_provider == "meta":
        if not settings.model_api_key:
            return ProviderStatus(task, ProviderName.META,
                                  settings.voice_model,
                                  Availability.MISSING_CREDENTIAL,
                                  "MODEL_API_KEY is not configured")
        if _breaker_open(ProviderName.META):
            return ProviderStatus(task, ProviderName.META,
                                  settings.voice_model,
                                  Availability.BREAKER_OPEN,
                                  "recent repeated Meta API failures")
        return ProviderStatus(task, ProviderName.META, settings.voice_model,
                              Availability.READY, "Meta Model API configured")
    return ProviderStatus(task, ProviderName.MOCK, settings.voice_provider,
                          Availability.MISCONFIGURED,
                          f"unknown voice provider: {settings.voice_provider}")


def vision_status(settings: Settings) -> ProviderStatus:
    task = TaskKind.SEGMENTATION
    if settings.vision_provider == "mock":
        if settings.environment == "production":
            return ProviderStatus(task, ProviderName.MOCK, "mock",
                                  Availability.NOT_APPLICABLE,
                                  "mock vision is dev/test only")
        if not settings.fixture_reader_enabled:
            return ProviderStatus(task, ProviderName.MOCK, "mock",
                                  Availability.MISCONFIGURED,
                                  "AIRLOCK_FIXTURE_READER is off")
        return ProviderStatus(task, ProviderName.MOCK, "mock",
                              Availability.READY, "mock vision enabled")
    if settings.vision_provider == "sam":
        if not settings.model_api_key:
            return ProviderStatus(task, ProviderName.META, settings.sam_model,
                                  Availability.MISSING_CREDENTIAL,
                                  "MODEL_API_KEY is not configured")
        if _breaker_open(ProviderName.META):
            return ProviderStatus(task, ProviderName.META, settings.sam_model,
                                  Availability.BREAKER_OPEN,
                                  "recent repeated Meta API failures")
        return ProviderStatus(task, ProviderName.META, settings.sam_model,
                              Availability.READY, "Meta Model API configured")
    return ProviderStatus(task, ProviderName.MOCK, settings.vision_provider,
                          Availability.MISCONFIGURED,
                          f"unknown vision provider: {settings.vision_provider}")


def all_statuses(settings: Settings) -> list[ProviderStatus]:
    return [reader_status(settings), voice_status(settings),
            vision_status(settings)]


def _require_ready(status: ProviderStatus, *,
                   unavailable_code: str = ErrorCode.API_UNAVAILABLE) -> None:
    if status.availability != Availability.READY:
        raise AppError(unavailable_code,
                       f"{status.task.value} provider unavailable: "
                       f"{status.reason}")


def resolve_reader(settings: Settings, **kwargs: Any) -> Any:
    """Build the configured invoice reader (fail closed, no fallback).

    Selection failures (disabled, unconfigured, missing credential,
    breaker open) surface as E_READER_UNAVAILABLE — the same code the
    reader itself raises — keeping them distinct from transport
    failures (E_API_UNAVAILABLE) raised by constructed readers.
    """
    from app.adapters.readers import FixtureReader
    from app.providers.baseten import BasetenSparkReader
    from app.providers.glimmer import GlimmerReader
    from app.providers.spark import SparkReader
    _require_ready(reader_status(settings),
                   unavailable_code=ErrorCode.READER_UNAVAILABLE)
    if settings.reader_provider == "fixture":
        return FixtureReader(settings)
    if settings.reader_provider == "spark":
        return SparkReader(settings, **kwargs)
    if settings.reader_provider == "spark-open":
        return BasetenSparkReader(settings, **kwargs)
    return GlimmerReader(settings, **kwargs)


def resolve_voice(settings: Settings, **kwargs: Any) -> Any:
    """Build the configured voice transcriber (fail closed, no fallback)."""
    from app.adapters.transcription import MockAsr
    from app.providers.voice import MetaVoiceTranscriber
    _require_ready(voice_status(settings))
    if settings.voice_provider == "mock":
        return MockAsr(settings)
    return MetaVoiceTranscriber(settings, **kwargs)


def resolve_vision(settings: Settings, **kwargs: Any) -> Any:
    """Build the configured visual segmenter (fail closed, no fallback)."""
    from app.adapters.vision import MockSam
    from app.providers.sam import MetaSamSegmenter
    _require_ready(vision_status(settings))
    if settings.vision_provider == "mock":
        return MockSam(settings)
    return MetaSamSegmenter(settings, **kwargs)
