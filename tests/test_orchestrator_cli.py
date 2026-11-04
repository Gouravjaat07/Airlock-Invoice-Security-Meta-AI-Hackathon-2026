"""Tests for the Phase 1 orchestrator CLI, aggregation, and report writers."""

import json
import tomllib
from pathlib import Path

import phase1_check as phase_mod
import pytest
from _common import TOOL_VERSION, atomic_write_json

ROOT = Path(__file__).resolve().parent.parent


def write_smoke_record(directory: Path, name: str, status: str, component: str):
    record = {"test_id": name, "component": component, "test_type": "live-smoke",
              "status": status, "model_id": "synthetic-model",
              "endpoint": "https://example.com/v1",
              "timestamp_utc": "2026-10-30T00:00:00+00:00",
              "http_status": 200 if status == "PASS" else None,
              "latency_ms": 10 if status == "PASS" else None,
              "evidence_file": None, "error_category": None,
              "notes": "synthetic test record"}
    results = directory / "results" / "phase1"
    results.mkdir(parents=True, exist_ok=True)
    (results / name).write_text(json.dumps(record), encoding="utf-8")


def canned_report(overall, tmp_path):
    return {"root": str(tmp_path),
            "sections": {"environment": {"status": overall, "summary": "canned",
                                        "details": [], "data": {}}},
            "prerequisites": [],
            "overall": overall}


# --- CLI surface (Step-J regression: documented flags must exist) ---


def test_unknown_flag_exits_2_not_crash():
    with pytest.raises(SystemExit) as exc:
        phase_mod.main(["--bogus-flag"])
    assert exc.value.code == 2


def test_partial_live_flags_exit_2(tmp_path, monkeypatch):
    def boom(script_path, component, json_path):
        raise AssertionError("live runner must not run on flag misuse")

    monkeypatch.chdir(tmp_path)
    assert phase_mod.main(["--live"], live_runner=boom) == 2
    assert phase_mod.main(["--allow-billable"], live_runner=boom) == 2
    assert phase_mod.main(["--confirm-external-call"], live_runner=boom) == 2


def test_version_flag(capsys):
    assert phase_mod.main(["--version"]) == 0
    assert TOOL_VERSION in capsys.readouterr().out


def test_help_exits_0():
    with pytest.raises(SystemExit) as exc:
        phase_mod.main(["--help"])
    assert exc.value.code == 0


def test_tool_version_matches_pyproject():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert TOOL_VERSION == pyproject["project"]["version"]


# --- Exit-code semantics ---


def test_strict_exits_nonzero_when_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(phase_mod, "run_phase1_check",
                        lambda *a, **k: canned_report("PARTIAL", tmp_path))
    assert phase_mod.main(["--strict"]) == 1
    assert phase_mod.main([]) == 0


def test_blocked_exits_nonzero_in_both_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(phase_mod, "run_phase1_check",
                        lambda *a, **k: canned_report("BLOCKED", tmp_path))
    assert phase_mod.main([]) == 1
    assert phase_mod.main(["--strict"]) == 1


def test_strict_pass_exits_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(phase_mod, "run_phase1_check",
                        lambda *a, **k: canned_report("PASS", tmp_path))
    assert phase_mod.main(["--strict"]) == 0


# --- Aggregation rules ---


def test_env_not_tested_only_is_partial_not_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(phase_mod.env_mod, "run_environment_checks",
                        lambda: [{"check_id": "x", "name": "X", "status": "NOT_TESTED",
                                  "detail": "skipped", "evidence": {}}])
    monkeypatch.setattr(phase_mod.env_mod, "summarize", lambda r: {"NOT_TESTED": 1})
    monkeypatch.setattr(phase_mod.hw_mod, "run_hardware_audit",
                        lambda: {"decision": "LOCAL_GLIMMER_UNAVAILABLE",
                                 "rationale": "synthetic"})
    report = phase_mod.run_phase1_check(tmp_path)
    assert report["sections"]["environment"]["status"] == "PARTIAL"


def test_api_fail_record_blocks(tmp_path):
    write_smoke_record(tmp_path, "smoke-meta-spark-a.json", "FAIL", "meta-spark")
    section = phase_mod.summarize_api_evidence(tmp_path)
    assert section["status"] == "FAIL"
    assert "meta-spark" in " ".join(section["details"])


def test_api_required_verified_passes(tmp_path):
    write_smoke_record(tmp_path, "smoke-a.json", "PASS", "meta-spark")
    write_smoke_record(tmp_path, "smoke-b.json", "VERIFIED_FROM_LOG", "baseten-spark-open")
    section = phase_mod.summarize_api_evidence(tmp_path)
    assert section["status"] == "PASS"


def test_api_corrupt_record_skipped_transparently(tmp_path):
    results = tmp_path / "results" / "phase1"
    results.mkdir(parents=True)
    (results / "smoke-bad.json").write_text("{corrupt", encoding="utf-8")
    section = phase_mod.summarize_api_evidence(tmp_path)
    assert section["data"]["corrupt_records"] == 1
    assert section["data"]["local_records"] == 0


def test_root_resolution_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = phase_mod.run_phase1_check()
    assert Path(report["root"]) == ROOT.resolve()
    assert report["overall"] == phase_mod.run_phase1_check(ROOT)["overall"]


def test_hygiene_root_independent_of_cwd(tmp_path, monkeypatch):
    import check_secret_hygiene as hygiene_mod

    monkeypatch.chdir(tmp_path)
    assert hygiene_mod.run_hygiene_checks()["root"] == str(ROOT.resolve())


def test_overall_matches_sections_on_real_root():
    report = phase_mod.run_phase1_check(ROOT)
    statuses = [s["status"] for s in report["sections"].values()]
    if "FAIL" in statuses:
        assert report["overall"] == "BLOCKED"
    elif "PARTIAL" in statuses:
        assert report["overall"] == "PARTIAL"
    else:
        assert report["overall"] == "PASS"


# --- Live plumbing (doubles only; never real network) ---


def live_double(results):
    def runner(script_path, component, json_path):
        assert script_path.is_file()
        return dict(results[component])
    return runner


def test_live_section_all_pass(tmp_path):
    results = {c: {"component": c, "exit_code": 0, "timed_out": False,
                   "status": "PASS", "notes": "synthetic"}
               for c in ("meta-spark", "baseten-spark-open", "sam-3.1",
                         "voice-transcribe")}
    section = phase_mod.run_live_smokes(ROOT, live_runner=live_double(results))
    assert section["status"] == "PASS"


def test_live_section_fail_blocks(tmp_path):
    results = {c: {"component": c, "exit_code": 0, "timed_out": False,
                   "status": "PASS", "notes": "synthetic"}
               for c in ("meta-spark", "baseten-spark-open", "sam-3.1",
                         "voice-transcribe")}
    results["meta-spark"] = {"component": "meta-spark", "exit_code": 1,
                             "timed_out": False, "status": "FAIL",
                             "notes": "synthetic failure"}
    section = phase_mod.run_live_smokes(ROOT, live_runner=live_double(results))
    assert section["status"] == "FAIL"


def test_live_section_partial_when_conditionally_untested():
    results = {
        "meta-spark": {"component": "meta-spark", "exit_code": 0,
                       "timed_out": False, "status": "PASS", "notes": "synthetic"},
        "baseten-spark-open": {"component": "baseten-spark-open", "exit_code": 0,
                               "timed_out": False, "status": "PASS", "notes": "synthetic"},
        "sam-3.1": {"component": "sam-3.1", "exit_code": 1, "timed_out": False,
                    "status": "NOT_TESTED", "notes": "schema-unverified"},
        "voice-transcribe": {"component": "voice-transcribe", "exit_code": 1,
                             "timed_out": False, "status": "NOT_TESTED",
                             "notes": "schema-unverified"},
    }
    section = phase_mod.run_live_smokes(ROOT, live_runner=live_double(results))
    assert section["status"] == "PARTIAL"


def test_default_mode_never_invokes_live_runner(tmp_path, monkeypatch):
    calls = []

    def boom(script_path, component, json_path):
        calls.append(component)
        raise AssertionError("live runner must not run in default mode")

    monkeypatch.chdir(tmp_path)
    phase_mod.main([], live_runner=boom)
    assert calls == []


def test_live_end_to_end_uses_double_and_warns_cost(tmp_path, monkeypatch, capsys):
    results = {c: {"component": c, "exit_code": 0, "timed_out": False,
                   "status": "PASS", "notes": "synthetic"}
               for c in ("meta-spark", "baseten-spark-open", "sam-3.1",
                         "voice-transcribe")}
    monkeypatch.chdir(tmp_path)
    code = phase_mod.main(["--live", "--allow-billable"],
                          live_runner=live_double(results))
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "Live mode" in out and "credit" in out.lower()


# --- Reports, sidecars, atomic writes ---


def test_output_dir_writes_sidecars(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    out_dir = tmp_path / "evidence"
    code = phase_mod.main(["--output-dir", str(out_dir)])
    assert code in (0, 1)
    for name in ("phase1_report.json", "environment.json", "hardware.json"):
        data = json.loads((out_dir / name).read_text(encoding="utf-8"))
        assert data["provenance"]["tool_version"] == TOOL_VERSION
    report = json.loads((out_dir / "phase1_report.json").read_text(encoding="utf-8"))
    assert report["overall"] in ("PASS", "PARTIAL", "BLOCKED")


def test_json_report_has_provenance(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    target = tmp_path / "phase1.json"
    phase_mod.main(["--json", str(target)])
    data = json.loads(target.read_text(encoding="utf-8"))
    prov = data["provenance"]
    assert prov["tool"] == "phase1_check"
    assert prov["tool_version"] == TOOL_VERSION
    assert "timestamp_utc" in prov and "git_commit" in prov


def test_atomic_write_json_roundtrip_and_failure_safety(tmp_path):
    target = tmp_path / "sub" / "report.json"
    assert atomic_write_json(target, {"a": 1}) == str(target)
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert target.read_bytes().endswith(b"\n")


def test_atomic_write_preserves_old_file_on_failure(tmp_path):
    import os as _os

    target = tmp_path / "locked.json"
    target.write_text('{"old": true}', encoding="utf-8")
    target.chmod(0o444)
    try:
        if _os.name == "nt":
            # Replacing over a read-only file must fail without truncating it.
            with pytest.raises(OSError):
                atomic_write_json(target, {"new": True})
            assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
        else:
            # POSIX replace follows directory permissions; assert round-trip.
            atomic_write_json(target, {"new": True})
            assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}
    finally:
        target.chmod(0o644)
