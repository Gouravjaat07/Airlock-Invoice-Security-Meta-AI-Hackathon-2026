"""Phase 5 evaluation: deterministic pipeline + extraction scoring.

Offline (default, no network):
  1. Runs `scripts/phase3_eval.py` for verdict match + false-ALLOW
     evidence (subprocess, parsed, never edited).
  2. Validates every canonical fixture extraction payload against
     `InvoiceExtraction` + arithmetic reconcile (schema-drift signal).

Live model-quality scoring is opt-in only:
  `phase5_eval.py --live --allow-billable [--reader-provider spark]
  [--max-calls N]`
runs the REAL reader adapter against the REAL provider over synthetic
fixture artifacts and scores normalized field accuracy against the
fixture ground truth. Without both flags the live part is NOT_TESTED
and no network call is made.

Usage: python scripts/phase5_eval.py [--output-dir results/phase5/eval]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    TOOL_VERSION,
    atomic_write_json,
    find_project_root,
    utc_now_iso,
)
from _smoke_common import (  # noqa: E402
    live_flag_misuse,
    live_requested_and_confirmed,
)

MAX_CALLS_CAP = 10
TEXT_FIELDS = ("vendor_name", "invoice_number", "currency",
               "bank_reference", "po_reference")
DATE_FIELDS = ("issue_date", "due_date")
MONEY_FIELDS = ("subtotal", "tax", "total")


def _norm_text(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _norm_date(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "").strip()


def _norm_money(value: object) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except Exception:
        return None


def score_extraction(predicted: dict, expected: dict) -> dict:
    """Normalized field comparison (strict money, casefold text)."""
    fields: dict[str, bool] = {}
    for name in TEXT_FIELDS:
        fields[name] = (_norm_text(predicted.get(name))
                        == _norm_text(expected.get(name)))
    for name in DATE_FIELDS:
        fields[name] = (_norm_date(predicted.get(name))
                        == _norm_date(expected.get(name)))
    for name in MONEY_FIELDS:
        got, want = (_norm_money(predicted.get(name)),
                     _norm_money(expected.get(name)))
        fields[name] = got is not None and got == want
    pred_lines = predicted.get("line_items") or []
    exp_lines = expected.get("line_items") or []
    fields["line_item_count"] = len(pred_lines) == len(exp_lines)
    line_hits = 0
    for pred, exp in zip(pred_lines, exp_lines):
        if not isinstance(pred, dict) or not isinstance(exp, dict):
            continue
        got_qty, want_qty = (_norm_money(pred.get("quantity")),
                             _norm_money(exp.get("quantity")))
        got_price, want_price = (_norm_money(pred.get("unit_price")),
                                 _norm_money(exp.get("unit_price")))
        if (_norm_text(pred.get("description"))
                == _norm_text(exp.get("description"))
                and got_qty is not None and got_qty == want_qty
                and got_price is not None and got_price == want_price):
            line_hits += 1
    fields["line_items_exact"] = (
        bool(exp_lines) and line_hits == len(exp_lines)
        and len(pred_lines) == len(exp_lines))
    total = len(fields)
    hits = sum(1 for hit in fields.values() if hit)
    return {"fields": fields, "hits": hits, "total": total,
            "accuracy": hits / total if total else None,
            "complete_match": hits == total}


def _run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, cwd=str(cwd))
    except subprocess.TimeoutExpired:
        return 99, "TIMEOUT"
    except OSError as exc:
        return 98, f"SPAWN FAILED: {exc}"
    return completed.returncode, (completed.stdout + completed.stderr)[-2000:]


def _offline_schema_part(root: Path) -> dict:
    """Validate canonical fixture payloads against the live schema."""
    sys.path.insert(0, str(root))
    from app.pipeline.validate import validate_extraction
    scenarios_dir = root / "fixtures" / "scenarios"
    checked = passed = 0
    failures: list[str] = []
    excluded: list[str] = []
    for path in sorted(scenarios_dir.glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if spec.get("variant") == "failure":
            excluded.append(path.stem)
            continue  # failure-path fixture: invalid payloads are
            # legitimate test inputs, covered by the verdict part
        payload = spec.get("extraction")
        if not isinstance(payload, dict):
            continue  # failure fixtures carry no valid payload
        checked += 1
        try:
            validate_extraction(payload)
            passed += 1
        except Exception:
            failures.append(path.stem)
    return {"checked": checked, "passed": passed, "failures": failures,
            "excluded_failure_variant": excluded}


def _live_reader_part(root: Path, provider: str, budget: int) -> dict:
    """Score the REAL adapter against the REAL provider (synthetic only)."""
    sys.path.insert(0, str(root))
    from app.config import load_settings
    from app.core.errors import AppError
    from app.evaluation.fixtures import safe_artifact_path
    from app.providers.registry import resolve_reader

    try:
        settings = load_settings()
    except AppError as exc:
        return {"status": "BLOCKED", "reason": f"config: {exc}",
                "results": []}
    if provider == "spark" and not settings.model_api_key:
        return {"status": "BLOCKED", "reason": "MODEL_API_KEY not set",
                "results": []}
    if provider == "spark-open" and not settings.baseten_api_key:
        return {"status": "BLOCKED", "reason": "BASETEN_API_KEY not set",
                "results": []}
    import dataclasses
    from app.config import _validate_safety
    settings = dataclasses.replace(settings, reader_provider=provider)
    try:
        _validate_safety(settings)
        reader = resolve_reader(settings)
    except AppError as exc:
        return {"status": "BLOCKED", "reason": str(exc)[:200],
                "results": []}

    scenarios_dir = root / "fixtures" / "scenarios"
    results: list[dict] = []
    calls_used = 0
    for path in sorted(scenarios_dir.glob("*.json")):
        if calls_used >= budget:
            break
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = path.stem
        expected = spec.get("extraction")
        invoice_rel = spec.get("invoice_artifact")
        if not isinstance(expected, dict) or not invoice_rel:
            continue
        artifact = safe_artifact_path(root / "fixtures",
                                     str(invoice_rel))
        if artifact is None:
            continue
        started = time.monotonic()
        try:
            outcome = reader.read(artifact.read_bytes())
            latency_ms = int((time.monotonic() - started) * 1000)
            calls_used += 1
            score = score_extraction(outcome.payload, expected)
            results.append({
                "scenario": name, "status": "SCORED",
                "request_id": outcome.request_id,
                "model_id": outcome.model_id,
                "latency_ms": latency_ms,
                "score": score,
                "warnings": [str(w)[:120] for w in outcome.warnings],
            })
        except AppError as exc:
            calls_used += 1
            results.append({
                "scenario": name, "status": "ADAPTER_ERROR",
                "error_code": exc.code, "note": str(exc)[:200],
                "latency_ms": int((time.monotonic() - started) * 1000),
            })
        except Exception as exc:  # noqa: BLE001 - record, never leak
            calls_used += 1
            results.append({
                "scenario": name, "status": "ERROR",
                "note": type(exc).__name__,
                "latency_ms": int((time.monotonic() - started) * 1000),
            })
    scored = [r for r in results if r["status"] == "SCORED"]
    accuracies = [r["score"]["accuracy"] for r in scored
                  if r["score"]["accuracy"] is not None]
    return {
        "status": "COMPLETED",
        "provider": provider,
        "calls_used": calls_used,
        "scored": len(scored),
        "mean_accuracy": (sum(accuracies) / len(accuracies)
                          if accuracies else None),
        "complete_matches": sum(1 for r in scored
                                if r["score"]["complete_match"]),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 5 evaluation.")
    parser.add_argument("--output-dir", default="results/phase5/eval")
    parser.add_argument("--live", action="store_true",
                        help="Score the real adapter against the real "
                             "provider (requires --allow-billable).")
    parser.add_argument("--allow-billable", dest="confirm_external_call",
                        action="store_true",
                        help="Confirm a possibly billable live eval.")
    parser.add_argument("--reader-provider", default="spark",
                        choices=["spark", "spark-open", "glimmer"])
    parser.add_argument("--max-calls", type=int, default=3)
    args = parser.parse_args(argv)

    misuse = live_flag_misuse(args)
    if misuse:
        print(f"ERROR: {misuse}", file=sys.stderr)
        return 2
    live = live_requested_and_confirmed(args)
    budget = max(1, min(int(args.max_calls), MAX_CALLS_CAP))

    root = find_project_root() or Path.cwd()
    python = sys.executable

    # Part 1: deterministic verdict eval (authoritative subprocess).
    with tempfile.TemporaryDirectory() as tmp:
        code, output = _run(
            [python, "scripts/phase3_eval.py", "--output-dir", tmp],
            root, timeout=900)
        if code != 0:
            print(output[-800:], file=sys.stderr)
        phase3: dict = {}
        report_path = Path(tmp) / "phase3_eval.json"
        if report_path.is_file():
            phase3 = json.loads(report_path.read_text(encoding="utf-8"))
    verdict_part = {
        "exit_code": code,
        "matched": phase3.get("matched"),
        "total": phase3.get("total"),
        "accuracy": phase3.get("accuracy"),
        "per_verdict": phase3.get("per_verdict"),
        "adversarial_false_allow": phase3.get("adversarial_false_allow"),
        "elapsed_ms": phase3.get("elapsed_ms"),
    }

    # Part 2: offline schema validation over canonical fixtures.
    schema_part = _offline_schema_part(root)

    # Part 3: live model-quality scoring (opt-in only).
    if live:
        print(f"Live eval confirmed: up to {budget} synthetic "
              f"reader calls via {args.reader_provider} (no retries "
              "beyond adapter policy)...")
        live_part: dict = _live_reader_part(root, args.reader_provider,
                                            budget)
    else:
        live_part = {"status": "NOT_TESTED",
                     "reason": "re-run with --live --allow-billable",
                     "results": []}

    report = {
        "tool_version": TOOL_VERSION,
        "timestamp_utc": utc_now_iso(),
        "scope": "offline pipeline behavior (authoritative) + "
                 "opt-in live extraction scoring on synthetic fixtures",
        "verdict_eval": verdict_part,
        "schema_eval": schema_part,
        "live_reader_eval": live_part,
    }
    out_dir = root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "phase5_eval.json", report)
    (out_dir / "phase5_eval.md").write_text(_markdown(report),
                                            encoding="utf-8")

    false_allow = verdict_part.get("adversarial_false_allow") or []
    matched = verdict_part.get("matched")
    total = verdict_part.get("total")
    print(f"Phase 5 eval: verdict {matched}/{total} matched, "
          f"false-ALLOW={len(false_allow)}, schema "
          f"{schema_part['passed']}/{schema_part['checked']}, "
          f"live={live_part['status']}")
    if false_allow:
        print(f"  FALSE ALLOW: {false_allow}")
        return 1
    if code != 0 or not total or matched != total:
        return 1
    if schema_part["failures"]:
        print(f"  SCHEMA FAILURES: {schema_part['failures']}")
        return 1
    return 0


def _markdown(report: dict) -> str:
    verdict = report["verdict_eval"]
    schema = report["schema_eval"]
    live = report["live_reader_eval"]
    lines = ["# Phase 5 evaluation", "",
             f"Generated: {report['timestamp_utc']}", "",
             "## Verdict behavior (offline, authoritative)", "",
             f"Matched: **{verdict.get('matched')}/{verdict.get('total')}**  ",
             f"False-ALLOW: **"
             f"{len(verdict.get('adversarial_false_allow') or [])}**", "",
             "## Fixture schema validation (offline)", "",
             f"Valid payloads: **{schema['passed']}/{schema['checked']}**"]
    if schema["failures"]:
        lines.append(f"Failures: {', '.join(schema['failures'])}")
    if schema.get("excluded_failure_variant"):
        lines.append("Excluded (failure-variant fixtures, covered by "
                     "verdict part): "
                     + ", ".join(schema["excluded_failure_variant"]))
    lines += ["", "## Live reader scoring (synthetic, opt-in)", "",
              f"Status: **{live['status']}**"]
    if live["status"] == "COMPLETED":
        lines.append(
            f"Provider {live.get('provider')}: scored={live.get('scored')} "
            f"mean_accuracy={live.get('mean_accuracy')} "
            f"complete={live.get('complete_matches')} "
            f"calls={live.get('calls_used')}")
    else:
        lines.append(str(live.get("reason", "")))
    lines += ["", "Details: `phase5_eval.json` (same directory).", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
