"""Registry/router tests: explicit selection, no hidden fallback."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.core.errors import AppError
from app.providers.registry import (
    all_statuses,
    reader_status,
    resolve_reader,
    resolve_voice,
    resolve_vision,
    vision_status,
    voice_status,
)
from app.providers.resilience import GUARDS
from app.providers.types import ProviderName
from tests.providers.helpers import provider_settings


def test_reader_selection_matrix():
    assert reader_status(provider_settings()).provider == ProviderName.META
    assert reader_status(provider_settings()).availability.value == "ready"
    assert reader_status(Settings(reader_provider="spark-open",
                                  baseten_api_key="tk")).provider == ProviderName.BASETEN
    assert reader_status(Settings(reader_provider="glimmer")).provider == \
        ProviderName.GLIMMER
    glimmer_reason = reader_status(
        Settings(reader_provider="glimmer")).reason
    assert "reachability is learned from call outcomes" in glimmer_reason
    fixture = Settings(reader_provider="fixture", fixture_reader_enabled=True)
    assert reader_status(fixture).availability.value == "ready"


def test_missing_credentials_reported():
    status = reader_status(Settings(reader_provider="spark"))
    assert status.availability.value == "missing_credential"
    assert "MODEL_API_KEY" in status.reason
    status = reader_status(Settings(reader_provider="spark-open"))
    assert status.availability.value == "missing_credential"
    status = voice_status(Settings(voice_provider="meta"))
    assert status.availability.value == "missing_credential"
    status = vision_status(Settings(vision_provider="sam"))
    assert status.availability.value == "missing_credential"


def test_fixture_requires_flag():
    status = reader_status(Settings(reader_provider="fixture"))
    assert status.availability.value == "misconfigured"
    assert voice_status(Settings()).availability.value == "misconfigured"
    assert vision_status(Settings()).availability.value == "misconfigured"


def test_production_rejects_doubles():
    prod = {"environment": "production", "fixture_reader_enabled": True}
    assert reader_status(Settings(reader_provider="fixture", **prod)
                         ).availability.value == "not_applicable"
    assert voice_status(Settings(voice_provider="mock", **prod)
                        ).availability.value == "not_applicable"
    assert vision_status(Settings(vision_provider="mock", **prod)
                         ).availability.value == "not_applicable"


def test_unknown_provider_misconfigured():
    assert reader_status(Settings(reader_provider="watson")
                         ).availability.value == "misconfigured"


def test_breaker_open_reported():
    breaker = GUARDS.breaker(ProviderName.META)
    for _ in range(5):
        breaker.record_failure()
    assert reader_status(provider_settings()).availability.value == \
        "breaker_open"


def test_resolve_no_fallback_on_failure():
    # Misconfigured selection raises; it never reroutes to fixtures.
    # Reader selection failures use the reader code (distinct from the
    # transport failures a constructed reader raises at call time).
    with pytest.raises(AppError) as exc_info:
        resolve_reader(Settings(reader_provider="spark"))
    assert exc_info.value.code == "E_READER_UNAVAILABLE"
    assert "MODEL_API_KEY" in exc_info.value.message
    with pytest.raises(AppError) as exc_info:
        resolve_voice(Settings(voice_provider="meta"))
    assert exc_info.value.code == "E_API_UNAVAILABLE"
    with pytest.raises(AppError) as exc_info:
        resolve_vision(Settings(vision_provider="sam"))
    assert exc_info.value.code == "E_API_UNAVAILABLE"


def test_resolve_reader_disabled_fails_closed_with_reader_code():
    settings = Settings(reader_provider="fixture")
    assert settings.fixture_reader_enabled is False
    with pytest.raises(AppError) as exc_info:
        resolve_reader(settings)
    assert exc_info.value.code == "E_READER_UNAVAILABLE"


def test_resolve_constructs_adapters():
    assert resolve_reader(provider_settings()).adapter_id == "meta-spark"
    assert resolve_voice(provider_settings()).adapter_id == "meta-voice"
    assert resolve_vision(provider_settings()).adapter_id == "meta-sam"
    assert resolve_reader(Settings(reader_provider="spark-open",
                                   baseten_api_key="tk")).adapter_id == \
        "baseten-spark-open"
    assert resolve_reader(Settings(reader_provider="glimmer")).adapter_id == \
        "glimmer-local"
    fixture = Settings(reader_provider="fixture", fixture_reader_enabled=True)
    assert resolve_reader(fixture).adapter_id == "fixture-reader"


def test_all_statuses_shape_safe():
    settings = provider_settings()
    payload = [status.as_dict() for status in all_statuses(settings)]
    assert [entry["task"] for entry in payload] == [
        "invoice_extraction", "transcription", "segmentation"]
    assert "tk" not in repr(payload)
