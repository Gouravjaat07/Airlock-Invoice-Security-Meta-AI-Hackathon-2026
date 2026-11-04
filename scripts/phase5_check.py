"""Phase 5 acceptance gate: live-ready providers + offline evidence.

Runs real checks (imports, config matrix, contract suites, Phase 5
offline suites, hygiene, lint, docs, eval, benchmark smoke) and writes
a structured report. Live provider calls are NEVER made here; live
status is classified separately by `phase5_live_smoke.py` (default:
preflight only, NOT_TESTED).

Usage: python scripts/phase5_check.py [--strict] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    TOOL_VERSION,
    atomic_write_json,
    default_audit_root,
    find_project_root,
    git_commit,
    utc_now_iso,
)


def _run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=str(cwd))
    except subprocess.TimeoutExpired:
        return 99, "TIMEOUT"
    except OSError as exc:
        return 98, f"SPAWN FAILED: {exc}"
    output = (completed.stdout + completed.stderr)[-4000:]
    return completed.returncode, output


def _check(check_id: str, name: str, status: str, command: str,
           exit_code: int | None, output: str, *,
           mandatory: bool = True, limitation: str = "") -> dict:
    return {"check_id": check_id, "name": name, "status": status,
            "mandatory": mandatory,
            "timestamp_utc": utc_now_iso(), "command": command,
            "exit_code": exit_code, "output": output[-1500:],
            "limitation": limitation}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 5 acceptance gate.")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-dir", default="results/phase5")
    args = parser.parse_args(argv)

    root = find_project_root() or Path.cwd()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    checks: list[dict] = []
    python = sys.executable

    def pytest_check(check_id, name, paths):
        cmd = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               *paths]
        code, output = _run(cmd, root, timeout=900)
        if code == 0:
            status = "PASS"
        elif code == 5:
            status, output = "NOT_TESTED", "no tests collected"
        elif "ModuleNotFoundError" in output or "ImportError" in output:
            status = "BLOCKED"
        else:
            status = "FAIL"
        checks.append(_check(check_id, name, status, " ".join(cmd), code,
                             output))

    # P5-01: provider + Phase 5 script imports.
    try:
        import app.providers.baseten  # noqa: F401
        import app.providers.glimmer  # noqa: F401
        import app.providers.meta  # noqa: F401
        import app.providers.registry  # noqa: F401
        import app.providers.sam  # noqa: F401
        import app.providers.spark  # noqa: F401
        import app.providers.voice  # noqa: F401
        import phase5_benchmark  # noqa: F401
        import phase5_eval  # noqa: F401
        import phase5_live_smoke  # noqa: F401
        checks.append(_check("P5-01", "provider + phase5 imports", "PASS",
                             "import app.providers.* + phase5_*", 0,
                             "all import"))
    except Exception as exc:
        checks.append(_check("P5-01", "provider + phase5 imports", "BLOCKED",
                             "import app.providers.* + phase5_*", 1,
                             repr(exc)[:300]))

    # P5-02: live-provider config matrix (no network; fake creds only).
    try:
        from app.config import Settings, _validate_safety
        from app.core.errors import AppError
        from app.providers.registry import (
            Availability,
            all_statuses,
        )
        live = Settings(environment="test", model_api_key="tk",
                        baseten_api_key="tk2", reader_provider="spark",
                        voice_provider="meta", vision_provider="sam")
        _validate_safety(live)
        ready = [s for s in all_statuses(live)
                 if s.availability == Availability.READY]
        missing = Settings(environment="test", reader_provider="spark",
                           voice_provider="meta", vision_provider="sam")
        absent = [s for s in all_statuses(missing)
                  if s.availability == Availability.MISSING_CREDENTIAL]
        bad_cases = [
            Settings(environment="production"),
            Settings(reader_provider="watson"),
            Settings(meta_api_base="http://api.meta.ai/v1"),
            Settings(spark_model="muse-spark-1.3-contributor"),
            Settings(model_api_key="same", baseten_api_key="same"),
        ]
        rejected = 0
        for bad in bad_cases:
            try:
                _validate_safety(bad)
            except AppError:
                rejected += 1
        stale = (root / "app" / "adapters" / "readers.py").read_text(
            encoding="utf-8")
        no_stale_copy = "intentionally absent in Phase 2" not in stale
        ok = (len(ready) == 3 and len(absent) == 3
              and rejected == len(bad_cases) and no_stale_copy)
        checks.append(_check(
            "P5-02", "live-provider config matrix",
            "PASS" if ok else "FAIL", "fake-cred statuses + unsafe "
            "rejected + stale-copy absent", 0,
            f"ready={len(ready)}/3 missing={len(absent)}/3 "
            f"rejected={rejected}/{len(bad_cases)} "
            f"stale_copy={'absent' if no_stale_copy else 'PRESENT'}"))
    except Exception as exc:
        checks.append(_check("P5-02", "live-provider config matrix",
                             "BLOCKED", "config matrix", 1,
                             repr(exc)[:300]))

    # P5-03: prompt/schema pinning.
    try:
        from app.providers.prompts import (
            EXTRACTION_JSON_SCHEMA,
            EXTRACTION_PROMPT_VERSION,
            EXTRACTION_SCHEMA_VERSION,
            SAM_PROMPT_VERSION,
        )
        assert EXTRACTION_PROMPT_VERSION and EXTRACTION_SCHEMA_VERSION
        assert SAM_PROMPT_VERSION and isinstance(EXTRACTION_JSON_SCHEMA, dict)
        assert EXTRACTION_JSON_SCHEMA["type"] == "object"
        checks.append(_check("P5-03", "prompt/schema pinning", "PASS",
                             "version constants present", 0, "pinned"))
    except Exception as exc:
        checks.append(_check("P5-03", "prompt/schema pinning", "FAIL",
                             "version constants present", 1, repr(exc)[:300]))

    # P5-04..P5-07: offline test suites.
    pytest_check("P5-04", "phase 5 offline suites", ["tests/phase5"])
    pytest_check("P5-05", "provider contract suites", ["tests/providers"])
    pytest_check("P5-06", "adversarial + failure injection",
                 ["tests/adversarial", "tests/failure_injection"])
    pytest_check("P5-07", "providers api", ["tests/api/test_providers_api.py"])

    # P5-08: secret hygiene.
    code, output = _run([python, "scripts/check_secret_hygiene.py"], root)
    checks.append(_check("P5-08", "secret hygiene",
                         "PASS" if code == 0 else "FAIL",
                         "check_secret_hygiene.py", code, output[-600:]))

    # P5-09: lint.
    code, output = _run([python, "-m", "ruff", "check", "scripts", "tests",
                         "app"], root, timeout=120)
    checks.append(_check("P5-09", "ruff",
                         "PASS" if code == 0 else "FAIL",
                         "ruff check scripts tests app", code,
                         output[-600:]))

    # P5-10: docs presence.
    required_docs = ["docs/phase5/PHASE5_IMPLEMENTATION_PLAN.md",
                     "docs/integrations/META_API_CONTRACTS.md",
                     "docs/integrations/MUSE_SPARK_SETUP.md",
                     "docs/integrations/MUSE_VOICE_SETUP.md",
                     "docs/integrations/SAM_SETUP.md",
                     "docs/integrations/BASETEN_SETUP.md",
                     "docs/integrations/GLIMMER_LOCAL_SETUP.md",
                     "docs/architecture/PROVIDER_ARCHITECTURE.md",
                     "docs/architecture/TRUST_BOUNDARIES.md",
                     "docs/operations/LIVE_PROVIDER_CONFIGURATION.md",
                     "docs/operations/PROVIDER_FAILURE_RUNBOOK.md",
                     "docs/operations/TROUBLESHOOTING.md",
                     "docs/phase5/PHASE5_BENCHMARK_METHODOLOGY.md",
                     "docs/REVIEWER_GUIDE.md"]
    missing_docs = [doc for doc in required_docs
                    if not (root / doc).is_file()]
    checks.append(_check("P5-10", "phase 5 docs",
                         "PASS" if not missing_docs else "FAIL",
                         "docs inventory", 0 if not missing_docs else 1,
                         f"missing={missing_docs}" if missing_docs else
                         "all present"))

    # P5-11: Phase 5 evaluation runs green offline (no false-ALLOW).
    code, output = _run([python, "scripts/phase5_eval.py"], root, timeout=900)
    checks.append(_check("P5-11", "phase 5 offline evaluation",
                         "PASS" if code == 0 else "FAIL",
                         "phase5_eval.py", code, output[-600:]))

    # P5-12: benchmark offline smoke (fast subset, temp output).
    with tempfile.TemporaryDirectory() as tmp:
        code, output = _run(
            [python, "scripts/phase5_benchmark.py", "--cases", "2",
             "--output-dir", tmp], root, timeout=900)
    checks.append(_check("P5-12", "benchmark offline smoke",
                         "PASS" if code == 0 else "FAIL",
                         "phase5_benchmark.py --cases 2", code,
                         output[-600:]))

    # P5-13: live smoke defaults to preflight-only (no live calls here).
    code, output = _run([python, "scripts/phase5_live_smoke.py"], root,
                        timeout=300)
    checks.append(_check(
        "P5-13", "live smoke safe by default",
        "PASS" if code == 0 and "no live request" in output.lower() else "FAIL",
        "phase5_live_smoke.py (preflight)", code, output[-600:]))

    # P5-14: Phase 3 strict regression (includes Phase 2).
    code, output = _run([python, "scripts/phase3_check.py", "--strict"],
                        root, timeout=1800)
    checks.append(_check("P5-14", "phase 3 strict regression",
                         "PASS" if code == 0 and "READY" in output else "FAIL",
                         "phase3_check.py --strict", code, output[-600:]))

    # Verdict.
    mandatory = [check for check in checks if check["mandatory"]]
    statuses = {check["status"] for check in mandatory}
    if "FAIL" in statuses:
        verdict = "FAILED"
    elif "BLOCKED" in statuses:
        verdict = "BLOCKED"
    elif statuses <= {"PASS"}:
        verdict = "READY"
    else:
        verdict = "PARTIAL"

    report = {
        "verdict": verdict,
        "tool_version": TOOL_VERSION,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(default_audit_root()),
        "python": sys.version.split()[0],
        "checks": checks,
    }
    out_dir = root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "phase5_report.json", report)
    (out_dir / "phase5_report.md").write_text(_markdown(report),
                                              encoding="utf-8")

    print(f"Phase 5 gate: {verdict} "
          f"({sum(1 for c in checks if c['status'] == 'PASS')}/{len(checks)} pass)")
    for check in checks:
        if check["status"] != "PASS":
            print(f"  [{check['status']}] {check['check_id']} {check['name']}")
    if verdict == "READY":
        return 0
    if verdict == "PARTIAL" and not args.strict:
        return 0
    return 1


def _markdown(report: dict) -> str:
    lines = ["# Airlock Phase 5 gate report", "",
             f"Verdict: **{report['verdict']}**", "",
             f"Generated: {report['timestamp_utc']}  ",
             f"Tool: {report['tool_version']}  ",
             f"Commit: {report.get('git_commit') or 'unknown'}", "",
             "| Check | Name | Status |", "|---|---|---|"]
    for check in report["checks"]:
        lines.append(f"| {check['check_id']} | {check['name']} | "
                     f"{check['status']} |")
    lines.append("")
    lines.append("Live provider status is classified separately by "
                 "`phase5_live_smoke.py --live --allow-billable`; "
                 "this gate never makes network calls.")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
