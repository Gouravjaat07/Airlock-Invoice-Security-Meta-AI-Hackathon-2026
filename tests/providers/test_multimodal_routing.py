"""Multimodal routing regression: exact selection, no overrides, no fallback.

Covers the live development configuration (spark reader + meta voice +
sam vision): authoritative model IDs stay consistent across config,
smoke runners, and validators; the dev fixture flag never overrides an
explicit live selection; unknown selections fail closed; production
refuses doubles; credentials stay separated.
"""

from __future__ import annotations

import pytest

from app.config import Settings, load_settings
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
from app.providers.types import ProviderName
from tests.providers.helpers import FAKE_KEY, provider_settings

SPARK_MODEL = "muse-spark-1.3"
VOICE_MODEL = "muse-voice-transcribe-1.0"
SAM_MODEL = "sam-3.1"
SPARK_OPEN_MODEL = "meta-models/muse-spark-open-1026"


def test_authoritative_model_ids_in_app_config():
    defaults = Settings()
    assert defaults.spark_model == SPARK_MODEL
    assert defaults.voice_model == VOICE_MODEL
    assert defaults.sam_model == SAM_MODEL
    assert defaults.baseten_spark_open_model == SPARK_OPEN_MODEL


def test_authoritative_model_ids_in_smoke_runners():
    import smoke_baseten as baseten_mod
    import smoke_meta as meta_mod
    import smoke_phase3 as phase3_mod
    import smoke_sam as sam_mod
    import smoke_voice as voice_mod

    assert meta_mod.CONFIG.model_default == SPARK_MODEL
    assert voice_mod.CONFIG.model_default == VOICE_MODEL
    assert sam_mod.CONFIG.model_default == SAM_MODEL
    assert baseten_mod.CONFIG.model_default == SPARK_OPEN_MODEL
    assert phase3_mod.CONFIGS["meta-spark"].model_default == SPARK_MODEL
    assert phase3_mod.CONFIGS["meta-voice"].model_default == VOICE_MODEL
    assert phase3_mod.CONFIGS["meta-sam"].model_default == SAM_MODEL
    assert phase3_mod.CONFIGS["baseten"].model_default == SPARK_OPEN_MODEL


def test_authoritative_model_ids_in_validate_config():
    import validate_config

    assert validate_config.EXPECTED_SPARK_MODEL == SPARK_MODEL
    assert (validate_config.DEFAULT_BASETEN_SPARK_OPEN_MODEL
            == SPARK_OPEN_MODEL)


def test_all_three_live_providers_ready():
    settings = provider_settings()
    assert settings.reader_provider == "spark"
    assert settings.voice_provider == "meta"
    assert settings.vision_provider == "sam"
    statuses = {status.task.value: status for status in all_statuses(settings)}
    assert statuses["invoice_extraction"].provider == ProviderName.META
    assert statuses["invoice_extraction"].model == SPARK_MODEL
    assert statuses["transcription"].provider == ProviderName.META
    assert statuses["transcription"].model == VOICE_MODEL
    assert statuses["segmentation"].provider == ProviderName.META
    assert statuses["segmentation"].model == SAM_MODEL
    assert all(status.availability.value == "ready"
               for status in statuses.values())


def test_fixture_flag_never_overrides_explicit_live_selection():
    # AIRLOCK_FIXTURE_READER=1 keeps dev/test doubles available, but an
    # explicit live selection must still resolve to the live adapter.
    settings = provider_settings(fixture_reader_enabled=True)
    assert resolve_reader(settings).adapter_id == "meta-spark"
    assert resolve_voice(settings).adapter_id == "meta-voice"
    assert resolve_vision(settings).adapter_id == "meta-sam"
    assert reader_status(settings).provider == ProviderName.META
    assert voice_status(settings).provider == ProviderName.META
    assert vision_status(settings).provider == ProviderName.META


def test_explicit_doubles_still_resolve_with_flag():
    settings = provider_settings(
        reader_provider="fixture", voice_provider="mock",
        vision_provider="sam", fixture_reader_enabled=True)
    assert resolve_reader(settings).adapter_id == "fixture-reader"
    assert resolve_voice(settings).adapter_id == "mock-asr"
    assert resolve_vision(settings).adapter_id == "meta-sam"


def test_unknown_selection_fails_closed_without_fallback():
    for kwargs in ({"reader_provider": "watson"},
                   {"voice_provider": "watson"},
                   {"vision_provider": "watson"}):
        settings = provider_settings(**kwargs)
        statuses = {status.task.value: status
                    for status in all_statuses(settings)}
        flagged = [status for status in statuses.values()
                   if status.availability.value == "misconfigured"]
        assert len(flagged) == 1
    with pytest.raises(AppError):
        resolve_reader(provider_settings(reader_provider="watson"))
    with pytest.raises(AppError):
        resolve_voice(provider_settings(voice_provider="watson"))
    with pytest.raises(AppError):
        resolve_vision(provider_settings(vision_provider="watson"))


def test_production_doubles_unresolvable():
    prod = {"environment": "production", "model_api_key": FAKE_KEY,
            "fixture_reader_enabled": False}
    with pytest.raises(AppError):
        resolve_reader(Settings(reader_provider="fixture", **prod))
    with pytest.raises(AppError):
        resolve_voice(Settings(voice_provider="mock", **prod))
    with pytest.raises(AppError):
        resolve_vision(Settings(vision_provider="mock", **prod))


def test_meta_and_baseten_keys_must_differ_at_config_load():
    with pytest.raises(AppError) as exc_info:
        load_settings({"MODEL_API_KEY": "same-key",
                       "BASETEN_API_KEY": "same-key"})
    assert "must differ" in exc_info.value.message
    settings = load_settings({"MODEL_API_KEY": "meta-key",
                              "BASETEN_API_KEY": "baseten-key"})
    assert settings.model_api_key == "meta-key"
    assert settings.baseten_api_key == "baseten-key"


def test_env_selection_round_trip():
    settings = load_settings({
        "AIRLOCK_READER_PROVIDER": "spark",
        "AIRLOCK_VOICE_PROVIDER": "meta",
        "AIRLOCK_VISION_PROVIDER": "sam",
        "AIRLOCK_FIXTURE_READER": "1",
        "MODEL_API_KEY": "meta-key",
        "SPARK_MODEL": SPARK_MODEL,
        "VOICE_MODEL": VOICE_MODEL,
        "SAM_MODEL": SAM_MODEL,
    })
    assert settings.reader_provider == "spark"
    assert settings.voice_provider == "meta"
    assert settings.vision_provider == "sam"
    assert settings.fixture_reader_enabled is True
    assert resolve_reader(settings).adapter_id == "meta-spark"
    assert resolve_voice(settings).adapter_id == "meta-voice"
    assert resolve_vision(settings).adapter_id == "meta-sam"
