"""Phase 5 benchmark: reproducible offline latency + reliability numbers.

Offline (default, no network): runs the REAL pipeline (isolated temp
DB, fixture reader, seeded synthetic registry) over rotating canonical
scenarios and reports per-case end-to-end latency (min/P50/P95/max),
verdict distribution, audit volume, and throughput. Deterministic
inputs; timings naturally vary by machine (recorded, never asserted).

Live provider latency is opt-in only:
  `phase5_benchmark.py --live --allow-billable`
reuses `smoke_phase3` (one synthetic micro-request per provider, no
retries) and folds each provider's observed latency/status into the
report. Without both flags the live part is NOT_TESTED.

Outputs: `benchmark_summary.json` + `benchmark_report.md`. No secrets,
no raw document bytes, and no usage/cost fabrication: usage appears
only when a provider reports it.

Usage: python scripts/phase5_benchmark.py [--cases 5] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    TOOL_VERSION,
    atomic_write_json,
    find_project_root,
    git_commit,
    utc_now_iso,
)
from _smoke_common import (  # noqa: E402
    live_flag_misuse,
    live_requested_and_confirmed,
)

LIVE_PROVIDERS = ("meta-spark", "meta-voice", "meta-sam", "baseten")


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def _stats(values: list[float]) -> dict:
    return {
        "count": len(values),
        "min_ms": min(values) if values else None,
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": max(values) if values else None,
        "mean_ms": (sum(values) / len(values)) if values else None,
    }


def _seed_registry(root: Path, conn) -> None:
    import json as _json
    from app.core.clock import SYSTEM_CLOCK
    from app.core.security import bank_fingerprint
    from app.domain.vendors import normalize_vendor_name
    from app.storage.database import transaction
    from app.storage.repositories import (
        PurchaseOrderRepository,
        VendorRepository,
    )
    data = _json.loads(
        (root / "registry" / "synthetic_vendors.json").read_text())
    now = SYSTEM_CLOCK.now().isoformat()
    with transaction(conn):
        for entry in data["vendors"]:
            VendorRepository().create(
                conn, vendor_id=entry["vendor_id"], name=entry["name"],
                name_norm=normalize_vendor_name(entry["name"]),
                bank_fp=bank_fingerprint(entry["bank_reference"],
                                         b"bench-key"),
                catalogue_json=_json.dumps(entry.get("catalogue", [])),
                cap=entry.get("per_invoice_cap"), now=now)
        for entry in data["purchase_orders"]:
            PurchaseOrderRepository().create(
                conn, po_id=entry["po_id"], vendor_id=entry["vendor_id"],
                po_reference=entry["po_reference"],
                currency=entry["currency"],
                original=entry["original_amount"],
                remaining=entry["remaining_amount"])


def _offline_part(root: Path, cases: int) -> dict:
    sys.path.insert(0, str(root))
    from app.config import Settings
    from app.evaluation import fixtures as eval_fixtures
    from app.evaluation import policy_eval
    from app.storage import database
    from app.storage.artifacts import LocalBlobStore

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            bank_hash_key=b"bench-key",
            db_path=f"{tmp}/bench.db", blob_dir=f"{tmp}/blobs",
            environment="test", fixture_reader_enabled=True,
            fixtures_dir=str(root / "fixtures"), enable_eval_api=True)
        database.upgrade(settings)
        conn = database.connect(settings)
        try:
            _seed_registry(root, conn)
            store = LocalBlobStore(settings)
            store.ensure_root()
            names = eval_fixtures.list_scenarios(settings)
            # Skip declared failure-injection scenarios: they exercise
            # error paths, not steady-state latency.
            steady = [n for n in names if "reader_error"
                      not in (root / "fixtures" / "scenarios" /
                              f"{n}.json").read_text(encoding="utf-8")]
            if not steady:
                steady = names
            latencies: list[float] = []
            verdicts: dict[str, int] = {}
            per_case: list[dict] = []
            started_all = time.monotonic()
            for index in range(cases):
                name = steady[index % len(steady)]
                started = time.monotonic()
                outcome = policy_eval.run_scenarios(
                    conn, settings, store, [name])
                elapsed_ms = (time.monotonic() - started) * 1000
                latencies.append(elapsed_ms)
                actual = outcome["results"][0].get("actual")
                verdicts[actual] = verdicts.get(actual, 0) + 1
                per_case.append({"case": index + 1, "scenario": name,
                                 "latency_ms": round(elapsed_ms, 2),
                                 "verdict": actual})
            total_s = time.monotonic() - started_all
            audit_events = conn.execute(
                "SELECT COUNT(*) FROM audit_events").fetchone()[0]
        finally:
            conn.close()

    return {
        "cases": cases,
        "latency_ms": _stats(latencies),
        "verdicts": verdicts,
        "audit_events": audit_events,
        "throughput_cases_per_s": (cases / total_s) if total_s else None,
        "per_case": per_case,
    }


def _live_part(env) -> dict:
    import smoke_phase3 as smoke
    entries: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in LIVE_PROVIDERS:
            code = smoke.main(
                ["--live", "--allow-billable", "--provider", name,
                 "--max-calls", "1", "--results-dir", tmp], env=env)
            saved = sorted(glob.glob(str(Path(tmp) / "smoke-*.json")))
            detail: dict = {"provider": name, "exit_code": code,
                            "status": "NOT_TESTED"}
            if saved:
                record = json.loads(Path(saved[-1]).read_text(
                    encoding="utf-8"))
                for entry in record.get("providers", []):
                    if entry.get("provider") == name:
                        detail.update({
                            "status": entry.get("status"),
                            "http_status": entry.get("http_status"),
                            "latency_ms": entry.get("latency_ms"),
                            "error_category": entry.get("error_category"),
                            "notes": entry.get("notes"),
                        })
            entries.append(detail)
    return {"providers": entries,
            "calls_used": sum(1 for e in entries
                              if e["status"] in ("PASS", "FAIL"))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 5 benchmark.")
    parser.add_argument("--cases", type=int, default=5,
                        help="Offline pipeline cases to time (>=1).")
    parser.add_argument("--output-dir", default="results/phase5")
    parser.add_argument("--live", action="store_true",
                        help="Add one live micro-request per provider "
                             "(requires --allow-billable).")
    parser.add_argument("--allow-billable", dest="confirm_external_call",
                        action="store_true",
                        help="Confirm possibly billable live requests.")
    args = parser.parse_args(argv)

    misuse = live_flag_misuse(args)
    if misuse:
        print(f"ERROR: {misuse}", file=sys.stderr)
        return 2
    live = live_requested_and_confirmed(args)
    cases = max(1, int(args.cases))

    root = find_project_root() or Path.cwd()
    offline = _offline_part(root, cases)
    if live:
        print("Live benchmark confirmed: one synthetic micro-request "
              "per provider (no retries)...")
        live_result: dict = _live_part(os.environ)
    else:
        live_result = {"status": "NOT_TESTED",
                       "reason": "re-run with --live --allow-billable",
                       "providers": []}

    summary = {
        "tool_version": TOOL_VERSION,
        "timestamp_utc": utc_now_iso(),
        "git_commit": git_commit(root),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "environment": "offline pipeline (fixture reader, temp DB); "
                       "timings are machine-specific observations",
        "offline": offline,
        "live": live_result,
        "usage_and_cost": "not measured offline; live usage appears in "
                          "provider records only when reported by the "
                          "provider (never estimated here)",
    }
    out_dir = root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "benchmark_summary.json", summary)
    (out_dir / "benchmark_report.md").write_text(_markdown(summary),
                                                encoding="utf-8")
    latency = offline["latency_ms"]
    print(f"Benchmark: {cases} cases, "
          f"p50={latency['p50_ms']:.1f}ms "
          f"p95={latency['p95_ms']:.1f}ms "
          f"max={latency['max_ms']:.1f}ms, live={live_result.get('status', 'measured')}")
    return 0


def _markdown(summary: dict) -> str:
    offline = summary["offline"]
    latency = offline["latency_ms"]
    lines = ["# Phase 5 benchmark report", "",
             f"Generated: {summary['timestamp_utc']}  ",
             f"Tool: {summary['tool_version']}  ",
             f"Commit: {summary.get('git_commit') or 'unknown'}  ",
             f"Python: {summary['python']} on {summary['platform']}", "",
             "## Offline pipeline (deterministic inputs)", "",
             f"Cases: **{offline['cases']}**  ",
             f"Throughput: {(offline['throughput_cases_per_s'] or 0):.2f} "
             "cases/s  ",
             f"Audit events: {offline['audit_events']}", "",
             "| Metric | ms |", "|---|---|",
             f"| min | {latency['min_ms']:.1f} |",
             f"| p50 | {latency['p50_ms']:.1f} |",
             f"| p95 | {latency['p95_ms']:.1f} |",
             f"| max | {latency['max_ms']:.1f} |",
             f"| mean | {latency['mean_ms']:.1f} |", "",
             f"Verdicts: {json.dumps(offline['verdicts'])}", "",
             "## Live provider latency (opt-in)", ""]
    live = summary["live"]
    if live.get("providers"):
        lines += ["| Provider | Status | HTTP | Latency ms |",
                  "|---|---|---|---|"]
        for entry in live["providers"]:
            lines.append(f"| {entry['provider']} | {entry['status']} | "
                         f"{entry.get('http_status')} | "
                         f"{entry.get('latency_ms')} |")
    else:
        lines.append(f"Status: **{live.get('status')}** — "
                     f"{live.get('reason', '')}")
    lines += ["", "## Usage and cost", "",
              str(summary["usage_and_cost"]), "",
              "Timings are observations from this machine, not targets. "
              "Reproduce with `python scripts/phase5_benchmark.py "
              "[--cases N]`.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
