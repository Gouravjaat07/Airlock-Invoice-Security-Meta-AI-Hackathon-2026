"""Top-level Phase 1 check for Airlock.

Default (offline) mode runs safe local checks only: no external API calls,
no package installs, no model downloads.

Live mode (`--live --allow-billable`, both required) additionally invokes
the provider smoke scripts as subprocesses, each sending at most its own
minimal synthetic request. Partial live flags exit 2 without running
anything. Cost/usage implications are printed before any live subprocess
starts.

Sections:
  * environment      — dev machine + repo scaffold readiness
  * api_evidence     — model entitlement evidence (honest unknowns)
  * local_inference  — Glimmer hardware feasibility
  * research         — manifest schema + preregistration readiness
  * security         — configuration + secret hygiene
  * documentation    — Phase 1 docs presence
  * live_integrations — only in live mode (subprocess smoke results)

Overall gate: PASS | PARTIAL | BLOCKED (see docs/phase1/PHASE1_REPORT.md).
Exit codes: 0 normally unless BLOCKED; with --strict, 0 only for PASS;
2 for flag misuse or argparse errors; 1 for report-write failures.

Status vocabulary:
  PASS         requirement tested and satisfied
  FAIL         test executed and the requirement was not satisfied
  PARTIAL      some evidence exists but a material condition is incomplete
  BLOCKED      overall gate: at least one section FAILED
  NOT_TESTED   test was not executed (never counts as PASS)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_environment as env_mod  # noqa: E402
import check_hardware as hw_mod  # noqa: E402
import check_secret_hygiene as hygiene_mod  # noqa: E402
import validate_config as config_mod  # noqa: E402
import validate_manifest as manifest_mod  # noqa: E402
from _common import (  # noqa: E402
    TOOL_VERSION, atomic_write_json, default_audit_root,
    provenance_envelope,
)
from _smoke_common import (  # noqa: E402
    live_flag_misuse, live_requested_and_confirmed,
)

OVERALL_PASS = "PASS"
OVERALL_PARTIAL = "PARTIAL"
OVERALL_BLOCKED = "BLOCKED"

DOC_PATHS = [
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
    "docs/phase1/MANIFEST_MIGRATION_v2.md",
    "prereg/PREREGISTRATION.md",
    "eval/README.md",
]

# Statuses that count as locally verified evidence (from results/phase1 logs).
EVIDENCE_STATUSES = {"PASS", "VERIFIED_FROM_LOG"}

# Providers that must verify before api_evidence can PASS.
REQUIRED_COMPONENTS = ("meta-spark", "baseten-spark-open")

# Live subprocesses: (script, component). SAM/voice refuse by design until
# their schemas are verified; their honest NOT_TESTED is preserved.
LIVE_SMOKE_SCRIPTS = (
    ("smoke_meta.py", "meta-spark"),
    ("smoke_baseten.py", "baseten-spark-open"),
    ("smoke_sam.py", "sam-3.1"),
    ("smoke_voice.py", "voice-transcribe"),
)
LIVE_SMOKE_TIMEOUT_S = 180


def section(status: str, summary: str, details: Optional[list[str]] = None,
            data: Optional[dict] = None) -> dict:
    return {"status": status, "summary": summary,
            "details": details or [], "data": data or {}}


def check_documentation(root: Path) -> dict:
    missing = [rel for rel in DOC_PATHS if not (root / rel).is_file()]
    if missing:
        return section("FAIL", f"{len(missing)} required doc(s) missing",
                       [f"missing: {m}" for m in missing], {"missing": missing})
    return section("PASS", f"all {len(DOC_PATHS)} required docs present")


def check_research(root: Path) -> dict:
    details: list[str] = []
    data: dict = {}
    schema_path = root / "eval" / "manifest.schema.json"
    template_path = root / "eval" / "manifest.dev.template.json"
    prereg_path = root / "prereg" / "PREREGISTRATION.md"

    if not schema_path.is_file():
        return section("FAIL", "manifest schema missing",
                       ["missing: eval/manifest.schema.json"])
    try:
        schema_text = schema_path.read_text(encoding="utf-8")
        schema = json.loads(schema_text)
        assert isinstance(schema, dict) and schema.get("$schema", "").endswith("2020-12/schema")
        details.append("manifest schema is valid JSON declaring Draft 2020-12")
        data["schema_draft"] = schema.get("$schema")
    except (OSError, json.JSONDecodeError, AssertionError) as exc:
        return section("FAIL", f"manifest schema invalid: {exc}")

    if not template_path.is_file():
        return section("FAIL", "dev template missing",
                       ["missing: eval/manifest.dev.template.json"])
    errors, warnings, fatal = manifest_mod.validate_file(str(template_path))
    if fatal:
        return section("FAIL", f"template unreadable: {fatal}")
    assert errors is not None and warnings is not None
    if errors:
        return section("FAIL", f"template invalid ({len(errors)} error(s))", errors)
    details.append("dev template validates against the contract")
    for warning in warnings:
        details.append(f"template warning: {warning}")

    if not prereg_path.is_file():
        return section("FAIL", "preregistration missing",
                       details + ["missing: prereg/PREREGISTRATION.md"])
    details.append("preregistration present (designs + thresholds, no results)")
    data["template_warnings"] = warnings
    return section("PASS", "research reproducibility foundation ready", details, data)


def summarize_api_evidence(root: Path) -> dict:
    """Read local smoke records only. Never invent evidence.

    USER_REPORTED_TESTED (prior API-key testing reported by the user) is
    recorded honestly and never upgraded to verified without a local log.
    A FAIL record is a verified failure signal: the section FAILS so the
    release gate blocks until the integration is re-verified. PASS requires
    every required component (meta-spark, baseten-spark-open) verified;
    anything less is PARTIAL, never PASS.
    """
    results_dir = root / "results" / "phase1"
    records: list[dict] = []
    corrupt = 0
    if results_dir.is_dir():
        for path in sorted(results_dir.glob("smoke-*.json")):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                corrupt += 1
                continue
    verified = [r for r in records if r.get("status") in EVIDENCE_STATUSES]
    failed = [r for r in records if r.get("status") == "FAIL"]
    verified_components = sorted({str(r.get("component")) for r in verified if r.get("component")})
    failed_components = sorted({str(r.get("component")) for r in failed if r.get("component")})
    details = [
        "Prior user-reported API-key testing: USER_REPORTED_TESTED (reported complete; "
        "no status codes, model IDs, or response logs reproduced in this workspace).",
        f"Local smoke records found: {len(records)}; locally verified: {len(verified)}; "
        f"failed: {len(failed)}.",
    ]
    if corrupt:
        details.append(f"{corrupt} unreadable smoke record(s) skipped (corrupt or locked).")
    data = {"local_records": len(records), "locally_verified": len(verified),
            "failed": len(failed), "corrupt_records": corrupt,
            "user_reported": "USER_REPORTED_TESTED",
            "required_components": list(REQUIRED_COMPONENTS),
            "verified_components": verified_components,
            "failed_components": failed_components,
            "components": sorted({str(r.get("component")) for r in records if r.get("component")})}
    if failed:
        for record in failed:
            details.append(f"failed: {record.get('component')} "
                           f"[{record.get('status')}] error={record.get('error_category')}")
        return section("FAIL", "at least one integration failed verification locally",
                       details, data)
    if verified:
        for record in verified:
            details.append(f"verified: {record.get('component')} "
                           f"[{record.get('status')}] model={record.get('model_id')}")
    if all(component in verified_components for component in REQUIRED_COMPONENTS):
        return section("PASS", "required integrations verified from local logs",
                       details, data)
    details.append("No complete local verification. Live smoke tests are opt-in and "
                   "were NOT run by this check (default mode).")
    return section("PARTIAL", "API access user-reported but not reproduced locally",
                   details, data)


def check_security(root: Path) -> dict:
    _, issues = config_mod.load_config()
    errors = [i for i in issues if i.level == "ERROR"]
    config_detail = [f"[{i.level}] {i.code}: {i.message}" for i in issues]
    hygiene = hygiene_mod.run_hygiene_checks(root)
    details = config_detail + [
        f"secret hygiene: {len(hygiene['findings'])} finding(s) across "
        f"{hygiene['files_scanned']} files; "
        + ("ignore rules OK" if all(r["ok"] for r in hygiene["ignore_rules"])
           else "IGNORE-RULE PROBLEMS present"),
    ]
    data = {"config_errors": len(errors), "hygiene_findings": len(hygiene["findings"]),
            "hygiene_clean": hygiene["clean"]}
    if errors or not hygiene["clean"]:
        return section("FAIL", "security checks have failures", details, data)
    return section("PASS", "config valid; no secret-hygiene findings", details, data)


def default_live_runner(script_path: Path, component: str, json_path: Path) -> dict:
    """Run one smoke script live as a subprocess. Returns a sanitized outcome."""
    try:
        completed = subprocess.run(
            [sys.executable, str(script_path), "--live", "--allow-billable",
             "--json", str(json_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=LIVE_SMOKE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"component": component, "exit_code": None, "timed_out": True,
                "status": None,
                "notes": f"live smoke timed out after {LIVE_SMOKE_TIMEOUT_S}s"}
    except OSError as exc:
        return {"component": component, "exit_code": None, "timed_out": False,
                "status": None, "notes": f"live smoke could not start: {exc}"}
    status = None
    try:
        record = json.loads(Path(json_path).read_text(encoding="utf-8"))
        status = record.get("status")
    except (OSError, json.JSONDecodeError):
        status = None
    tail = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip().splitlines()
    notes = " | ".join(line.strip()[-160:] for line in tail[-3:] if line.strip())
    return {"component": component, "exit_code": completed.returncode,
            "timed_out": False, "status": status, "notes": notes[:400]}


def run_live_smokes(root: Path,
                    live_runner: Optional[Callable[[Path, str, Path], dict]] = None,
                    results_dir: Optional[Path] = None) -> dict:
    """Execute live provider smokes (explicit opt-in only) and aggregate."""
    runner = live_runner or default_live_runner
    scripts_dir = Path(__file__).resolve().parent
    out_dir = Path(results_dir) if results_dir else root / "results" / "phase1"
    outcomes: dict[str, dict] = {}
    details: list[str] = []
    for script_name, component in LIVE_SMOKE_SCRIPTS:
        script_path = scripts_dir / script_name
        json_path = out_dir / f"smoke-{component}-live.json"
        try:
            outcome = runner(script_path, component, json_path)
        except Exception as exc:  # noqa: BLE001 - runner failure is a finding
            outcome = {"component": component, "exit_code": None, "timed_out": False,
                       "status": None, "notes": f"live runner failed: {exc}"}
        outcomes[component] = outcome
        details.append(
            f"{component}: exit={outcome.get('exit_code')} "
            f"status={outcome.get('status')} {str(outcome.get('notes') or '')[:160]}".rstrip())
    data = {"components": outcomes,
            "required_components": list(REQUIRED_COMPONENTS)}
    failed = [c for c, o in outcomes.items() if o.get("status") == "FAIL"]
    required_ok = all(outcomes[c].get("status") == "PASS" for c in REQUIRED_COMPONENTS)
    if failed:
        return section("FAIL", f"live smoke failed for: {', '.join(failed)}",
                       details, data)
    if required_ok and all(o.get("status") == "PASS" for o in outcomes.values()):
        return section("PASS", "all live integrations verified", details, data)
    if required_ok:
        return section("PARTIAL", "required live integrations passed; "
                                  "conditional/optional remain untested", details, data)
    return section("PARTIAL", "live integrations not verified (see per-component notes)",
                   details, data)


def run_phase1_check(root: Optional[Path] = None, live: bool = False,
                     live_runner: Optional[Callable[[Path, str, Path], dict]] = None,
                     live_results_dir: Optional[Path] = None) -> dict:
    root = (root or default_audit_root()).resolve()
    report: dict = {"root": str(root), "sections": {}}

    env_results = env_mod.run_environment_checks()
    env_summary = env_mod.summarize(env_results)
    if env_summary.get("FAIL"):
        env_section = section("FAIL", "environment checks have failures",
                              [f"[{r['status']}] {r['name']}: {r['detail']}" for r in env_results],
                              {"summary": env_summary, "checks": env_results})
    elif env_summary.get("WARNING") or env_summary.get("NOT_AVAILABLE") \
            or env_summary.get("NOT_TESTED"):
        env_section = section("PARTIAL", "environment usable with warnings/gaps/"
                                         "untested checks",
                              [f"[{r['status']}] {r['name']}: {r['detail']}" for r in env_results],
                              {"summary": env_summary, "checks": env_results})
    else:
        env_section = section("PASS", "environment checks all pass",
                              [f"[{r['status']}] {r['name']}: {r['detail']}" for r in env_results],
                              {"summary": env_summary, "checks": env_results})
    report["sections"]["environment"] = env_section

    try:
        hw_report = hw_mod.run_hardware_audit()
    except Exception as exc:  # noqa: BLE001 - audit failure is a finding, not a crash
        hw_report = {"decision": "AUDIT_FAILED", "rationale": str(exc)}
    decision = hw_report.get("decision", "UNKNOWN")
    if decision == "LOCAL_GLIMMER_FEASIBLE":
        hw_section = section("PASS", "local Glimmer load experiment justified",
                             [hw_report.get("rationale", "")], hw_report)
    elif decision == "LOCAL_GLIMMER_REQUIRES_EXPERIMENT":
        hw_section = section("PARTIAL", "Glimmer feasibility inconclusive; experiment needed",
                             [hw_report.get("rationale", "")], hw_report)
    else:
        hw_section = section("PARTIAL", f"hardware finding: {decision} (fallback path documented)",
                             [hw_report.get("rationale", "")], hw_report)
    report["sections"]["local_inference"] = hw_section

    report["sections"]["api_evidence"] = summarize_api_evidence(root)
    report["sections"]["research"] = check_research(root)
    report["sections"]["security"] = check_security(root)
    report["sections"]["documentation"] = check_documentation(root)
    if live:
        report["sections"]["live_integrations"] = run_live_smokes(
            root, live_runner=live_runner, results_dir=live_results_dir)

    statuses = [s["status"] for s in report["sections"].values()]
    if "FAIL" in statuses:
        report["overall"] = OVERALL_BLOCKED
    elif "PARTIAL" in statuses:
        report["overall"] = OVERALL_PARTIAL
    else:
        report["overall"] = OVERALL_PASS

    prereqs: list[str] = []
    if report["sections"]["environment"]["status"] == "FAIL":
        prereqs.append("Fix failing environment checks (see section detail).")
    if report["sections"]["research"]["status"] == "FAIL":
        prereqs.append("Repair the manifest schema/template or preregistration.")
    if report["sections"]["security"]["status"] == "FAIL":
        prereqs.append("Resolve configuration errors or secret-hygiene findings.")
    if report["sections"]["documentation"]["status"] == "FAIL":
        prereqs.append("Create the missing Phase 1 documents.")
    if decision == "LOCAL_GLIMMER_UNAVAILABLE":
        prereqs.append("Reader decision: use the labelled hosted/mock fallback (see FALLBACK_DECISIONS.md).")
    if report["sections"]["api_evidence"]["status"] != "PASS":
        prereqs.append("API integrations remain unverified locally; run opt-in live smoke tests "
                       "before depending on any hosted model in Phase 2.")
    if live and report["sections"]["live_integrations"]["status"] != "PASS":
        prereqs.append("Live integrations were requested but are not fully verified; "
                       "see the live_integrations section.")
    report["prerequisites"] = prereqs
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Phase 1 check suite. Default is offline; "
                    "--live --allow-billable additionally runs provider live smokes.")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Write the structured report as JSON to this path.")
    parser.add_argument("--output-dir", dest="output_dir", default=None,
                        help="Write phase1_report.json plus environment.json and "
                             "hardware.json sidecars into this directory.")
    parser.add_argument("--strict", action="store_true",
                        help="Exit nonzero unless the overall gate is PASS.")
    parser.add_argument("--live", action="store_true",
                        help="Run provider live smokes (requires --allow-billable).")
    parser.add_argument("--allow-billable", "--confirm-external-call",
                        dest="confirm_external_call", action="store_true",
                        help="Confirm live, possibly billable calls. --allow-billable is "
                             "canonical; --confirm-external-call is a deprecated alias.")
    parser.add_argument("--verbose", action="store_true",
                        help="Print full section details.")
    parser.add_argument("--version", action="store_true",
                        help="Print the tool version and exit.")
    return parser


def main(argv: Optional[list[str]] = None,
         live_runner: Optional[Callable[[Path, str, Path], dict]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"phase1_check {TOOL_VERSION}")
        return 0

    misuse = live_flag_misuse(args)
    if misuse:
        print(f"ERROR: {misuse}", file=sys.stderr)
        return 2
    live = live_requested_and_confirmed(args)

    if live:
        print("Live mode confirmed: each provider smoke sends at most its own minimal "
              "synthetic request (single text prompt, tight output cap, strict timeout, "
              "no retries). This may consume API credit and is rate-limited by the "
              "provider. Synthetic content only; records are sanitized.")

    report = run_phase1_check(live=live, live_runner=live_runner,
                              live_results_dir=Path(args.output_dir) if args.output_dir else None)
    print(f"Airlock Phase 1 check (root: {report['root']})")
    for name, section_report in report["sections"].items():
        print(f"  [{section_report['status']}] {name}: {section_report['summary']}")
        details = section_report["details"] if args.verbose else section_report["details"][:12]
        width = 2000 if args.verbose else 220
        for detail in details:
            print(f"      - {detail[:width]}")
    print("  prerequisites / next actions:")
    for prereq in report["prerequisites"]:
        print(f"    * {prereq}")
    print(f"  OVERALL: {report['overall']}")

    exit_code = 0
    if args.strict:
        exit_code = 0 if report["overall"] == OVERALL_PASS else 1
    elif report["overall"] == OVERALL_BLOCKED:
        exit_code = 1
    report["provenance"] = provenance_envelope(
        "phase1_check", argv=argv, root=Path(report["root"]),
        extra={"overall": report["overall"], "strict": bool(args.strict),
               "live": bool(live), "exit_code": exit_code})

    try:
        if args.json_path:
            atomic_write_json(args.json_path, report)
            print(f"  JSON report written to {args.json_path}")
        if args.output_dir:
            out_dir = Path(args.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(out_dir / "phase1_report.json", report)
            env_data = report["sections"].get("environment", {}).get("data", {})
            atomic_write_json(out_dir / "environment.json", {
                "provenance": report["provenance"],
                "checks": env_data.get("checks", []),
                "summary": env_data.get("summary", {})})
            hw_data = report["sections"].get("local_inference", {}).get("data", {})
            atomic_write_json(out_dir / "hardware.json", {
                **(hw_data if isinstance(hw_data, dict) else {}),
                "provenance": report["provenance"]})
            print(f"  JSON reports written to {args.output_dir}")
    except OSError as exc:
        print(f"ERROR: cannot write JSON report: {exc}", file=sys.stderr)
        return 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
