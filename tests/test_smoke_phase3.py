"""Phase 3 smoke safety: preflight default, gating, budget, no leaks."""

import io
import json
import urllib.error

import smoke_phase3 as smoke
from _smoke_common import SmokeRequestError

DUMMY = "DUMMY-PHASE3-CRED"
NEW_MODEL = "meta-models/muse-spark-open-1026"


def _env(**overrides):
    env = {"MODEL_API_KEY": DUMMY, "BASETEN_API_KEY": DUMMY + "-B"}
    env.update(overrides)
    return env


def _recorder(results_dir=None, succeed=True):
    calls = []

    def live_runner(name, base, model, key, timeout):
        calls.append(name)
        if not succeed:
            raise RuntimeError("boom")
        return True, "ok", 200, 11

    live_runner.calls = calls
    return live_runner


def test_default_results_dir_is_phase3():
    args = smoke.build_parser().parse_args([])
    assert args.results_dir == "results/phase3"


def test_default_run_writes_nothing_under_phase1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    live_runner = _recorder()
    code = smoke.main([], env=_env(), live_runner=live_runner)
    assert code == 0
    assert live_runner.calls == []
    assert list((tmp_path / "results" / "phase3").glob("smoke-*.json"))
    assert not (tmp_path / "results" / "phase1").exists()


def test_default_is_preflight_only(tmp_path):
    live_runner = _recorder()
    code = smoke.main(["--results-dir", str(tmp_path)], env=_env(),
                      live_runner=live_runner)
    assert code == 0
    assert live_runner.calls == []
    saved = list(tmp_path.glob("smoke-*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["test_type"] == "preflight"
    assert all(entry["status"] == "NOT_TESTED"
               for entry in record["providers"])
    assert DUMMY not in saved[0].read_text(encoding="utf-8")


def test_partial_live_flags_rejected(tmp_path):
    live_runner = _recorder()
    assert smoke.main(["--live", "--results-dir", str(tmp_path)],
                      env=_env(), live_runner=live_runner) == 2
    assert smoke.main(["--allow-billable", "--results-dir", str(tmp_path)],
                      env=_env(), live_runner=live_runner) == 2
    assert live_runner.calls == []


def test_missing_key_blocks_live_call(tmp_path):
    live_runner = _recorder()
    code = smoke.main(["--live", "--allow-billable", "--provider",
                       "meta-spark", "--results-dir", str(tmp_path)],
                      env={}, live_runner=live_runner)
    assert code == 1
    assert live_runner.calls == []


def test_contributor_model_refused(tmp_path):
    live_runner = _recorder()
    code = smoke.main(["--live", "--allow-billable", "--provider",
                       "meta-spark", "--results-dir", str(tmp_path)],
                      env=_env(SPARK_MODEL="muse-spark-1.3-contributor"),
                      live_runner=live_runner)
    assert code == 1
    assert live_runner.calls == []


def test_budget_caps_live_calls(tmp_path):
    live_runner = _recorder()
    code = smoke.main(["--live", "--allow-billable", "--max-calls", "2",
                       "--results-dir", str(tmp_path)],
                      env=_env(), live_runner=live_runner)
    assert code == 1  # rest are NOT_TESTED, so not all-PASS
    assert len(live_runner.calls) == 2
    saved = list(tmp_path.glob("smoke-*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["calls_used"] == 2
    pending = [entry for entry in record["providers"]
               if entry["status"] == "NOT_TESTED"]
    assert pending and all("Budget exhausted" in entry["notes"]
                           for entry in pending)


def test_live_failure_sanitized(tmp_path):
    live_runner = _recorder(succeed=False)
    code = smoke.main(["--live", "--allow-billable", "--provider",
                       "meta-spark", "--results-dir", str(tmp_path)],
                      env=_env(), live_runner=live_runner)
    assert code == 1
    saved = list(tmp_path.glob("smoke-*.json"))
    assert DUMMY not in saved[0].read_text(encoding="utf-8")


def test_glimmer_keyless_preflight(tmp_path):
    live_runner = _recorder()
    code = smoke.main(["--provider", "glimmer", "--results-dir",
                       str(tmp_path)], env={}, live_runner=live_runner)
    assert code == 0
    saved = list(tmp_path.glob("smoke-*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["providers"][0]["preflight_ok"] is True


def _chat_body(content, finish="stop"):
    return json.dumps({"id": "chatcmpl_1", "choices": [
        {"index": 0, "message": {"role": "assistant", "content": content},
         "finish_reason": finish}]})


def _refusing_runner():
    def live_runner(name, base, model, key, timeout):
        raise AssertionError(f"network call attempted for {name}")
    return live_runner


# --- Baseten model identity (authoritative: NEW_MODEL) ---

def test_baseten_smoke_default_model_is_authoritative():
    assert smoke.CONFIGS["baseten"].model_default == NEW_MODEL


def test_app_config_default_model_is_authoritative():
    from app.config import Settings
    assert Settings().baseten_spark_open_model == NEW_MODEL


def test_validate_config_default_model_is_authoritative():
    import validate_config
    assert validate_config.DEFAULT_BASETEN_SPARK_OPEN_MODEL == NEW_MODEL


def test_env_model_override_respected():
    _, model, _ = smoke._resolve(
        "baseten", _env(BASETEN_SPARK_OPEN_MODEL=NEW_MODEL))
    assert model == NEW_MODEL


def test_baseten_default_resolves_to_authoritative():
    _, model, _ = smoke._resolve("baseten", _env())
    assert model == NEW_MODEL


# --- _live_chat request shaping (post_json doubled: no network) ---

def test_live_chat_baseten_uses_configured_model_and_budget(monkeypatch):
    seen = {}

    def fake_post(url, payload, api_key, timeout):
        seen.update(url=url, payload=payload)
        return 200, _chat_body("AIRLOCK_SMOKE_OK"), 9

    monkeypatch.setattr(smoke, "post_json", fake_post)
    ok, note, status, _ = smoke._live_chat(
        "https://inference.baseten.co/v1", NEW_MODEL, DUMMY, 30)
    assert (ok, note, status) == (True, "marker echoed", 200)
    assert seen["url"].endswith("/chat/completions")
    assert seen["payload"]["model"] == NEW_MODEL
    assert seen["payload"]["max_tokens"] == 512
    assert seen["payload"]["reasoning_effort"] == "low"


def test_live_chat_glimmer_request_unchanged(monkeypatch):
    seen = {}

    def fake_post(url, payload, api_key, timeout):
        seen.update(payload=payload)
        return 200, _chat_body("AIRLOCK_SMOKE_OK"), 9

    monkeypatch.setattr(smoke, "post_json", fake_post)
    ok, note, status, _ = smoke._live_chat(
        "http://127.0.0.1:8081/v1", "muse-glimmer", DUMMY, 30)
    assert (ok, note, status) == (True, "marker echoed", 200)
    assert seen["payload"]["model"] == "muse-glimmer"
    assert seen["payload"]["max_tokens"] == 16
    assert "reasoning_effort" not in seen["payload"]


def test_live_chat_http200_without_marker_fails(monkeypatch):
    monkeypatch.setattr(
        smoke, "post_json",
        lambda *a: (200, _chat_body("hello there"), 9))
    ok, note, status, _ = smoke._live_chat(
        "https://inference.baseten.co/v1", NEW_MODEL, DUMMY, 30)
    assert (ok, note, status) == (False, "marker missing", 200)


def test_live_chat_invalid_json_fails(monkeypatch):
    monkeypatch.setattr(
        smoke, "post_json", lambda *a: (200, "not json{", 9))
    ok, note, status, _ = smoke._live_chat(
        "https://inference.baseten.co/v1", NEW_MODEL, DUMMY, 30)
    assert (ok, note, status) == (False, "invalid JSON", 200)


def test_live_chat_invalid_shape_fails(monkeypatch):
    bodies = [json.dumps({"oops": 1}), json.dumps({"choices": []})]
    for body in bodies:
        monkeypatch.setattr(
            smoke, "post_json", lambda *a, b=body: (200, b, 9))
        ok, note, status, _ = smoke._live_chat(
            "https://inference.baseten.co/v1", NEW_MODEL, DUMMY, 30)
        assert (ok, note, status) == (False, "invalid chat shape", 200)


def test_live_chat_truncated_response_fails(monkeypatch):
    monkeypatch.setattr(
        smoke, "post_json",
        lambda *a: (200, _chat_body("AIRLOCK_SMOKE_", "length"), 9))
    ok, note, status, _ = smoke._live_chat(
        "https://inference.baseten.co/v1", NEW_MODEL, DUMMY, 30)
    assert ok is False and status == 200
    assert note == "incomplete response (finish_reason=length)"


def test_live_chat_empty_content_fails(monkeypatch):
    for content in ("", None):
        monkeypatch.setattr(
            smoke, "post_json",
            lambda *a, c=content: (200, _chat_body(c), 9))
        ok, note, status, _ = smoke._live_chat(
            "https://inference.baseten.co/v1", NEW_MODEL, DUMMY, 30)
        assert (ok, note, status) == (False, "empty response content", 200)


def test_live_chat_http_errors_fail(monkeypatch):
    for code in (401, 403, 500):
        def fake_post(*a, c=code):
            raise SmokeRequestError(f"HTTP {c}", http_status=c)

        monkeypatch.setattr(smoke, "post_json", fake_post)
        ok, note, status, _ = smoke._live_chat(
            "https://inference.baseten.co/v1", NEW_MODEL, DUMMY, 30)
        assert (ok, note, status) == (False, f"HTTP {code}", code)


def test_live_chat_timeout_reports_cause(monkeypatch):
    def fake_post(*a):
        raise SmokeRequestError("timed out after 30s", latency_ms=5)

    monkeypatch.setattr(smoke, "post_json", fake_post)
    ok, note, status, _ = smoke._live_chat(
        "https://inference.baseten.co/v1", NEW_MODEL, DUMMY, 30)
    assert ok is False and status is None
    assert "timed out" in note and "HTTP None" not in note


# --- keyless (Glimmer) transport branch (urlopen doubled: no network) ---

class _FakeResponse:
    def __init__(self, body):
        self.status = 200
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_live_chat_keyless_path_sends_no_auth(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["auth"] = request.get_header("Authorization")
        seen["payload"] = json.loads(request.data.decode())
        return _FakeResponse(_chat_body("AIRLOCK_SMOKE_OK"))

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    ok, note, status, _ = smoke._live_chat(
        "http://127.0.0.1:8081/v1", "muse-glimmer", "", 30)
    assert (ok, note, status) == (True, "marker echoed", 200)
    assert seen["auth"] is None
    assert seen["payload"]["max_tokens"] == 16
    assert "reasoning_effort" not in seen["payload"]


def test_live_chat_keyless_http_error_fails(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 500, "boom", None, io.BytesIO(b"err"))

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    ok, note, status, _ = smoke._live_chat(
        "http://127.0.0.1:8081/v1", "muse-glimmer", "", 30)
    assert (ok, note, status) == (False, "HTTP 500", 500)


# --- --model override ---

def test_model_override_reaches_preflight_record(tmp_path):
    code = smoke.main(["--provider", "baseten", "--model", NEW_MODEL,
                       "--results-dir", str(tmp_path)],
                      env={}, live_runner=_refusing_runner())
    assert code == 0
    saved = list(tmp_path.glob("smoke-*.json"))
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["providers"][0]["model_id"] == NEW_MODEL


def test_model_override_reaches_live_runner(tmp_path):
    seen = {}

    def live_runner(name, base, model, key, timeout):
        seen["model"] = model
        return True, "ok", 200, 11

    code = smoke.main(["--live", "--allow-billable", "--provider",
                       "baseten", "--model", NEW_MODEL,
                       "--results-dir", str(tmp_path)],
                      env=_env(), live_runner=live_runner)
    assert code == 0
    assert seen["model"] == NEW_MODEL


def test_model_override_rejected_with_all_providers(tmp_path):
    code = smoke.main(["--model", NEW_MODEL, "--results-dir",
                       str(tmp_path)], env=_env(),
                      live_runner=_refusing_runner())
    assert code == 2


def test_base_url_override_still_rejected(tmp_path):
    code = smoke.main(["--provider", "baseten", "--base-url",
                       "https://x.example/v1", "--results-dir",
                       str(tmp_path)], env=_env(),
                      live_runner=_refusing_runner())
    assert code == 2
