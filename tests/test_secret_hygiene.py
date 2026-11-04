"""Tests for scripts/check_secret_hygiene.py.

Synthetic credential-shaped values are assembled dynamically (string
concatenation) so the literal patterns never appear in this file and the
repository scan stays clean. Nothing here is a real credential.
"""

import json
import os
from pathlib import Path

import check_secret_hygiene as hygiene
import pytest
import validate_config as cfg
from _smoke_common import save_record

ROOT = Path(__file__).resolve().parent.parent


def synth_sk_token():
    return "sk-" + "SYNTHETIC-" + "TEST-VALUE-0123456789"


def synth_bearer_line():
    return "Bear" + "er " + "SYNTHETICBEARER0123456789"


def synth_assignment():
    return "api" + "_key = " + "SYNTHETIC-DUMMY-VALUE"


def synth_private_key():
    return "-----BEGIN " + "SYNTHETIC PRIVATE KEY-----"


def synth_aws_key():
    return "AKI" + "A" + "IOSFODNN7EXAMPLE"


def test_pattern_warnings_for_synthetic_values():
    assert hygiene.scan_text(synth_assignment()) != []
    assert hygiene.scan_text(synth_bearer_line()) != []
    assert hygiene.scan_text("token=" + synth_sk_token()) != []
    assert hygiene.scan_text(synth_private_key()) != []
    assert hygiene.scan_text("aws=" + synth_aws_key()) != []
    assert hygiene.scan_text("db=postgres://" + "user:" + "SYNTHETICpw9@host/db") != []


def test_code_shapes_are_not_flagged():
    assert hygiene.scan_text("def f(api_key: str): ...") == []
    assert hygiene.scan_text("session_secret = _non_empty(env)") == []
    assert hygiene.scan_text("MODEL_API_KEY=") == []
    assert hygiene.scan_text("# MODEL_API_KEY is the Meta credential") == []


def test_findings_carry_no_values(tmp_path):
    victim = tmp_path / "leak.py"
    victim.write_text("x = 1\n" + synth_assignment() + "\n", encoding="utf-8")
    report = hygiene.run_hygiene_checks(tmp_path)
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["line"] == 2
    assert "SYNTHETIC" not in json.dumps(finding)


def test_env_ignored_and_example_trackable():
    report = hygiene.run_hygiene_checks(ROOT)
    rules = {r["check"]: r for r in report["ignore_rules"]}
    assert rules["gitignore-ignores-env"]["ok"] is True
    assert rules["gitignore-keeps-example"]["ok"] is True
    if "git-ignores-env" in rules:  # git behavioral checks when in a repo
        assert rules["git-ignores-env"]["ok"] is True
        assert rules["git-keeps-example"]["ok"] is True
        assert rules["env-not-tracked"]["ok"] is True


def test_repo_tree_has_no_findings():
    report = hygiene.run_hygiene_checks(ROOT)
    assert report["findings"] == [], report["findings"]


def test_config_reports_never_contain_keys(tmp_path):
    config, _ = cfg.load_config({"MODEL_API_KEY": "SYNTHETIC-META-1",
                                 "BASETEN_API_KEY": "SYNTHETIC-BASETEN-2"})
    assert "SYNTHETIC-META-1" not in json.dumps(config.redacted_dict())
    record = {"component": "meta-spark", "notes": "ok SYNTHETIC-META-1"}
    saved = save_record(record, str(tmp_path), None, ["SYNTHETIC-META-1"])
    assert "SYNTHETIC-META-1" not in Path(saved).read_text(encoding="utf-8")


def test_scanner_stays_inside_root(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    assert hygiene.is_scannable(outside, tmp_path) is False
    inside = tmp_path / "inside.txt"
    inside.write_text("hello", encoding="utf-8")
    files, _ = hygiene.iter_candidate_files(tmp_path)
    assert all(tmp_path.resolve() in p.parents or p.parent == tmp_path.resolve() for p in files)


def test_walk_symlink_cannot_escape_root(tmp_path):
    outside = tmp_path.parent / ("outside-" + tmp_path.name + ".txt")
    outside.write_text("api" + "_key = " + "ESCAPED-SECRET-VALUE\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        os.symlink(str(outside), str(link))
    except OSError:
        pytest.skip("symlink creation not permitted on this machine")
    report = hygiene.run_hygiene_checks(tmp_path)
    assert report["findings"] == []
    skipped = {entry["file"]: entry["reason"] for entry in report["skipped"]}
    assert skipped.get("link.txt") == "outside-root-symlink"


def test_skipped_files_are_logged_not_silent(tmp_path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"\x00" * (hygiene.MAX_FILE_BYTES + 1))
    odd = tmp_path / "odd.txt"
    odd.write_bytes(b"caf\xe9 latin-1 \xff\xfe\n")
    report = hygiene.run_hygiene_checks(tmp_path)
    skipped = {entry["file"]: entry["reason"] for entry in report["skipped"]}
    assert skipped.get("big.txt") == "too-large"
    assert skipped.get("odd.txt") == "non-utf8-or-unreadable"
    assert report["skipped_count"] == 2


def test_gitignore_leading_slash_env_accepted(tmp_path):
    (tmp_path / ".gitignore").write_text("/.env\n!.env.example\n", encoding="utf-8")
    rules = {r["check"]: r for r in hygiene.check_ignore_rules(tmp_path)}
    assert rules["gitignore-ignores-env"]["ok"] is True


def test_pytest_temp_dirs_are_skipped(tmp_path):
    temp_file = tmp_path / "pytest-of-user" / "pytest-0" / "x.py"
    temp_file.parent.mkdir(parents=True)
    temp_file.write_text(synth_assignment() + "\n", encoding="utf-8")
    assert hygiene.is_scannable(temp_file, tmp_path) is False


def test_skipped_dirs_are_not_scanned(tmp_path):
    venv_file = tmp_path / ".venv" / "lib" / "x.py"
    venv_file.parent.mkdir(parents=True)
    venv_file.write_text(synth_assignment() + "\n", encoding="utf-8")
    assert hygiene.is_scannable(venv_file, tmp_path) is False


def test_main_exit_codes(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "a.py").write_text("x = 1\n", encoding="utf-8")
    (clean / ".gitignore").write_text(".env\n!.env.example\n", encoding="utf-8")
    # Exit must match the computed verdict on the real root, not just (0, 1).
    assert hygiene.main([]) == (0 if hygiene.run_hygiene_checks(ROOT)["clean"] else 1)
    report = hygiene.run_hygiene_checks(clean)
    assert report["clean"] is True
