"""Airlock development-environment audit (Phase 1).

Inspects the local machine and repository scaffold. Safe by design:
no network requests, no package installation, no secret values printed.

Statuses: PASS, FAIL, WARNING, NOT_AVAILABLE, NOT_TESTED.
Exit code: 0 unless any check reports FAIL.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Scripts can also be imported by phase1_check.py; make sibling imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from validate_config import KNOWN_VARS
except ImportError:  # pragma: no cover
    KNOWN_VARS = ()

from _common import (  # noqa: E402
    atomic_write_json, find_project_root as _common_find_root,
    provenance_envelope,
)

COMMAND_TIMEOUT_S = 10

# Required Phase 1 scaffold (relative to project root).
REQUIRED_PATHS = [
    "README.md",
    ".gitignore",
    ".env.example",
    "pyproject.toml",
    "Makefile",
    "docs/SOURCES.md",
    "docs/ARCHITECTURE_DECISIONS.md",
    "docs/phase1/PHASE1_PLAN.md",
    "docs/phase1/PHASE1_REPORT.md",
    "docs/phase1/ENVIRONMENT_REPORT.md",
    "docs/phase1/INTEGRATION_STATUS.md",
    "docs/phase1/MODEL_ACCESS_MATRIX.md",
    "docs/phase1/HARDWARE_REPORT.md",
    "docs/phase1/DATA_FLOW_AND_PRIVACY.md",
    "docs/phase1/FALLBACK_DECISIONS.md",
    "docs/phase1/OPEN_BLOCKERS.md",
    "scripts/_common.py",
    "scripts/phase1_check.py",
    "scripts/check_environment.py",
    "scripts/check_hardware.py",
    "scripts/validate_config.py",
    "scripts/validate_manifest.py",
    "scripts/check_secret_hygiene.py",
    "scripts/record_smoke_result.py",
    "scripts/smoke_meta.py",
    "scripts/smoke_baseten.py",
    "scripts/smoke_sam.py",
    "scripts/smoke_voice.py",
    "prereg/PREREGISTRATION.md",
    "eval/manifest.schema.json",
    "eval/manifest.dev.template.json",
    "eval/README.md",
    "results/phase1/.gitkeep",
    "app/.gitkeep",
    "web/.gitkeep",
    "tests/test_environment.py",
    "tests/test_configuration.py",
    "tests/test_manifest_schema.py",
    "tests/test_secret_hygiene.py",
    "tests/test_smoke_test_safety.py",
    "tests/test_phase1_report.py",
    "tests/test_orchestrator_cli.py",
    "docs/phase1/MANIFEST_MIGRATION_v2.md",
    ".github/workflows/phase1.yml",
]

WEIGHT_SUFFIXES = (".gguf", ".safetensors", ".bin", ".pt", ".pth", ".onnx")

# Ephemeral/tooling directories excluded from the weight scan (test temp dirs
# hold synthetic fixtures by construction, never real weights).
WEIGHT_SKIP_DIRS = frozenset({".git", ".hg", ".sl", ".eden", ".agents", ".muse",
                              ".venv", "venv", "__pycache__", "node_modules"})
WEIGHT_SKIP_PREFIXES = ("pytest-of-",)


def _is_weight_candidate(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return False
    if any(part in WEIGHT_SKIP_DIRS for part in parts):
        return False
    if any(part.startswith(prefix) for part in parts for prefix in WEIGHT_SKIP_PREFIXES):
        return False
    return True


def make_result(check_id: str, name: str, status: str, detail: str,
                evidence: dict | None = None) -> dict:
    return {
        "check_id": check_id,
        "name": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def run_command(argv: list[str], timeout: int = COMMAND_TIMEOUT_S) -> tuple[bool, str]:
    """Run an external command safely. Returns (ok, combined_output)."""
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout)
    except FileNotFoundError:
        # Windows console shims (.cmd/.bat) need shell execution.
        if os.name == "nt" and argv:
            resolved = shutil.which(argv[0])
            if resolved and resolved.lower().endswith((".cmd", ".bat")):
                try:
                    completed = subprocess.run(
                        subprocess.list2cmdline(argv), capture_output=True,
                        text=True, encoding="utf-8", errors="replace",
                        timeout=timeout, shell=True)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    return False, f"shell fallback failed: {exc}"
                output = (completed.stdout + completed.stderr).strip()
                if completed.returncode != 0:
                    return False, output or f"exit code {completed.returncode}"
                return True, output
        return False, "executable not found"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except OSError as exc:
        return False, f"OS error: {exc}"
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return False, output or f"exit code {completed.returncode}"
    return True, output


def find_project_root(start: Optional[Path] = None) -> Optional[Path]:
    return _common_find_root(start=start)


def check_operating_system() -> dict:
    detail = f"{platform.system()} {platform.release()} ({platform.version()}); machine={platform.machine()}"
    return make_result("os", "Operating system", "PASS", detail,
                       {"system": platform.system(), "release": platform.release(),
                        "version": platform.version(), "machine": platform.machine()})


def check_python() -> dict:
    version = sys.version_info
    detail = f"{sys.executable} — Python {version.major}.{version.minor}.{version.micro}"
    if (version.major, version.minor) == (3, 11):
        return make_result("python", "Python runtime", "PASS",
                            detail + " (matches intended 3.11 runtime)",
                            {"executable": sys.executable, "version": list(version[:3])})
    if (version.major, version.minor) > (3, 11):
        return make_result("python", "Python runtime", "WARNING",
                            detail + " — Phase 1 tooling supports >=3.11, but the intended "
                                      "application runtime is Python 3.11; verify before Phase 2",
                            {"executable": sys.executable, "version": list(version[:3])})
    return make_result("python", "Python runtime", "FAIL",
                        detail + " — Python >=3.11 is required",
                        {"executable": sys.executable, "version": list(version[:3])})


def check_venv() -> dict:
    if importlib.util.find_spec("venv") is None:
        return make_result("venv", "Virtual-environment support", "FAIL",
                            "stdlib `venv` module is unavailable")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    detail = "stdlib `venv` available"
    detail += f"; running inside {sys.prefix}" if in_venv else "; not currently in a venv"
    return make_result("venv", "Virtual-environment support", "PASS", detail,
                       {"in_venv": in_venv, "prefix": sys.prefix})


def check_pip() -> dict:
    if importlib.util.find_spec("pip") is None:
        return make_result("pip", "pip availability", "WARNING",
                            "pip module not importable; dependency install would need bootstrapping")
    ok, output = run_command([sys.executable, "-m", "pip", "--version"])
    if not ok:
        return make_result("pip", "pip availability", "WARNING",
                            f"pip importable but `--version` failed: {output[:200]}")
    return make_result("pip", "pip availability", "PASS", output.splitlines()[0][:200] if output else "pip present")


def check_git() -> dict:
    ok, output = run_command(["git", "--version"])
    if not ok:
        return make_result("git", "Git availability", "NOT_AVAILABLE",
                            f"git not usable: {output[:200]}")
    version = output.splitlines()[0][:120] if output else "git present"
    repo_ok, repo_out = run_command(["git", "rev-parse", "--show-toplevel"])
    if not repo_ok:
        if "not a git repository" in repo_out.lower():
            return make_result("git", "Git availability", "WARNING",
                                f"{version}; current directory is not inside a Git repository",
                                {"version": version, "in_repo": False})
        return make_result("git", "Git availability", "WARNING",
                            f"{version}; repository status unavailable: "
                            f"{repo_out.strip()[:160]}",
                            {"version": version, "in_repo": None})
    return make_result("git", "Git availability", "PASS",
                        f"{version}; repo root: {repo_out.strip()[:200]}",
                        {"version": version, "in_repo": True})


def check_node_npm() -> list[dict]:
    results = []
    ok, output = run_command(["node", "--version"])
    if not ok:
        results.append(make_result("node", "Node.js", "NOT_AVAILABLE",
                                   f"node not usable: {output[:200]}"))
    else:
        results.append(make_result("node", "Node.js", "PASS",
                                   f"node {output.strip()[:60]} (needed only for the future web dashboard)"))
    ok, output = run_command(["npm", "--version"])
    if not ok:
        results.append(make_result("npm", "npm", "NOT_AVAILABLE",
                                   f"npm not usable: {output[:200]}"))
    else:
        results.append(make_result("npm", "npm", "PASS",
                                   f"npm {output.strip()[:60]} (needed only for the future web dashboard)"))
    return results


def check_muse_cli() -> dict:
    muse_path = shutil.which("muse")
    if muse_path is None:
        return make_result("muse_cli", "Muse Code CLI", "NOT_AVAILABLE",
                            "`muse` not found on PATH in this session; development assistance "
                            "availability cannot be confirmed here")
    ok, output = run_command(["muse", "--version"])
    if not ok:
        first_line = output.strip().splitlines()[0][:200] if output.strip() else "no output"
        return make_result("muse_cli", "Muse Code CLI", "NOT_AVAILABLE",
                            f"`muse` found at {muse_path} but `--version` failed ({first_line}); "
                            "on Windows this is often an un-runnable shell shim — use WSL/Git Bash "
                            "or the installed Muse app instead",
                            {"path": muse_path})
    return make_result("muse_cli", "Muse Code CLI", "PASS",
                        f"muse {output.strip()[:120]} at {muse_path}",
                        {"path": muse_path, "version": output.strip()[:120]})


def check_dev_packages() -> dict:
    found: dict[str, str] = {}
    missing: list[str] = []
    for name in ("pytest",):
        spec = importlib.util.find_spec(name)
        if spec is None:
            missing.append(name)
            continue
        try:
            module = importlib.import_module(name)
            found[name] = str(getattr(module, "__version__", "unknown"))
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            missing.append(f"{name} (import failed: {exc})")
    if missing:
        return make_result("dev_packages", "Developer packages", "WARNING",
                            f"missing: {', '.join(missing)} — run `pip install -e \".[dev]\"` "
                            "in the project .venv",
                            {"found": found, "missing": missing})
    return make_result("dev_packages", "Developer packages", "PASS",
                        "pytest " + found.get("pytest", "?") + " available",
                        {"found": found})


def check_working_directory(root: Optional[Path]) -> dict:
    cwd = str(Path.cwd().resolve())
    if root is None:
        return make_result("cwd", "Working directory", "WARNING",
                            f"cwd={cwd}; project root (pyproject.toml) not found above it",
                            {"cwd": cwd})
    return make_result("cwd", "Working directory", "PASS",
                        f"cwd={cwd}; project root={root}",
                        {"cwd": cwd, "root": str(root)})


def check_scaffold(root: Optional[Path]) -> dict:
    if root is None:
        return make_result("scaffold", "Repository scaffold", "NOT_TESTED",
                            "project root unknown; scaffold check skipped")
    missing = [rel for rel in REQUIRED_PATHS if not (root / rel).exists()]
    if missing:
        return make_result("scaffold", "Repository scaffold", "FAIL",
                            f"{len(missing)} required path(s) missing: {', '.join(missing[:8])}"
                            + (" ..." if len(missing) > 8 else ""),
                            {"missing": missing})
    return make_result("scaffold", "Repository scaffold", "PASS",
                        f"all {len(REQUIRED_PATHS)} required Phase 1 paths exist")


def check_disk(root: Optional[Path]) -> dict:
    target = str(root) if root else os.getcwd()
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return make_result("disk", "Disk availability", "NOT_AVAILABLE",
                            f"disk usage unreadable for {target}: {exc}")
    free_gib = usage.free / (1024 ** 3)
    detail = f"{free_gib:.1f} GiB free of {usage.total / (1024 ** 3):.1f} GiB on project drive ({target})"
    if free_gib < 5:
        return make_result("disk", "Disk availability", "WARNING",
                            detail + " — low free space", {"free_gib": round(free_gib, 2)})
    return make_result("disk", "Disk availability", "PASS", detail,
                       {"free_gib": round(free_gib, 2)})


def check_config_var_presence() -> dict:
    presence = {name: bool(os.environ.get(name, "").strip()) for name in KNOWN_VARS} if KNOWN_VARS else {}
    n_set = sum(1 for v in presence.values() if v)
    return make_result("config_vars", "Configuration variable presence", "PASS",
                        f"{n_set}/{len(presence)} known variables set (names only; values never shown). "
                        "Run `validate_config.py` for full validation.",
                        {"presence": presence})


def check_weight_files(root: Optional[Path]) -> dict:
    if root is None:
        return make_result("weights", "Local model weights", "NOT_TESTED",
                            "project root unknown; weight scan skipped")
    hits: list[str] = []
    for path in root.rglob("*"):
        if len(hits) >= 20:
            break
        if not _is_weight_candidate(path, root):
            continue
        if path.is_file() and (path.suffix.lower() in WEIGHT_SUFFIXES
                               or "glimmer" in path.name.lower()):
            try:
                hits.append(str(path.relative_to(root)))
            except ValueError:
                hits.append(path.name)
    if hits:
        return make_result("weights", "Local model weights", "WARNING",
                            f"{len(hits)} weight-like file(s) already present: {', '.join(hits[:5])}"
                            " — ensure they are git-ignored and licensed",
                            {"files": hits})
    return make_result("weights", "Local model weights", "PASS",
                        "no model weight files in the project directory (expected in Phase 1)")


def check_git_status() -> dict:
    ok, _ = run_command(["git", "--version"])
    if not ok:
        return make_result("git_status", "Uncommitted files", "NOT_TESTED",
                            "git unavailable; status check skipped")
    ok, output = run_command(["git", "status", "--short"])
    if not ok:
        if "not a git repository" in output.lower():
            return make_result("git_status", "Uncommitted files", "WARNING",
                                "not a Git repository yet; initialize with `git init` after inspection")
        return make_result("git_status", "Uncommitted files", "NOT_AVAILABLE",
                            f"`git status` failed: {output[:200]}")
    if not output.strip():
        return make_result("git_status", "Uncommitted files", "PASS",
                            "working tree clean")
    lines = output.strip().splitlines()
    return make_result("git_status", "Uncommitted files", "WARNING",
                        f"{len(lines)} uncommitted change(s)",
                        {"count": len(lines)})


def run_environment_checks() -> list[dict]:
    root = find_project_root()
    results: list[dict] = [
        check_operating_system(),
        check_python(),
        check_venv(),
        check_pip(),
        check_git(),
        *check_node_npm(),
        check_muse_cli(),
        check_dev_packages(),
        check_working_directory(root),
        check_scaffold(root),
        check_disk(root),
        check_config_var_presence(),
        check_weight_files(root),
        check_git_status(),
    ]
    return results


def summarize(results: list[dict]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in results:
        summary[item["status"]] = summary.get(item["status"], 0) + 1
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the Airlock dev environment (no network, no secrets).")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Write the structured report as JSON to this path.")
    args = parser.parse_args(argv)

    results = run_environment_checks()
    summary = summarize(results)

    print("Airlock environment audit")
    for item in results:
        print(f"  [{item['status']}] {item['name']}: {item['detail']}")
    print("  summary: " + ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))

    exit_code = 1 if summary.get("FAIL") else 0
    if args.json_path:
        report = {"checks": results, "summary": summary,
                  "provenance": provenance_envelope(
                      "check_environment", argv=argv, root=find_project_root(),
                      extra={"exit_code": exit_code})}
        try:
            atomic_write_json(args.json_path, report)
            print(f"  JSON report written to {args.json_path}")
        except OSError as exc:
            print(f"ERROR: cannot write JSON report: {exc}", file=sys.stderr)
            return 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
