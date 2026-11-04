"""Tests for report correctness and the smoke-result recorder."""

import json
from pathlib import Path

import phase1_check as phase_mod
import record_smoke_result as recorder

ROOT = Path(__file__).resolve().parent.parent


def write_record(directory: Path, name: str, status: str, component="meta-spark",
                 evidence_file=None, http_status=None, latency_ms=None):
    record = {"test_id": name, "component": component, "test_type": "live-smoke",
              "status": status, "model_id": "muse-spark-1.3",
              "endpoint": "https://example.com/v1",
              "timestamp_utc": "2026-10-30T00:00:00+00:00",
              "http_status": http_status, "latency_ms": latency_ms,
              "evidence_file": evidence_file, "error_category": None,
              "notes": "synthetic test record"}
    (directory / name).write_text(json.dumps(record), encoding="utf-8")


def test_user_reported_is_not_pass(tmp_path):
    results = tmp_path / "results" / "phase1"
    results.mkdir(parents=True)
    write_record(results, "smoke-meta-spark-a.json", "USER_REPORTED_TESTED")
    section = phase_mod.summarize_api_evidence(tmp_path)
    assert section["status"] == "PARTIAL"
    assert section["data"]["locally_verified"] == 0


def test_not_tested_remains_unverified(tmp_path):
    results = tmp_path / "results" / "phase1"
    results.mkdir(parents=True)
    write_record(results, "smoke-x.json", "NOT_TESTED")
    section = phase_mod.summarize_api_evidence(tmp_path)
    assert section["data"]["locally_verified"] == 0
    assert "NOT run" in " ".join(section["details"])


def test_failed_integration_blocks_not_partials(tmp_path):
    # A FAIL smoke record is a verified failure signal: the section must FAIL
    # so the release gate blocks until the integration is re-verified.
    results = tmp_path / "results" / "phase1"
    results.mkdir(parents=True)
    write_record(results, "smoke-sam.json", "FAIL", component="sam-3.1")
    section = phase_mod.summarize_api_evidence(tmp_path)
    assert section["data"]["local_records"] == 1
    assert section["data"]["locally_verified"] == 0
    assert section["status"] == "FAIL"


def test_verified_log_counts_as_evidence(tmp_path):
    results = tmp_path / "results" / "phase1"
    results.mkdir(parents=True)
    log = results / "resp.log"
    log.write_text("HTTP 200 synthetic", encoding="utf-8")
    write_record(results, "smoke-meta.json", "VERIFIED_FROM_LOG",
                 evidence_file=str(log), http_status=200, latency_ms=100)
    section = phase_mod.summarize_api_evidence(tmp_path)
    assert section["data"]["locally_verified"] == 1


def test_passing_env_does_not_imply_model_pass(tmp_path, monkeypatch):
    # Force environment to all-PASS; API evidence must still be PARTIAL.
    fake_results = [{"check_id": "x", "name": "X", "status": "PASS", "detail": "ok",
                     "evidence": {}}]
    monkeypatch.setattr(phase_mod.env_mod, "run_environment_checks", lambda: fake_results)
    monkeypatch.setattr(phase_mod.env_mod, "summarize", lambda r: {"PASS": 1})
    monkeypatch.setattr(phase_mod.hw_mod, "run_hardware_audit",
                        lambda: {"decision": "LOCAL_GLIMMER_UNAVAILABLE",
                                 "rationale": "synthetic"})
    report = phase_mod.run_phase1_check(tmp_path)
    assert report["sections"]["environment"]["status"] == "PASS"
    assert report["sections"]["api_evidence"]["status"] == "PARTIAL"


def test_phase_incomplete_when_docs_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(phase_mod.env_mod, "run_environment_checks", lambda: [])
    monkeypatch.setattr(phase_mod.env_mod, "summarize", lambda r: {})
    monkeypatch.setattr(phase_mod.hw_mod, "run_hardware_audit",
                        lambda: {"decision": "LOCAL_GLIMMER_UNAVAILABLE",
                                 "rationale": "synthetic"})
    report = phase_mod.run_phase1_check(tmp_path)
    assert report["sections"]["documentation"]["status"] == "FAIL"
    assert report["overall"] == "BLOCKED"
    assert phase_mod.main([]) == (1 if phase_mod.run_phase1_check()["overall"] == "BLOCKED" else 0)


def test_full_check_runs_against_real_root():
    report = phase_mod.run_phase1_check(ROOT)
    assert set(report["sections"]) == {"environment", "local_inference",
                                       "api_evidence", "research", "security",
                                       "documentation"}
    assert report["overall"] in ("PASS", "PARTIAL", "BLOCKED")
    assert report["prerequisites"]


# --- Recorder validation ---


def test_recorder_rejects_pass_without_evidence():
    record = recorder.build_record("t1", "meta-spark", "live-smoke", "PASS",
                                   "m", "https://e", None, None, None, None, "n")
    errors = recorder.validate_record(record)
    assert any("evidence" in e for e in errors)


def test_recorder_accepts_pass_with_evidence(tmp_path):
    record = recorder.build_record("t1", "meta-spark", "live-smoke", "PASS",
                                   "m", "https://e", 200, 50, None, None, "synthetic ok")
    assert recorder.validate_record(record) == []
    assert recorder.main(["--component", "meta-spark", "--test-type", "live-smoke",
                          "--status", "PASS", "--model-id", "m",
                          "--endpoint", "https://e", "--http-status", "200",
                          "--latency-ms", "50", "--notes", "synthetic ok",
                          "--out-dir", str(tmp_path), "--test-id", "t1"]) == 0
    assert (tmp_path / "smoke-meta-spark-t1.json").is_file()


def test_recorder_rejects_bad_status_and_type():
    record = recorder.build_record("t1", "c", "live-smoke", "GREEN",
                                   None, None, None, None, None, None, "n")
    assert any("status" in e for e in record and recorder.validate_record(record))
    record["status"] = "FAIL"
    record["test_type"] = "vibes"
    assert any("test_type" in e for e in recorder.validate_record(record))


def test_recorder_rejects_credentials_in_fields():
    bad = "token " + "sk-" + "SYNTHETIC0123456789"
    record = recorder.build_record("t1", "c", "live-smoke", "FAIL",
                                   None, None, None, None, None, None, bad)
    assert any("credential" in e for e in recorder.validate_record(record))


def test_recorder_requires_evidence_file_for_verified_log():
    record = recorder.build_record("t1", "c", "live-smoke", "VERIFIED_FROM_LOG",
                                   None, None, None, None, None, None, "n")
    assert any("evidence-file" in e for e in recorder.validate_record(record))


def test_recorder_validates_ranges():
    record = recorder.build_record("t1", "c", "live-smoke", "FAIL",
                                   None, None, 99, None, None, None, "n")
    assert any("http_status" in e for e in recorder.validate_record(record))
    record["http_status"] = 600
    assert any("http_status" in e for e in recorder.validate_record(record))
    record["http_status"] = 200
    record["latency_ms"] = -1
    assert any("latency_ms" in e for e in recorder.validate_record(record))
    record["latency_ms"] = 0
    assert recorder.validate_record(record) == []
    record["http_status"] = "two-hundred"
    assert any("http_status" in e for e in recorder.validate_record(record))


def test_recorder_refuses_overwrite_by_default(tmp_path):
    args = ["--component", "c", "--test-type", "preflight", "--status", "NOT_TESTED",
            "--out-dir", str(tmp_path), "--test-id", "dup"]
    assert recorder.main(args) == 0
    assert recorder.main(args) == 1
    assert recorder.main(args + ["--overwrite"]) == 0
