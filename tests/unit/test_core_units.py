"""Unit tests: core utilities, fact shapes, logging, config parsing."""

from __future__ import annotations


import pytest


def test_ids_format():
    from app.core.ids import new_id, new_token
    first = new_id("case")
    assert first.startswith("case_") and new_id("case") != first
    assert len(new_token()) >= 40 and new_token() != new_token()


def test_canonical_json_deterministic():
    from app.core.canonical_json import canonical_json, canonical_sha256
    assert canonical_json({"b": 1, "a": [2, 1]}) == '{"a":[2,1],"b":1}'
    assert canonical_sha256({"a": 1}) == canonical_sha256({"a": 1})
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_clock_iso():
    from app.core.clock import SYSTEM_CLOCK, utc_now_iso
    assert SYSTEM_CLOCK.now().tzinfo is not None
    assert utc_now_iso().endswith("+00:00")


def test_error_defaults():
    from app.core.errors import STATUS_BY_CODE, AppError, ErrorCode
    err = AppError(ErrorCode.AUTH, "nope")
    assert err.status == 401 and err.details == []
    assert AppError("E_NOPE", "x").status == 500
    assert len(STATUS_BY_CODE) == 17


def test_fact_shapes_roundtrip():
    from app.domain.enums import FieldStatus
    from app.domain.facts import Fact, Producer, Source
    from app.domain.provenance import Producer as Producer2, Source as Source2
    from app.domain.taint import TaintClass, is_authoritative
    assert (Source2, Producer2) == (Source, Producer)
    source = Source.from_dict(Source("a", "invoice", page=2).to_dict())
    assert source.page == 2 and source.region is None
    made = Producer.from_dict(
        Producer("r", "1", model_id=None).to_dict())
    assert made.adapter == "r" and made.model_id is None
    fact = Fact(id="f", case_id="c", field="total", value="1",
                source=source, producer=made, taint=TaintClass.T2_MODEL,
                validation_status=FieldStatus.UNCONFIRMED)
    assert fact.validated_by == [] and fact.created_at is None
    assert is_authoritative(TaintClass.T0_OWNER)
    assert is_authoritative(TaintClass.T1_TRUSTED)
    assert not is_authoritative(TaintClass.T2_MODEL)
    assert not is_authoritative(TaintClass.T3_RAW)


def test_purchase_order_defaults():
    from decimal import Decimal
    from app.domain.purchase_orders import PurchaseOrder
    po = PurchaseOrder("p", "v", "PO-1", "USD", Decimal("5"),
                       Decimal("5"))
    assert po.status == "open" and po.version == 1


def test_logging_redaction(capsys):
    import logging
    from app.core.logging import configure_logging, get_logger, log
    configure_logging("DEBUG")
    logger = get_logger()
    log(logger, logging.INFO, "hello", pin="S3CR3T-PIN-VALUE",
        other={"bank_account": "S3CR3T-BANK-VALUE"})
    out = capsys.readouterr().out
    assert "S3CR3T-PIN-VALUE" not in out
    assert "S3CR3T-BANK-VALUE" not in out
    assert '"pin": "***"' in out
    assert '"bank_account": "***"' in out


def test_config_env_parsing(monkeypatch, tmp_path):
    from app.config import _get_bool, _get_float, _get_int, load_settings
    from app.core.errors import AppError
    assert _get_int({}, "X", 3) == 3
    assert _get_int({"X": "7"}, "X", 3) == 7
    with pytest.raises(AppError):
        _get_int({"X": "nope"}, "X", 3)
    assert _get_float({"X": "1.5"}, "X", 0.0) == 1.5
    with pytest.raises(AppError):
        _get_float({"X": "nope"}, "X", 0.0)
    assert _get_bool({"X": "yes"}, "X", False) is True
    assert _get_bool({}, "X", True) is True
    settings = load_settings({})
    assert settings.redacted_dict()["pin_hash"] == "unset"


def test_config_policy_file_errors(tmp_path):
    from app.config import (
        Settings,
        _validate_safety,
        apply_policy,
        load_policy_file,
        load_settings,
    )
    from app.core.errors import AppError
    with pytest.raises(AppError):
        load_policy_file(tmp_path / "missing.toml")
    bad = tmp_path / "bad.toml"
    bad.write_text("not = [toml", encoding="utf-8")
    with pytest.raises(AppError):
        load_policy_file(bad)
    settings = Settings()
    apply_policy(settings, {"meta": {"version": "9.9.9"},
                            "rules": {"per_invoice_cap_default": "5",
                                      "currency_precision": 3,
                                      "due_date_max_days": 10,
                                      "sam_count_min": 1, "sam_count_max": 9,
                                      "catalogue_tolerance_default": 2,
                                      "bank_change_cooldown_hours": 1}})
    assert settings.policy_version == "9.9.9"
    assert settings.currency_precision == 3
    with pytest.raises(AppError):
        load_settings({"AIRLOCK_LOGIN_MAX_ATTEMPTS": "0"})
    with pytest.raises(AppError):
        load_settings({"AIRLOCK_SESSION_MINUTES": "0"})
    broken = Settings()
    apply_policy(broken, {"rules": {"due_date_max_days": 0}})
    with pytest.raises(AppError):
        _validate_safety(broken)


def test_config_policy_value_validation(tmp_path):
    """Regression (F6): malformed policy values fail closed at load."""
    from app.config import Settings, _validate_safety, apply_policy
    from app.core.errors import AppError
    for rules in ({"per_invoice_cap_default": "not-a-number"},
                  {"per_invoice_cap_default": "0"},
                  {"per_invoice_cap_default": "-5"},
                  {"currency_precision": "many"},
                  {"due_date_max_days": True},
                  {"sam_count_min": [1]}):
        with pytest.raises(AppError):
            apply_policy(Settings(), {"rules": rules})
    with pytest.raises(AppError):
        _validate_safety(Settings(per_invoice_cap_default="bogus"))
    with pytest.raises(AppError):
        _validate_safety(Settings(per_invoice_cap_default="0"))
    ok = Settings()
    apply_policy(ok, {"rules": {"per_invoice_cap_default": "250.5"}})
    assert ok.per_invoice_cap_default == "250.5"
    _validate_safety(ok)


def test_config_safety_matrix():
    from app.config import Settings, _validate_safety
    from app.core.errors import AppError
    _validate_safety(Settings())
    for kwargs in ({"environment": "production",
                    "allow_insecure_cookies": True},
                   {"environment": "production", "enable_eval_api": True},
                   {"max_upload_bytes": 0},
                   {"login_max_attempts": -1},
                   {"challenge_duration_minutes": 0},
                   {"currency_precision": -1},
                   {"sam_count_min": 5, "sam_count_max": 2},
                   # Phase 3: no mock/fixture providers in production.
                   {"environment": "production"},
                   {"reader_provider": "watson"},
                   {"voice_provider": "watson"},
                   {"vision_provider": "watson"},
                   {"meta_api_base": "http://api.meta.ai/v1"},
                   {"meta_api_base": "ftp://x/y"},
                   {"meta_api_base": "https://" + "user:" +
                    "pw@api.meta.ai/v1"},
                   {"glimmer_base_url": "http://192.168.1.9:8081/v1"},
                   {"spark_model": "muse-spark-1.3-contributor"},
                   {"spark_model": "has space"},
                   {"spark_model": ""},
                   {"provider_connect_timeout_s": 0},
                   {"extraction_timeout_s": 4},
                   {"voice_timeout_s": 9999},
                   {"provider_max_inflight": 0},
                   {"provider_max_retries": 6},
                   {"spark_max_output_tokens": 8}):
        with pytest.raises(AppError):
            _validate_safety(Settings(**kwargs))
    # Phase 3: valid explicit provider selections pass outside production.
    _validate_safety(Settings(reader_provider="spark",
                              voice_provider="meta",
                              vision_provider="sam"))
    _validate_safety(Settings(glimmer_base_url="https://gpu.lan:8081/v1"))


def test_provider_settings_from_env(tmp_path):
    from app.config import load_settings
    env = {"AIRLOCK_DB_PATH": str(tmp_path / "t.db"),
           "AIRLOCK_READER_PROVIDER": "SPARK",
           "AIRLOCK_VOICE_PROVIDER": "meta",
           "AIRLOCK_VISION_PROVIDER": "sam",
           "MODEL_API_KEY": "  LLM_test-key ",
           "VOICE_MODEL": "custom-voice-2.0",
           "AIRLOCK_PROVIDER_MAX_RETRIES": "1"}
    settings = load_settings(env, policy_path="policy/rules.toml")
    assert settings.reader_provider == "spark"
    assert settings.voice_model == "custom-voice-2.0"
    assert settings.provider_max_retries == 1
    redacted = settings.redacted_dict()
    assert redacted["model_api_key"] == "set"
    assert "LLM_test-key" not in repr(redacted)
    assert redacted["baseten_api_key"] == "unset"


def test_override_settings_roundtrip(settings):
    from app.config import get_settings, override_settings
    override_settings(settings)
    try:
        assert get_settings() is settings
    finally:
        override_settings(None)


def test_pagination_schema():
    from app.schemas.common import PagedQuery
    assert PagedQuery().limit == 50
    with pytest.raises(Exception):
        PagedQuery(limit=0)
    with pytest.raises(Exception):
        PagedQuery(limit=1, bogus=2)
