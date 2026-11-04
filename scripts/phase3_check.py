"""Phase 3 acceptance gate: provider implementation + offline evidence.

Runs real checks (provider imports, config matrix, contract suites,
pipeline/injection/API suites, Phase 2 strict regression, hygiene,
lint, docs, eval) and writes a structured report. Live provider calls
are NEVER made here; live status is classified separately by
`smoke_phase3.py` (default: preflight only, NOT_TESTED).

Usage: python scripts/phase3_check.py [--strict] [--output-dir DIR]
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
    parser = argparse.ArgumentParser(description="Phase 3 acceptance gate.")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-dir", default="results/phase3")
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

    # P3-01: provider imports.
    try:
        import app.providers.baseten  # noqa: F401
        import app.providers.glimmer  # noqa: F401
        import app.providers.meta  # noqa: F401
        import app.providers.registry  # noqa: F401
        import app.providers.sam  # noqa: F401
        import app.providers.spark  # noqa: F401
        import app.providers.voice  # noqa: F401
        checks.append(_check("P3-01", "provider imports", "PASS",
                             "import app.providers.*", 0, "all import"))
    except Exception as exc:
        checks.append(_check("P3-01", "provider imports", "BLOCKED",
                             "import app.providers.*", 1, repr(exc)[:300]))

    # P3-02: provider config matrix.
    try:
        from app.config import Settings, _validate_safety
        from app.core.errors import AppError
        _validate_safety(Settings())
        bad_cases = [
            Settings(environment="production"),
            Settings(reader_provider="watson"),
            Settings(meta_api_base="http://api.meta.ai/v1"),
            Settings(spark_model="muse-spark-1.3-contributor"),
            Settings(glimmer_base_url="http://192.168.0.9:8081/v1"),
        ]
        rejected = 0
        for bad in bad_cases:
            try:
                _validate_safety(bad)
            except AppError:
                rejected += 1
        checks.append(_check(
            "P3-02", "provider config matrix",
            "PASS" if rejected == len(bad_cases) else "FAIL",
            "safe defaults + unsafe rejected", 0,
            f"rejected {rejected}/{len(bad_cases)}"))
    except Exception as exc:
        checks.append(_check("P3-02", "provider config matrix", "BLOCKED",
                             "config matrix", 1, repr(exc)[:300]))

    # P3-03: prompt/schema pinning.
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
        checks.append(_check("P3-03", "prompt/schema pinning", "PASS",
                             "version constants present", 0, "pinned"))
    except Exception as exc:
        checks.append(_check("P3-03", "prompt/schema pinning", "FAIL",
                             "version constants present", 1, repr(exc)[:300]))

    # P3-04: /providers endpoint (auth + shape, no secrets).
    try:
        import tests.asgi_harness as _h
        from app.auth.pin import hash_pin
        from app.config import Settings as _S, override_settings
        from app.main import create_app
        from app.storage import database as _db
        with tempfile.TemporaryDirectory() as tmp:
            settings = _S(db_path=f"{tmp}/g.db", blob_dir=f"{tmp}/b",
                          pin_hash=hash_pin("gate-pin-1234"))
            _db.upgrade(settings)
            override_settings(settings)
            try:
                client = _h.ASGIClient(create_app())
                denied = client.get("/api/v1/providers")
                login = client.post("/api/v1/auth/login",
                                    json={"pin": "gate-pin-1234"})
                csrf = login.json()["csrf_token"]
                client.headers["X-CSRF-Token"] = csrf
                allowed = client.get("/api/v1/providers")
            finally:
                override_settings(None)
        body = allowed.json()
        tasks = [entry["task"] for entry in body.get("providers", [])]
        ok = (denied.status_code == 401 and allowed.status_code == 200
              and tasks == ["invoice_extraction", "transcription",
                            "segmentation"]
              and "MODEL_API_KEY" not in allowed.text)
        checks.append(_check("P3-04", "providers endpoint",
                             "PASS" if ok else "FAIL",
                             "GET /api/v1/providers", allowed.status_code,
                             allowed.text[:300]))
    except Exception as exc:
        checks.append(_check("P3-04", "providers endpoint", "BLOCKED",
                             "harness providers", 1, repr(exc)[:300]))

    # P3-05..P3-08: provider test suites.
    pytest_check("P3-05", "provider contract suites", ["tests/providers"])
    pytest_check("P3-06", "provider pipeline integration",
                 ["tests/integration/test_providers_pipeline.py"])
    pytest_check("P3-07", "provider injection adversarial",
                 ["tests/adversarial/test_provider_injection.py"])
    pytest_check("P3-08", "providers api", ["tests/api/test_providers_api.py"])

    # P3-09: Phase 2 strict regression (full prior gate).
    code, output = _run([python, "scripts/phase2_check.py", "--strict"],
                        root, timeout=1200)
    checks.append(_check("P3-09", "phase 2 strict regression",
                         "PASS" if code == 0 and "READY" in output else "FAIL",
                         "phase2_check.py --strict", code, output[-600:]))

    # P3-10: secret hygiene.
    code, output = _run([python, "scripts/check_secret_hygiene.py"], root)
    checks.append(_check("P3-10", "secret hygiene",
                         "PASS" if code == 0 else "FAIL",
                         "check_secret_hygiene.py", code, output[-600:]))

    # P3-11: lint.
    code, output = _run([python, "-m", "ruff", "check", "scripts", "tests",
                         "app"], root, timeout=120)
    checks.append(_check("P3-11", "ruff",
                         "PASS" if code == 0 else "FAIL",
                         "ruff check scripts tests app", code,
                         output[-600:]))

    # P3-12: docs presence.
    required_docs = ["docs/phase3/ARCHITECTURE_DISCOVERY.md",
                     "docs/phase3/CAPABILITY_MATRIX.md",
                     "docs/phase3/PROVIDERS.md",
                     "docs/phase3/EXTRACTION.md",
                     "docs/phase3/VOICE.md",
                     "docs/phase3/SAM.md",
                     "docs/phase3/PRIVACY.md",
                     "docs/phase3/EVALUATION.md",
                     "docs/phase3/LIMITATIONS.md"]
    missing_docs = [doc for doc in required_docs
                    if not (root / doc).is_file()]
    checks.append(_check("P3-12", "phase 3 docs",
                         "PASS" if not missing_docs else "FAIL",
                         "docs inventory", 0 if not missing_docs else 1,
                         f"missing={missing_docs}" if missing_docs else
                         "all present"))

    # P3-13: offline eval runs green (no false-ALLOW).
    code, output = _run([python, "scripts/phase3_eval.py"], root, timeout=900)
    checks.append(_check("P3-13", "offline evaluation",
                         "PASS" if code == 0 else "FAIL",
                         "phase3_eval.py", code, output[-600:]))

    # P3-14: live smoke defaults to preflight-only (no live calls here).
    code, output = _run([python, "scripts/smoke_phase3.py"], root, timeout=300)
    checks.append(_check(
        "P3-14", "live smoke safe by default",
        "PASS" if code == 0 and "no live request" in output.lower() else "FAIL",
        "smoke_phase3.py (preflight)", code, output[-600:]))

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
    atomic_write_json(out_dir / "phase3_report.json", report)
    (out_dir / "phase3_report.md").write_text(_markdown(report),
                                              encoding="utf-8")

    print(f"Phase 3 gate: {verdict} "
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
    lines = ["# Airlock Phase 3 gate report", "",
             f"Verdict: **{report['verdict']}**", "",
             f"Generated: {report['timestamp_utc']}  ",
             f"Tool: {report['tool_version']}  ",
             f"Python: {report['python']}  ",
             f"Commit: {report['git_commit']}", "",
             "| Check | Name | Status |", "|---|---|---|"]
    for check in report["checks"]:
        lines.append(f"| {check['check_id']} | {check['name']} | "
                     f"{check['status']} |")
    lines += ["", "Details: `phase3_report.json` (same directory).",
              "Live provider status is classified by `smoke_phase3.py`, "
              "never by this gate.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
