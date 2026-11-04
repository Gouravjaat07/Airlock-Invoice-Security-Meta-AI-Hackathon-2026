"""Phase 5 live-smoke wrapper safety (offline; doubles only)."""

import json

import phase5_live_smoke as smoke

DUMMY = "DUMMY-PHASE5-CRED"


def _env(**overrides):
    env = {"MODEL_API_KEY": DUMMY, "BASETEN_API_KEY": DUMMY + "-B"}
    env.update(overrides)
    return env


def _refusing_runner():
    def live_runner(name, base, model, key, timeout):
        raise AssertionError(f"network call attempted for {name}")
    return live_runner


def test_default_results_dir_is_phase5():
    args = smoke.build_parser().parse_args([])
    assert args.results_dir == "results/phase5"


def test_default_is_preflight_only(tmp_path):
    code = smoke.main(["--results-dir", str(tmp_path)], env=_env(),
                      live_runner=_refusing_runner())
    assert code == 0
    saved = list(tmp_path.glob("smoke-*.json"))
    assert len(saved) == 1
    record = json.loads(saved[0].read_text(encoding="utf-8"))
    assert record["test_type"] == "preflight"
    assert all(entry["status"] == "NOT_TESTED"
               for entry in record["providers"])
    assert DUMMY not in saved[0].read_text(encoding="utf-8")


def test_default_run_writes_under_phase5(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = smoke.main([], env=_env(), live_runner=_refusing_runner())
    assert code == 0
    assert list((tmp_path / "results" / "phase5").glob("smoke-*.json"))
    assert not (tmp_path / "results" / "phase1").exists()


def test_partial_live_flags_rejected(tmp_path):
    assert smoke.main(["--live", "--results-dir", str(tmp_path)],
                      env=_env(),
                      live_runner=_refusing_runner()) == 2
    assert smoke.main(["--allow-billable", "--results-dir", str(tmp_path)],
                      env=_env(),
                      live_runner=_refusing_runner()) == 2


def test_per_provider_selection_and_budget(tmp_path):
    calls = []

    def live_runner(name, base, model, key, timeout):
        calls.append(name)
        return True, "ok", 200, 11

    code = smoke.main(["--live", "--allow-billable", "--provider",
                       "meta-spark", "--results-dir", str(tmp_path)],
                      env=_env(), live_runner=live_runner)
    assert code == 0
    assert calls == ["meta-spark"]


def test_explicit_results_dir_honored(tmp_path):
    other = tmp_path / "custom"
    code = smoke.main(["--results-dir", str(other)], env=_env(),
                      live_runner=_refusing_runner())
    assert code == 0
    assert list(other.glob("smoke-*.json"))
