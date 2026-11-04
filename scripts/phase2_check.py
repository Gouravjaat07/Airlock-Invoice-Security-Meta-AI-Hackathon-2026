"""Phase 2 strict release gate: verify implementation and evidence.

Runs real checks (imports, migrations, API, pytest subsets, Phase 1
regression, hygiene, offline) and writes a structured report. Exit code
is nonzero unless the verdict is READY (--strict also fails on PARTIAL).

Usage: python scripts/phase2_check.py [--strict] [--output-dir DIR]
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

STATUS_ORDER = ("PASS", "PARTIAL", "FAIL", "BLOCKED", "NOT_TESTED",
                "NOT_AVAILABLE")


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
    parser = argparse.ArgumentParser(description="Phase 2 strict release gate.")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-dir", default="results/phase2")
    args = parser.parse_args(argv)

    root = find_project_root() or Path.cwd()
    sys.path.insert(0, str(root))
    checks: list[dict] = []
    python = sys.executable

    def pytest_check(check_id, name, paths, extra=None):
        cmd = [python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               *(extra or []), *paths]
        code, output = _run(cmd, root)
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

    # 1-4: import, config, migrations, integrity (in-process, temp DB).
    try:
        import app.main  # noqa: F401
        checks.append(_check("P2-01", "application import", "PASS",
                             "import app.main", 0, "app.main imports"))
    except Exception as exc:
        checks.append(_check("P2-01", "application import", "BLOCKED",
                             "import app.main", 1, repr(exc)[:300]))

    try:
        from app.config import Settings, _validate_safety
        from app.core.errors import AppError
        _validate_safety(Settings())
        try:
            _validate_safety(Settings(environment="production",
                                      allow_insecure_cookies=True))
            checks.append(_check("P2-02", "config validation", "FAIL",
                                 "unsafe config accepted", 1,
                                 "production+insecure accepted"))
        except AppError:
            checks.append(_check("P2-02", "config validation", "PASS",
                                 "safe defaults + unsafe rejected", 0, "ok"))
    except Exception as exc:
        checks.append(_check("P2-02", "config validation", "BLOCKED",
                             "load_settings", 1, repr(exc)[:300]))

    try:
        from app.config import Settings as _S
        from app.storage import database as _db
        with tempfile.TemporaryDirectory() as tmp:
            settings = _S(db_path=f"{tmp}/g.db", blob_dir=f"{tmp}/b")
            result = _db.upgrade(settings)
            ok, detail = _db.is_integrity_ok(settings)
        checks.append(_check(
            "P2-03", "migrations+integrity",
            "PASS" if result["current_version"] >= 1 and ok else "FAIL",
            "db upgrade + integrity_check", 0,
            f"version={result['current_version']} integrity={detail}"))
    except Exception as exc:
        checks.append(_check("P2-03", "migrations+integrity", "BLOCKED",
                             "db upgrade", 1, repr(exc)[:300]))

    # 5-6: API health + required routes via the socket-free harness.
    try:
        sys.path.insert(0, str(root / "tests"))
        import tests.asgi_harness as _h  # noqa: F401
        from app.config import Settings as _S2, override_settings
        from app.main import create_app
        with tempfile.TemporaryDirectory() as tmp:
            settings = _S2(db_path=f"{tmp}/g.db", blob_dir=f"{tmp}/b")
            from app.storage import database as _db2
            _db2.upgrade(settings)
            override_settings(settings)
            try:
                client = _h.ASGIClient(create_app())
                health = client.get("/api/v1/health")
                spec = client.get("/api/openapi.json").json()
            finally:
                override_settings(None)
        required = ["/api/v1/health", "/api/v1/auth/login",
                    "/api/v1/auth/logout", "/api/v1/auth/me",
                    "/api/v1/cases", "/api/v1/cases/{case_id}",
                    "/api/v1/cases/{case_id}/process",
                    "/api/v1/cases/{case_id}/reject",
                    "/api/v1/vendors", "/api/v1/vendors/{vendor_id}",
                    "/api/v1/proposals/{proposal_id}",
                    "/api/v1/proposals/{proposal_id}/challenge",
                    "/api/v1/proposals/{proposal_id}/confirm",
                    "/api/v1/payments/mock/{payment_id}",
                    "/api/v1/audit/{case_id}", "/api/v1/audit/verify",
                    "/api/v1/evaluation/run"]
        missing = [path for path in required
                   if path not in spec.get("paths", {})]
        checks.append(_check(
            "P2-04", "api health",
            "PASS" if health.status_code == 200 else "FAIL",
            "GET /api/v1/health", health.status_code,
            health.text[:300]))
        checks.append(_check(
            "P2-05", "required routes",
            "PASS" if not missing else "FAIL",
            "openapi path audit", 0 if not missing else 1,
            f"missing={missing}" if missing else
            f"{len(spec.get('paths', {}))} paths present"))
    except Exception as exc:
        checks.append(_check("P2-04", "api health", "BLOCKED",
                             "harness health", 1, repr(exc)[:300]))
        checks.append(_check("P2-05", "required routes", "BLOCKED",
                             "harness openapi", 1, repr(exc)[:300]))

    # 7-13: pytest subsets (real execution evidence).
    pytest_check("P2-06", "policy unit tests", ["tests/unit/test_policy_rules.py"])
    pytest_check("P2-07", "domain/state/arithmetic tests",
                 ["tests/unit/test_domain.py", "tests/unit/test_arithmetic.py",
                  "tests/unit/test_file_validation.py"])
    pytest_check("P2-08", "database+pipeline integration", ["tests/integration"])
    pytest_check("P2-09", "api tests", ["tests/api"])
    pytest_check("P2-10", "security+executor tests", ["tests/security"])
    pytest_check("P2-11", "adversarial+offline tests", ["tests/adversarial"])
    pytest_check("P2-12", "failure-injection tests", ["tests/failure_injection"])
    pytest_check("P2-13", "end-to-end workflows", ["tests/end_to_end"])

    # 14: Phase 1 regression (top-level legacy tests + orchestrator).
    code, output = _run(
        [python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/test_configuration.py", "tests/test_environment.py",
         "tests/test_manifest_schema.py", "tests/test_orchestrator_cli.py",
         "tests/test_phase1_report.py", "tests/test_secret_hygiene.py",
         "tests/test_smoke_test_safety.py"], root)
    checks.append(_check("P2-14", "phase1 test regression",
                         "PASS" if code == 0 else "FAIL",
                         "pytest tests/test_*.py", code, output))
    code, output = _run([python, "scripts/phase1_check.py"], root)
    checks.append(_check("P2-15", "phase1 orchestrator still PARTIAL",
                         "PASS" if "OVERALL: PARTIAL" in output else "FAIL",
                         "phase1_check.py", code, output[-600:]))

    # 16-17: manifest + hygiene.
    code, output = _run(
        [python, "scripts/validate_manifest.py",
         "eval/manifest.dev.template.json"], root)
    checks.append(_check("P2-16", "manifest v2 compatibility",
                         "PASS" if code == 0 else "FAIL",
                         "validate_manifest template", code, output))
    code, output = _run([python, "scripts/check_secret_hygiene.py"], root)
    checks.append(_check("P2-17", "secret hygiene",
                         "PASS" if code == 0 else "FAIL",
                         "check_secret_hygiene.py", code, output[-600:]))

    # 18: fixtures deterministic.
    code, output = _run([python, "scripts/make_fixtures.py", "--check"],
                        root)
    checks.append(_check("P2-18", "fixture determinism",
                         "PASS" if code == 0 else "FAIL",
                         "make_fixtures.py --check", code, output))

    # 19: docs presence.
    required_docs = ["docs/phase2/README.md", "docs/phase2/API.md",
                     "docs/phase2/DATABASE.md", "docs/phase2/POLICY.md",
                     "docs/phase2/AUTH.md", "docs/phase2/AUDIT.md",
                     "docs/phase2/ADAPTERS.md", "docs/phase2/MIGRATION.md",
                     "docs/phase2/LIMITATIONS.md",
                     "docs/phase2/EVALUATION.md"]
    missing_docs = [doc for doc in required_docs
                    if not (root / doc).is_file()]
    checks.append(_check("P2-19", "documentation presence",
                         "PASS" if not missing_docs else "FAIL",
                         "docs inventory", 0 if not missing_docs else 1,
                         f"missing={missing_docs}" if missing_docs else "all present"))

    # 20: coverage + lint tooling availability (informational, non-mandatory).
    for tool in ("coverage", "ruff"):
        code, output = _run([python, "-m", tool, "--version"], root,
                            timeout=60)
        checks.append(_check(
            f"P2-20-{tool}", f"{tool} available",
            "PASS" if code == 0 else "NOT_AVAILABLE",
            f"{tool} --version", code, output[-200:], mandatory=False,
            limitation="" if code == 0 else
            "tool not installed in this environment"))

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
    atomic_write_json(out_dir / "phase2_report.json", report)
    (out_dir / "phase2_report.md").write_text(_markdown(report),
                                              encoding="utf-8")

    print(f"Phase 2 gate: {verdict} "
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
    lines = ["# Airlock Phase 2 gate report", "",
             f"Verdict: **{report['verdict']}**", "",
             f"Generated: {report['timestamp_utc']}  ",
             f"Tool: {report['tool_version']}  ",
             f"Python: {report['python']}  ",
             f"Commit: {report['git_commit']}", "",
             "| Check | Name | Status |", "|---|---|---|"]
    for check in report["checks"]:
        lines.append(f"| {check['check_id']} | {check['name']} | "
                     f"{check['status']} |")
    lines += ["", "Details: `phase2_report.json` (same directory).", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
