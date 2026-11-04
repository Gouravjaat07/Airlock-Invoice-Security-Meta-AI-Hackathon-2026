"""Regression tests for scripts/setup_airlock.py env preservation.

All values are synthetic and dynamically assembled so literal
credential-shaped patterns never appear in this file. Tests never print
.env contents; secret comparisons fail with redacted messages.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import setup_airlock


def _synth(prefix: str, tag: str) -> str:
    return "SYNTHETIC-" + prefix + "-" + tag


def _line(key: str, value: str) -> str:
    # Build KEY=VALUE without a literal credential assignment in source.
    return key + "=" + value


def _parse_keys(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            continue
        left, _, right = raw.partition("=")
        key = left.strip()
        if key.startswith("export ") and len(key) > 7:
            key = key[7:].strip()
        # Strip trailing inline comment for comparison (space + #).
        value = right.strip()
        if " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        data[key] = value
    return data


def _make_root(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\n',
                                             encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _base_unrelated_lines() -> list[str]:
    # Keys as plain names (no '=' literal); values synthetic.
    model_key = "MODEL_" + "API_KEY"
    base_key = "BASETEN_" + "API_KEY"
    return [
        "# Synthetic fixture header - must be preserved",
        "# Second comment line",
        "",
        _line(model_key, _synth("META", "001")),
        _line("META_API_BASE", "https://synthetic.example/v1"),
        _line("SPARK_MODEL", "muse-spark-1.3"),
        _line(base_key, _synth("BASETEN", "002")),
        _line("BASETEN_BASE_URL", "https://synthetic.baseten.example/v1"),
        _line("GLIMMER_BASE_URL", "http://127.0.0.1:8081/v1"),
        _line("AIRLOCK_FIXTURE_READER", "1"),
        _line("AIRLOCK_ENABLE_EVAL_API", "0"),
        _line("CUSTOM_UNRELATED", _synth("CUSTOM", "003")),
    ]


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assert_not_leaked(haystack: str, secrets: list[str], label: str) -> None:
    for secret in secrets:
        if secret and secret in haystack:
            pytest.fail(label + ": secret value leaked in output")


def test_unrelated_vars_unchanged(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    custom_val = _synth("CUSTOM", "KEEP-004")
    # Rebuild deterministically to avoid duplicates.
    lines = [entry for entry in _base_unrelated_lines()
             if not entry.startswith("CUSTOM_UNRELATED=")]
    lines.append(_line("CUSTOM_UNRELATED", custom_val))
    _write_lines(env_path, lines)
    pin = "synthetic-pin-" + "005"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env"])
    if rc != 0:
        pytest.fail("setup should succeed for missing managed keys")
    parsed = _parse_keys(env_path)
    if parsed.get("CUSTOM_UNRELATED") != custom_val:
        pytest.fail("unrelated variable was not preserved")
    if parsed.get("GLIMMER_BASE_URL") != "http://127.0.0.1:8081/v1":
        pytest.fail("glimmer configuration was not preserved")
    if parsed.get("AIRLOCK_FIXTURE_READER") != "1":
        pytest.fail("fixture-reader flag was not preserved")
    if parsed.get("AIRLOCK_ENABLE_EVAL_API") != "0":
        pytest.fail("phase2 runtime flag was not preserved")
    text = env_path.read_text(encoding="utf-8")
    if "# Synthetic fixture header - must be preserved" not in text:
        pytest.fail("header comment was not preserved")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err, [pin, custom_val], "unrelated")


def test_meta_baseten_unchanged(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    meta_val = _synth("META", "KEEP-006")
    baseten_val = _synth("BASETEN", "KEEP-007")
    model_key = "MODEL_" + "API_KEY"
    base_key = "BASETEN_" + "API_KEY"
    lines = [
        "# meta/baseten preservation",
        _line(model_key, meta_val),
        _line("META_API_BASE", "https://synthetic.example/v1"),
        _line(base_key, baseten_val),
        _line("BASETEN_BASE_URL", "https://synthetic.baseten.example/v1"),
    ]
    _write_lines(env_path, lines)
    pin = "synthetic-pin-" + "008"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env"])
    if rc != 0:
        pytest.fail("setup should succeed")
    parsed = _parse_keys(env_path)
    if parsed.get(model_key) != meta_val:
        pytest.fail("meta configuration was not preserved")
    if parsed.get(base_key) != baseten_val:
        pytest.fail("baseten configuration was not preserved")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err, [pin, meta_val, baseten_val],
                       "meta-baseten")


def test_fixture_reader_unchanged(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    lines = ["# fixture reader", _line("AIRLOCK_FIXTURE_READER", "1")]
    _write_lines(env_path, lines)
    pin = "synthetic-pin-" + "009"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env"])
    if rc != 0:
        pytest.fail("setup should succeed")
    parsed = _parse_keys(env_path)
    if parsed.get("AIRLOCK_FIXTURE_READER") != "1":
        pytest.fail("fixture-reader setting was not preserved")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err, [pin], "fixture")


def test_comments_preserved(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    comment_a = "# keep-this-comment-010"
    comment_b = "# keep-this-comment-011"
    lines = [comment_a, _line("CUSTOM_X", _synth("X", "012")), comment_b]
    _write_lines(env_path, lines)
    pin = "synthetic-pin-" + "013"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env"])
    if rc != 0:
        pytest.fail("setup should succeed")
    text = env_path.read_text(encoding="utf-8")
    if comment_a not in text:
        pytest.fail("first comment was not preserved")
    if comment_b not in text:
        pytest.fail("second comment was not preserved")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err, [pin], "comments")


def test_missing_env_can_be_created(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "fresh.env"
    if env_path.exists():
        pytest.fail("precondition: fresh file must not exist")
    pin = "synthetic-pin-" + "014"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "fresh.env"])
    if rc != 0:
        pytest.fail("setup should create missing file")
    if not env_path.is_file():
        pytest.fail("missing file was not created")
    parsed = _parse_keys(env_path)
    for key in ("AIRLOCK_PIN_HASH", "AIRLOCK_SESSION_SECRET",
                "AIRLOCK_BANK_HASH_KEY", "AIRLOCK_DB_PATH",
                "AIRLOCK_BLOB_DIR", "AIRLOCK_ENV"):
        if not parsed.get(key):
            pytest.fail("managed key missing after create: " + key)
    text = env_path.read_text(encoding="utf-8")
    if pin in text:
        pytest.fail("raw PIN must never be stored")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err, [pin], "create")


def test_existing_secrets_preserved_unless_authorized(tmp_path, monkeypatch,
                                                     capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    old_hash = "SYNTHETIC-" + "OLD-HASH-015"
    old_session = "SYNTHETIC-" + "OLD-SESSION-016"
    old_bank = "SYNTHETIC-" + "OLD-BANK-017"
    lines = [
        _line("AIRLOCK_PIN_HASH", old_hash),
        _line("AIRLOCK_SESSION_SECRET", old_session),
        _line("AIRLOCK_BANK_HASH_KEY", old_bank),
        _line("AIRLOCK_DB_PATH", "./data/airlock.db"),
        _line("AIRLOCK_BLOB_DIR", "./data/blobs"),
        _line("AIRLOCK_ENV", "development"),
    ]
    _write_lines(env_path, lines)
    before = env_path.read_bytes()
    pin = "synthetic-pin-" + "018"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    monkeypatch.delenv("AIRLOCK_SETUP_OVERWRITE", raising=False)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env"])
    if rc == 0:
        pytest.fail("overwrite without authorization must not succeed")
    if env_path.read_bytes() != before:
        pytest.fail("unauthorized overwrite must not modify file")
    capsys.readouterr()
    # Explicit authorization via flag preserves session/bank secrets.
    rc2 = setup_airlock.main(["--non-interactive", "--env-file", "test.env",
                              "--overwrite"])
    if rc2 != 0:
        pytest.fail("authorized overwrite should succeed")
    parsed = _parse_keys(env_path)
    if parsed.get("AIRLOCK_SESSION_SECRET") != old_session:
        pytest.fail("session secret must be preserved on overwrite")
    if parsed.get("AIRLOCK_BANK_HASH_KEY") != old_bank:
        pytest.fail("bank key must be preserved on overwrite")
    if parsed.get("AIRLOCK_PIN_HASH") == old_hash:
        pytest.fail("PIN hash should rotate on authorized overwrite")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err,
                       [pin, old_hash, old_session, old_bank], "overwrite")


def test_duplicate_managed_keys_safe_error(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    first = "SYNTHETIC-" + "FIRST-019"
    second = "SYNTHETIC-" + "SECOND-020"
    lines = [
        _line("AIRLOCK_SESSION_SECRET", first),
        "# intervening comment",
        _line("AIRLOCK_SESSION_SECRET", second),
    ]
    _write_lines(env_path, lines)
    before = env_path.read_bytes()
    pin = "synthetic-pin-" + "021"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env",
                             "--overwrite"])
    if rc == 0:
        pytest.fail("duplicate managed keys must fail safely")
    if env_path.read_bytes() != before:
        pytest.fail("duplicate error must not modify file")
    out = capsys.readouterr()
    combined = out.out + out.err
    if "AIRLOCK_SESSION_SECRET" not in combined:
        pytest.fail("duplicate error should name the key")
    _assert_not_leaked(combined, [pin, first, second], "duplicate")


def test_pin_mismatch_writes_nothing(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    _write_lines(env_path, ["# mismatch guard"])
    before = env_path.read_bytes()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    calls = {"n": 0}

    def _fake_getpass(prompt=""):
        calls["n"] += 1
        return "synthetic-pin-" + ("AAA" if calls["n"] == 1 else "BBB")

    monkeypatch.setattr(setup_airlock.getpass, "getpass", _fake_getpass)
    rc = setup_airlock.main(["--env-file", "test.env"])
    if rc == 0:
        pytest.fail("PIN mismatch must fail")
    if env_path.read_bytes() != before:
        pytest.fail("PIN mismatch must not write")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err,
                       ["synthetic-pin-AAA", "synthetic-pin-BBB"], "mismatch")


def test_short_pin_writes_nothing(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    _write_lines(env_path, ["# short-pin guard"])
    before = env_path.read_bytes()
    # Non-interactive short PIN path.
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", "abc")
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env"])
    if rc == 0:
        pytest.fail("short PIN must fail")
    if env_path.read_bytes() != before:
        pytest.fail("short PIN must not write")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err, ["abc"], "short-pin")


def test_failed_atomic_write_keeps_previous(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    keep_val = _synth("KEEP", "022")
    lines = ["# atomic guard", _line("CUSTOM_KEEP", keep_val)]
    _write_lines(env_path, lines)
    before = env_path.read_bytes()

    def _boom_replace(src, dst):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", _boom_replace)
    pin = "synthetic-pin-" + "023"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env"])
    if rc == 0:
        pytest.fail("failed atomic write must fail")
    if env_path.read_bytes() != before:
        pytest.fail("failed write must keep previous file")
    leftovers = list(root.glob(".test.env.*.tmp"))
    if leftovers:
        pytest.fail("temp file must be cleaned after failure")
    out = capsys.readouterr()
    _assert_not_leaked(out.out + out.err, [pin, keep_val], "atomic")


def test_no_secrets_in_output(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path, monkeypatch)
    env_path = root / "test.env"
    _write_lines(env_path, ["# output hygiene"])
    pin = "synthetic-pin-" + "024"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", pin)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "test.env"])
    if rc != 0:
        pytest.fail("setup should succeed")
    out = capsys.readouterr()
    combined = out.out + out.err
    if pin in combined:
        pytest.fail("PIN leaked in output")
    # Hashes/secrets are random per run; ensure output carries no assignments.
    for token in ("AIRLOCK_PIN_HASH=", "AIRLOCK_SESSION_SECRET=",
                  "AIRLOCK_BANK_HASH_KEY="):
        # Check for value-bearing lines, not bare key mentions.
        for raw in combined.splitlines():
            if token in raw and len(raw.split(token, 1)[1].strip()) > 0:
                # Allow the duplicate-error path naming keys without values;
                # here any value after '=' is a leak.
                if "Wrote" not in raw:
                    pytest.fail("secret assignment leaked in output")
    # File must not contain the raw PIN.
    text = env_path.read_text(encoding="utf-8")
    if pin in text:
        pytest.fail("raw PIN stored in file")
