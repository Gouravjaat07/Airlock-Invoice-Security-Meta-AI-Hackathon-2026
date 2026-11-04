"""Tests for scripts/validate_config.py."""

import json

import validate_config as cfg

DUMMY_META = "DUMMY-META-CRED-001"
DUMMY_BASETEN = "DUMMY-BASETEN-CRED-002"


def test_empty_env_uses_defaults_with_info_only():
    config, issues = cfg.load_config({})
    assert config.meta_api_base == cfg.DEFAULT_META_API_BASE
    assert config.spark_model == cfg.EXPECTED_SPARK_MODEL
    assert config.model_api_key is None
    assert config.baseten_api_key is None
    assert not [i for i in issues if i.level == "ERROR"]
    codes = {i.code for i in issues}
    assert "unset:MODEL_API_KEY" in codes
    assert "unset:BASETEN_API_KEY" in codes


def test_unset_key_is_info_not_error():
    _, issues = cfg.load_config({"META_API_BASE": "https://example.com/v1"})
    assert not [i for i in issues if i.level == "ERROR" and "MODEL_API_KEY" in i.code]


def test_malformed_url_is_error_not_unset():
    _, issues = cfg.load_config({"META_API_BASE": "not a url"})
    errors = [i for i in issues if i.level == "ERROR"]
    assert any(i.code == "invalid-url:META_API_BASE" for i in errors)


def test_invalid_baseten_and_glimmer_urls():
    _, issues = cfg.load_config({"BASETEN_BASE_URL": "ftp://x",
                                 "GLIMMER_BASE_URL": "notaurl"})
    codes = {i.code for i in issues if i.level == "ERROR"}
    assert "invalid-url:BASETEN_BASE_URL" in codes
    assert "invalid-url:GLIMMER_BASE_URL" in codes


def test_url_validation_is_syntax_only():
    assert cfg.is_valid_http_url("https://api.meta.ai/v1")
    assert cfg.is_valid_http_url("http://127.0.0.1:8081/v1")
    assert not cfg.is_valid_http_url("not a url")
    assert not cfg.is_valid_http_url("ftp://example.com")
    assert not cfg.is_valid_http_url("https://")


def test_contributor_model_is_error():
    _, issues = cfg.load_config({"SPARK_MODEL": "muse-spark-1.3-contributor"})
    errors = [i for i in issues if i.level == "ERROR"]
    assert any(i.code == "contributor-as-runtime" for i in errors)
    assert any("development" in i.message for i in errors)


def test_unexpected_runtime_model_warns():
    _, issues = cfg.load_config({"SPARK_MODEL": "some-other-model"})
    assert any(i.code == "unexpected-spark-model" and i.level == "WARNING" for i in issues)


def test_shared_credential_is_error():
    _, issues = cfg.load_config({"MODEL_API_KEY": DUMMY_META, "BASETEN_API_KEY": DUMMY_META})
    assert any(i.code == "shared-credential" and i.level == "ERROR" for i in issues)


def test_distinct_credentials_are_fine():
    config, issues = cfg.load_config({"MODEL_API_KEY": DUMMY_META,
                                      "BASETEN_API_KEY": DUMMY_BASETEN})
    assert config.model_api_key == DUMMY_META
    assert config.baseten_api_key == DUMMY_BASETEN
    assert not [i for i in issues if i.code == "shared-credential"]


def test_future_phase_vars_optional_and_reported():
    _, unset_issues = cfg.load_config({})
    assert any(i.code == "future-phase-unset:AIRLOCK_PIN_HASH" for i in unset_issues)
    _, set_issues = cfg.load_config({"AIRLOCK_PIN_HASH": "DUMMY-HASH",
                                     "AIRLOCK_SESSION_SECRET": "DUMMY-SECRET",
                                     "AIRLOCK_DB_PATH": "./x.db",
                                     "AIRLOCK_BLOB_DIR": "./blobs"})
    assert not [i for i in set_issues if i.level == "ERROR"]
    assert any(i.code == "future-phase-set:AIRLOCK_PIN_HASH" for i in set_issues)


def test_redacted_dict_never_contains_secrets():
    config, _ = cfg.load_config({"MODEL_API_KEY": DUMMY_META,
                                 "BASETEN_API_KEY": DUMMY_BASETEN,
                                 "AIRLOCK_PIN_HASH": "DUMMY-HASH",
                                 "AIRLOCK_SESSION_SECRET": "DUMMY-SECRET"})
    text = json.dumps(config.redacted_dict())
    assert DUMMY_META not in text
    assert DUMMY_BASETEN not in text
    assert "DUMMY-HASH" not in text
    assert "DUMMY-SECRET" not in text
    assert config.redacted_dict()["model_api_key"] == "set"


def test_presence_report_is_boolean():
    presence = cfg.validate_environment({"MODEL_API_KEY": DUMMY_META})
    assert presence["MODEL_API_KEY"] is True
    assert presence["BASETEN_API_KEY"] is False
    assert set(presence) == set(cfg.KNOWN_VARS)


def test_main_exit_codes(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("SPARK_MODEL", raising=False)
    monkeypatch.delenv("META_API_BASE", raising=False)
    monkeypatch.delenv("BASETEN_BASE_URL", raising=False)
    monkeypatch.delenv("GLIMMER_BASE_URL", raising=False)
    out = tmp_path / "cfg.json"
    assert cfg.main(["--json", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["valid"] is True
    assert DUMMY_META not in json.dumps(data)

    monkeypatch.setenv("SPARK_MODEL", "muse-spark-1.3-contributor")
    assert cfg.main([]) == 1
    captured = capsys.readouterr()
    assert "contributor-as-runtime" in captured.out


def test_env_file_mode(tmp_path):
    env_file = tmp_path / "test.env"
    env_file.write_text("SPARK_MODEL=some-other-model\nMETA_API_BASE=notaurl\n",
                        encoding="utf-8")
    assert cfg.main(["--env-file", str(env_file)]) == 1
    assert cfg.main(["--env-file", str(tmp_path / "missing.env")]) == 1


def test_whitespace_only_key_counts_as_unset():
    config, _ = cfg.load_config({"MODEL_API_KEY": "   "})
    assert config.model_api_key is None


def test_non_utf8_env_file_fails_gracefully(tmp_path):
    env_file = tmp_path / "latin1.env"
    env_file.write_bytes(b"SPARK_MODEL=caf\xe9-model\n")
    assert cfg.main(["--env-file", str(env_file)]) == 1


def test_secret_vars_wired_into_redaction():
    config, _ = cfg.load_config({"MODEL_API_KEY": "SYNTHETIC-1",
                                 "BASETEN_API_KEY": "SYNTHETIC-2",
                                 "AIRLOCK_PIN_HASH": "SYNTHETIC-3",
                                 "AIRLOCK_SESSION_SECRET": "SYNTHETIC-4"})
    redacted = config.redacted_dict()
    for var in cfg.SECRET_VARS:
        assert redacted[var.lower()] in ("set", "unset")
    text = json.dumps(redacted)
    assert "SYNTHETIC-1" not in text and "SYNTHETIC-4" not in text
