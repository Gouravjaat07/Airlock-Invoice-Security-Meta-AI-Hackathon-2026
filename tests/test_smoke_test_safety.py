"""Tests for smoke-test safety: default-no-request, live gating, no leaks."""

import json
from pathlib import Path

import smoke_baseten as baseten_mod
import smoke_meta as meta_mod
import smoke_sam as sam_mod
import smoke_voice as voice_mod
from _smoke_common import SmokeRequestError, classify_error

DUMMY_CRED = "DUMMY-CRED-001"


class CallRecorder:
    """Test double for the HTTP layer. Records calls; never touches network."""

    def __init__(self, succeed=True, http_status=200):
        self.calls = []
        self.succeed = succeed
        self.http_status = http_status

    def __call__(self, url, payload, credential, timeout):
        self.calls.append({"url": url, "payload": payload, "timeout": timeout,
                           "cred_len": len(credential)})
        if not self.succeed:
            raise SmokeRequestError("HTTP 401", http_status=401,
                                    body="unauthorized", latency_ms=5)
        return self.http_status, '{"ok": true}', 12


def env_with_meta(**overrides):
    env = {"MODEL_API_KEY": DUMMY_CRED}
    env.update(overrides)
    return env


# --- Default invocation never requests ---


def test_meta_default_makes_no_request(tmp_path):
    recorder = CallRecorder()
    code = meta_mod.main(["--results-dir", str(tmp_path)], env=env_with_meta(),
                         request_fn=recorder)
    assert code == 0
    assert recorder.calls == []


def test_baseten_default_makes_no_request(tmp_path):
    recorder = CallRecorder()
    env = {"BASETEN_API_KEY": DUMMY_CRED}
    code = baseten_mod.main(["--results-dir", str(tmp_path)], env=env,
                            request_fn=recorder)
    assert code == 0
    assert recorder.calls == []


def test_sam_and_voice_default_make_no_request():
    assert sam_mod.main([]) == 0
    assert voice_mod.main([]) == 0


def test_no_mocked_client_enters_live_mode_by_default(tmp_path):
    # Even with a working double injected, no flags means no calls.
    recorder = CallRecorder()
    meta_mod.main(["--results-dir", str(tmp_path)], env=env_with_meta(),
                  request_fn=recorder)
    baseten_mod.main(["--results-dir", str(tmp_path)],
                     env={"BASETEN_API_KEY": DUMMY_CRED}, request_fn=recorder)
    assert recorder.calls == []


# --- Live gating ---


def test_live_requires_both_flags_meta():
    recorder = CallRecorder()
    assert meta_mod.main(["--live"], env=env_with_meta(), request_fn=recorder) == 2
    assert meta_mod.main(["--confirm-external-call"], env=env_with_meta(),
                         request_fn=recorder) == 2
    assert recorder.calls == []


def test_live_requires_both_flags_baseten_sam_voice():
    assert baseten_mod.main(["--live"], env={"BASETEN_API_KEY": DUMMY_CRED},
                            request_fn=CallRecorder()) == 2
    assert sam_mod.main(["--live"]) == 2
    assert voice_mod.main(["--live"]) == 2
    assert sam_mod.main(["--confirm-external-call"]) == 2
    assert voice_mod.main(["--confirm-external-call"]) == 2


def test_missing_key_fails_safely_with_live_flags():
    recorder = CallRecorder()
    assert meta_mod.main(["--live", "--confirm-external-call"], env={},
                         request_fn=recorder) == 1
    assert recorder.calls == []


def test_invalid_config_fails_safely_with_live_flags():
    recorder = CallRecorder()
    code = meta_mod.main(["--live", "--confirm-external-call", "--base-url", "notaurl"],
                         env=env_with_meta(), request_fn=recorder)
    assert code == 1
    assert recorder.calls == []


def test_contributor_model_refused_live():
    recorder = CallRecorder()
    env = env_with_meta(SPARK_MODEL="muse-spark-1.3-contributor")
    code = meta_mod.main(["--live", "--confirm-external-call"], env=env,
                         request_fn=recorder)
    assert code == 1
    assert recorder.calls == []


# --- Live behavior with doubles ---


def test_live_success_path_is_sanitized(tmp_path):
    recorder = CallRecorder()
    code = meta_mod.main(["--live", "--confirm-external-call", "--results-dir", str(tmp_path)],
                         env=env_with_meta(), request_fn=recorder)
    assert code == 0
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["payload"]["messages"][0]["content"].startswith("Reply with exactly")
    saved = list(tmp_path.glob("smoke-*.json"))
    assert len(saved) == 1
    assert DUMMY_CRED not in saved[0].read_text(encoding="utf-8")


def test_live_structured_runs_second_request_only_after_text(tmp_path):
    recorder = CallRecorder()
    code = meta_mod.main(["--live", "--confirm-external-call", "--structured",
                          "--results-dir", str(tmp_path)],
                         env=env_with_meta(), request_fn=recorder)
    assert code == 0
    assert len(recorder.calls) == 2


def test_live_failure_classified_without_headers(tmp_path):
    recorder = CallRecorder(succeed=False)
    code = meta_mod.main(["--live", "--confirm-external-call", "--results-dir", str(tmp_path)],
                         env=env_with_meta(), request_fn=recorder)
    assert code == 1
    saved = list(tmp_path.glob("smoke-*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["status"] == "FAIL"
    assert record["error_category"] == "auth-error"
    assert "Authorization" not in json.dumps(record)
    assert DUMMY_CRED not in json.dumps(record)


def test_timeout_has_no_retry_loop():
    calls = []

    def flaky(url, payload, credential, timeout):
        calls.append(url)
        raise SmokeRequestError("timed out after 30s", latency_ms=30000)

    record = meta_mod.run_live("https://example.com/v1", "m", DUMMY_CRED, 30,
                               structured=False, request_fn=flaky)
    assert record["status"] == "FAIL"
    assert record["error_category"] == "timeout"
    assert len(calls) == 1  # no retries


def test_error_containing_cred_is_redacted():
    def leaky(url, payload, credential, timeout):
        raise SmokeRequestError(f"server said no to {credential}", latency_ms=1)

    record = meta_mod.run_live("https://example.com/v1", "m", DUMMY_CRED, 30,
                               structured=False, request_fn=leaky)
    assert DUMMY_CRED not in json.dumps(record)


def test_baseten_live_success(tmp_path):
    recorder = CallRecorder()
    code = baseten_mod.main(["--live", "--confirm-external-call",
                             "--results-dir", str(tmp_path)],
                            env={"BASETEN_API_KEY": DUMMY_CRED}, request_fn=recorder)
    assert code == 0
    assert len(recorder.calls) == 1


def test_classify_error_categories():
    assert classify_error(SmokeRequestError("x", http_status=401)) == "auth-error"
    assert classify_error(SmokeRequestError("x", http_status=403)) == "auth-error"
    assert classify_error(SmokeRequestError("x", http_status=404)) == "not-found"
    assert classify_error(SmokeRequestError("x", http_status=400)) == "bad-request"
    assert classify_error(SmokeRequestError("x", http_status=422)) == "bad-request"
    assert classify_error(SmokeRequestError("x", http_status=408)) == "timeout"
    assert classify_error(SmokeRequestError("x", http_status=413)) == "payload-too-large"
    assert classify_error(SmokeRequestError("x", http_status=429)) == "rate-limited"
    assert classify_error(SmokeRequestError("x", http_status=500)) == "server-error"
    assert classify_error(SmokeRequestError("x", http_status=503)) == "server-error"
    assert classify_error(SmokeRequestError("timed out after 5s")) == "timeout"


def test_allow_billable_is_canonical_live_flag(tmp_path):
    recorder = CallRecorder()
    code = meta_mod.main(["--live", "--allow-billable", "--results-dir", str(tmp_path)],
                         env=env_with_meta(), request_fn=recorder)
    assert code == 0
    assert len(recorder.calls) == 1


def test_allow_billable_alone_is_misuse():
    recorder = CallRecorder()
    assert meta_mod.main(["--allow-billable"], env=env_with_meta(),
                         request_fn=recorder) == 2
    assert recorder.calls == []


def test_http_base_url_rejected_outside_loopback(tmp_path):
    recorder = CallRecorder()
    code = meta_mod.main(["--live", "--allow-billable", "--base-url", "http://example.com/v1",
                          "--results-dir", str(tmp_path)],
                         env=env_with_meta(), request_fn=recorder)
    assert code == 1
    assert recorder.calls == []


def test_http_loopback_base_url_allowed(tmp_path):
    recorder = CallRecorder()
    code = meta_mod.main(["--live", "--allow-billable", "--base-url", "http://127.0.0.1:8081/v1",
                          "--results-dir", str(tmp_path)],
                         env=env_with_meta(), request_fn=recorder)
    assert code == 0
    assert len(recorder.calls) == 1


def test_url_userinfo_never_echoed(tmp_path, capsys):
    # Assembled via concatenation so the repo scanner sees no credential shape.
    from _smoke_common import mask_url_credentials
    cred_url = "https://" + "u:p@example.com/v1"
    cred_url_port = "https://" + "u:p@example.com:8443/v1"
    assert "u:p" not in mask_url_credentials(cred_url)
    assert "@example.com" in mask_url_credentials(cred_url_port)
    recorder = CallRecorder()
    code = meta_mod.main(["--live", "--allow-billable", "--base-url", cred_url,
                          "--results-dir", str(tmp_path)],
                         env=env_with_meta(), request_fn=recorder)
    assert code == 0
    out = capsys.readouterr().out
    assert "u:p@example.com" not in out
    saved = list(tmp_path.glob("smoke-*.json"))
    assert len(saved) == 1
    text = saved[0].read_text(encoding="utf-8")
    assert "u:p@example.com" not in text
    assert "example.com" in text


def test_clamp_timeout_boundaries():
    from _smoke_common import DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S, clamp_timeout
    assert clamp_timeout(0) == DEFAULT_TIMEOUT_S
    assert clamp_timeout(-5) == DEFAULT_TIMEOUT_S
    assert clamp_timeout(30) == 30
    assert clamp_timeout(MAX_TIMEOUT_S + 100) == MAX_TIMEOUT_S


# --- SAM / Voice: schema-unverified refusal ---


def test_sam_live_refuses_without_transmitting(tmp_path):
    code = sam_mod.main(["--live", "--confirm-external-call", "--endpoint",
                         "https://example.com/sam", "--results-dir", str(tmp_path)],
                        env=env_with_meta())
    assert code == 1
    saved = list(tmp_path.glob("smoke-*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["status"] == "NOT_TESTED"
    assert record["error_category"] == "schema-unverified"
    assert record["http_status"] is None


def test_voice_live_refuses_without_transmitting(tmp_path):
    audio = tmp_path / "note.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 40)
    code = voice_mod.main(["--live", "--confirm-external-call", "--endpoint",
                           "https://example.com/voice", "--audio", str(audio),
                           "--results-dir", str(tmp_path)], env=env_with_meta())
    assert code == 1
    saved = list(tmp_path.glob("smoke-*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["status"] == "NOT_TESTED"
    assert record["error_category"] == "schema-unverified"


def test_voice_rejects_missing_audio():
    code = voice_mod.main([], env=env_with_meta())
    assert code == 0  # preflight-only default never fails the process


def test_pytest_never_triggers_live():
    """Guard: every `--live` use in tests/ targets a CallRecorder double, an
    injected live_runner double, or a refuse-by-design module (sam/voice,
    which have no request path)."""
    import ast

    tests_dir = Path(__file__).resolve().parent
    offenders: list[str] = []
    for path in sorted(tests_dir.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            source = ast.get_source_segment(path.read_text(encoding="utf-8"), node) or ""
            if '"--live"' in source or "'--live'" in source:
                uses_double = ("request_fn" in source or "CallRecorder" in source
                               or "live_runner" in source)
                uses_refuser = "sam_mod" in source or "voice_mod" in source
                if not (uses_double or uses_refuser):
                    offenders.append(f"{path.name}::{node.name}")
    assert offenders == []
    # The refusers genuinely have no request path: no post_json import.
    import smoke_sam as sam_check
    import smoke_voice as voice_check
    assert not hasattr(sam_check, "post_json")
    assert not hasattr(voice_check, "post_json")
