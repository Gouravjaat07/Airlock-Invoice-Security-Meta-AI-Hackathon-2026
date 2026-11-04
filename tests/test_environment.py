"""Tests for scripts/check_environment.py and scripts/check_hardware.py."""

import json
import sys

import pytest

import check_environment as env_mod
import check_hardware as hw_mod

STATUSES = {"PASS", "FAIL", "WARNING", "NOT_AVAILABLE", "NOT_TESTED"}


def test_run_command_missing_executable():
    ok, output = env_mod.run_command(["airlock-no-such-binary-xyz"])
    assert ok is False
    assert "not found" in output.lower()


def test_run_command_nonzero_exit():
    ok, _ = env_mod.run_command(
        [sys.executable, "-c", "import sys; sys.exit(3)"])
    assert ok is False


def test_all_checks_return_valid_statuses():
    for result in env_mod.run_environment_checks():
        assert result["status"] in STATUSES
        assert result["check_id"] and result["name"] and result["detail"]


def test_check_python_matches_interpreter():
    result = env_mod.check_python()
    if sys.version_info[:2] == (3, 11):
        assert result["status"] == "PASS"
    elif sys.version_info[:2] > (3, 11):
        assert result["status"] == "WARNING"
    else:
        assert result["status"] == "FAIL"


def test_check_dev_packages_reports_missing(monkeypatch):
    import importlib.util
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "pytest":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    result = env_mod.check_dev_packages()
    assert result["status"] == "WARNING"
    assert "pytest" in result["detail"]


def test_find_project_root_prefers_nearest(tmp_path, monkeypatch):
    # NOTE: pytest temp dirs may live under the repo (sandbox tempdir), so the
    # "no root" case cannot be assumed here; test nearest-root resolution.
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.chdir(inner)
    assert env_mod.find_project_root() == outer.resolve()
    assert env_mod.find_project_root(start=inner) == outer.resolve()


def test_scaffold_missing_project_dir(tmp_path):
    result = env_mod.check_scaffold(tmp_path)
    assert result["status"] == "FAIL"
    assert result["evidence"]["missing"]


def test_scaffold_unknown_root_not_tested():
    result = env_mod.check_scaffold(None)
    assert result["status"] == "NOT_TESTED"


def test_weight_files_found_in_tmp_root(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "reader.gguf").write_bytes(b"\x00" * 16)
    result = env_mod.check_weight_files(tmp_path)
    assert result["status"] == "WARNING"
    assert "reader.gguf" in result["detail"]


def test_weight_files_absent_is_pass(tmp_path):
    result = env_mod.check_weight_files(tmp_path)
    assert result["status"] == "PASS"


def test_weight_scan_skips_pytest_temp_dirs(tmp_path):
    models = tmp_path / "pytest-of-user" / "pytest-0" / "models"
    models.mkdir(parents=True)
    (models / "reader.gguf").write_bytes(b"\x00" * 16)
    assert env_mod.check_weight_files(tmp_path)["status"] == "PASS"
    assert hw_mod.find_weight_files(tmp_path) == []


def test_run_command_shell_fallback_for_cmd_shim(tmp_path, monkeypatch):
    import os
    if os.name != "nt":
        pytest.skip("Windows .cmd shim behavior")
    shim = tmp_path / "airlockshim.cmd"
    shim.write_text("@echo AIRLOCK_SHIM_OK\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    ok, output = env_mod.run_command(["airlockshim"])
    assert ok is True
    assert "AIRLOCK_SHIM_OK" in output


def test_git_status_outside_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = env_mod.check_git_status()
    # git present + readable -> WARNING (not a repo); git absent -> NOT_TESTED;
    # git present but repo unreadable (e.g. sandbox ownership) -> NOT_AVAILABLE.
    assert result["status"] in ("WARNING", "NOT_TESTED", "NOT_AVAILABLE")


def test_muse_cli_never_passes_without_version():
    result = env_mod.check_muse_cli()
    assert result["status"] in STATUSES
    if result["status"] == "PASS":
        assert result["evidence"].get("version")
    else:
        assert result["detail"]


def test_git_repo_unreadable_is_not_not_a_repo(monkeypatch):
    def fake_run(argv, timeout=10):
        if argv[:2] == ["git", "--version"]:
            return True, "git version 2.50.1.windows.1"
        return False, "fatal: detected dubious ownership in repository at 'D:/x'"

    monkeypatch.setattr(env_mod, "run_command", fake_run)
    result = env_mod.check_git()
    assert result["status"] == "WARNING"
    assert "unavailable" in result["detail"]
    assert "not inside a Git repository" not in result["detail"]


def test_unavailable_optional_tools_are_not_failures(monkeypatch):
    real_run = env_mod.run_command
    monkeypatch.setattr(env_mod, "run_command", lambda argv, timeout=10: (False, "missing"))
    for result in env_mod.check_node_npm():
        assert result["status"] == "NOT_AVAILABLE"
    assert env_mod.check_git()["status"] == "NOT_AVAILABLE"
    monkeypatch.setattr(env_mod, "run_command", real_run)


def test_config_var_presence_reports_names_only():
    result = env_mod.check_config_var_presence()
    assert result["status"] == "PASS"
    for name, is_set in result["evidence"]["presence"].items():
        assert isinstance(is_set, bool), name


def test_json_output_written_and_valid(tmp_path):
    out = tmp_path / "sub" / "env.json"
    code = env_mod.main(["--json", str(out)])
    assert code in (0, 1)
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "checks" in data and "summary" in data
    assert sum(data["summary"].values()) == len(data["checks"])


def test_invalid_json_output_path(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    code = env_mod.main(["--json", str(blocker / "env.json")])
    assert code == 1


# --- Hardware audit ---


def test_hardware_audit_structure():
    report = hw_mod.run_hardware_audit()
    for key in ("platform", "system_ram", "nvidia_smi", "video_controllers",
                "disk", "runtimes", "weight_files", "decision", "rationale"):
        assert key in report
    assert report["decision"] in ("LOCAL_GLIMMER_FEASIBLE",
                                  "LOCAL_GLIMMER_REQUIRES_EXPERIMENT",
                                  "LOCAL_GLIMMER_UNAVAILABLE")


def test_nvidia_missing_is_not_proof():
    info = hw_mod.get_nvidia_info()
    assert "available" in info and "gpus" in info
    # Absence must be reported as unavailable probe, never as a GPU verdict.
    if not info["available"]:
        assert info["gpus"] == []


def test_feasibility_unavailable_without_gpu_signal():
    nvidia = {"available": False, "gpus": []}
    controllers = {"available": True, "devices": [{"name": "unknown"}]}
    disk = {"free_gib": 100.0}
    runtimes = {"torch": {"installed": False}}
    decision, rationale = hw_mod.decide_feasibility(nvidia, controllers, disk, runtimes, [])
    assert decision == "LOCAL_GLIMMER_UNAVAILABLE"
    assert rationale


def test_feasibility_insufficient_vram_is_unavailable():
    nvidia = {"available": True,
              "gpus": [{"name": "Small GPU", "vram_total_mib": 8192, "vram_free_mib": 7000}]}
    controllers = {"available": True, "devices": []}
    disk = {"free_gib": 100.0}
    runtimes = {"torch": {"installed": True, "cuda_available": True}}
    decision, _ = hw_mod.decide_feasibility(nvidia, controllers, disk, runtimes, [])
    assert decision == "LOCAL_GLIMMER_UNAVAILABLE"


def test_feasibility_needs_more_than_vram_number():
    # Known-sufficient VRAM but no runtime and no disk margin -> not FEASIBLE.
    nvidia = {"available": True,
              "gpus": [{"name": "Big GPU", "vram_total_mib": 24576, "vram_free_mib": 20000}]}
    controllers = {"available": True, "devices": []}
    disk = {"free_gib": 100.0}
    runtimes = {"torch": {"installed": False}}
    decision, _ = hw_mod.decide_feasibility(nvidia, controllers, disk, runtimes, [])
    assert decision in ("LOCAL_GLIMMER_REQUIRES_EXPERIMENT", "LOCAL_GLIMMER_UNAVAILABLE")


def test_disk_units_are_gib_everywhere():
    info = hw_mod.get_disk_info(None)
    assert "free_gib" in info and "total_gib" in info
    assert "free_gb" not in info


def test_feasibility_unknown_vram_requires_experiment():
    nvidia = {"available": False, "gpus": []}
    controllers = {"available": True, "devices": [
        {"name": "Some Display Adapter", "vram_gib_estimate": None}]}
    disk = {"free_gib": 100.0}
    runtimes = {"torch": {"installed": False}}
    decision, rationale = hw_mod.decide_feasibility(nvidia, controllers, disk, runtimes, [])
    assert decision == "LOCAL_GLIMMER_REQUIRES_EXPERIMENT"
    assert "VRAM unknown" in rationale or "unknown" in rationale.lower()


def test_zero_adapter_ram_is_not_zero_vram():
    # A device reporting AdapterRAM 0/None must not be treated as 0 GiB known.
    assert hw_mod.get_video_controllers() is not None  # smoke: never crashes
    nvidia = {"available": False, "gpus": []}
    controllers = {"available": True, "devices": [
        {"name": "Adapter", "vram_gib_estimate": None}]}
    disk = {"free_gib": 100.0}
    runtimes = {"torch": {"installed": False}}
    decision, _ = hw_mod.decide_feasibility(nvidia, controllers, disk, runtimes, [])
    assert decision != "LOCAL_GLIMMER_FEASIBLE"


def test_hw_run_command_missing_executable():
    ok, output = hw_mod.run_command(["airlock-no-such-binary-xyz"])
    assert ok is False
    assert "not found" in output.lower()


def test_hw_run_command_shell_fallback_for_cmd_shim(tmp_path, monkeypatch):
    import os
    if os.name != "nt":
        pytest.skip("Windows .cmd shim behavior")
    shim = tmp_path / "airlockhwshim.cmd"
    shim.write_text("@echo AIRLOCK_HW_SHIM_OK\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    ok, output = hw_mod.run_command(["airlockhwshim"])
    assert ok is True
    assert "AIRLOCK_HW_SHIM_OK" in output


def test_hardware_json_output(tmp_path):
    out = tmp_path / "hw.json"
    assert hw_mod.main(["--json", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["decision"] in ("LOCAL_GLIMMER_FEASIBLE",
                                "LOCAL_GLIMMER_REQUIRES_EXPERIMENT",
                                "LOCAL_GLIMMER_UNAVAILABLE")
