"""Phase 3 offline evaluation: verdict confusion over synthetic scenarios.

Runs the REAL pipeline (isolated temp DB, fixture reader, seeded
synthetic registry) over every scenario in fixtures/scenarios and
reports verdict match rates, per-verdict precision/recall, rule
triggers, and the adversarial false-ALLOW rate (must be zero).

This measures deterministic pipeline behavior on synthetic ground
truth. It does NOT measure live model quality — no provider is called.
Model-quality eval stays BLOCKED until opt-in live runs exist.

Usage: python scripts/phase3_eval.py [--output-dir results/phase3/eval]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    TOOL_VERSION,
    atomic_write_json,
    find_project_root,
    utc_now_iso,
)


def is_false_allow(spec: dict, actual: str | None) -> bool:
    """An attack sample counts as false-ALLOW only when its documented
    ground truth requires non-allowance (DENY/ESCALATE) yet the pipeline
    allowed it. Attack samples whose ground truth is ALLOW_PROPOSAL
    prove injection-inertness (valid values decide; hostile text stays
    data) and must NOT count: rejecting a financially valid invoice
    for containing suspicious words would be the defect, not the
    defense.
    """
    return (bool(spec.get("attack_type"))
            and actual == "ALLOW_PROPOSAL"
            and spec.get("expected_verdict") in ("DENY", "ESCALATE"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3 offline evaluation.")
    parser.add_argument("--output-dir", default="results/phase3/eval")
    args = parser.parse_args(argv)

    root = find_project_root() or Path.cwd()
    sys.path.insert(0, str(root))
    from app.config import Settings
    from app.evaluation import fixtures as eval_fixtures
    from app.evaluation import policy_eval
    from app.storage import database
    from app.storage.artifacts import LocalBlobStore

    with tempfile.TemporaryDirectory() as tmp:
        # Synthetic eval-only bank key (isolated temp DB, destroyed after).
        settings = Settings(
            bank_hash_key=b"eval-key",
            db_path=f"{tmp}/eval.db", blob_dir=f"{tmp}/blobs",
            environment="test", fixture_reader_enabled=True,
            fixtures_dir=str(root / "fixtures"), enable_eval_api=True)
        database.upgrade(settings)
        conn = database.connect(settings)
        try:
            import json as _json
            from app.core.clock import SYSTEM_CLOCK
            from app.core.security import bank_fingerprint
            from app.domain.vendors import normalize_vendor_name
            from app.storage.database import transaction
            from app.storage.repositories import (
                PurchaseOrderRepository,
                VendorRepository,
            )
            data = _json.loads((root / "registry" / "synthetic_vendors.json").read_text())
            now = SYSTEM_CLOCK.now().isoformat()
            with transaction(conn):
                for entry in data["vendors"]:
                    VendorRepository().create(
                        conn, vendor_id=entry["vendor_id"],
                        name=entry["name"],
                        name_norm=normalize_vendor_name(entry["name"]),
                        bank_fp=bank_fingerprint(entry["bank_reference"], b"eval-key"),
                        catalogue_json=_json.dumps(entry.get("catalogue", [])),
                        cap=entry.get("per_invoice_cap"), now=now)
                for entry in data["purchase_orders"]:
                    PurchaseOrderRepository().create(
                        conn, po_id=entry["po_id"],
                        vendor_id=entry["vendor_id"],
                        po_reference=entry["po_reference"],
                        currency=entry["currency"],
                        original=entry["original_amount"],
                        remaining=entry["remaining_amount"])
            store = LocalBlobStore(settings)
            store.ensure_root()
            names = eval_fixtures.list_scenarios(settings)
            started = time.monotonic()
            outcome = policy_eval.run_scenarios(conn, settings, store, names)
            elapsed_ms = int((time.monotonic() - started) * 1000)
        finally:
            conn.close()

    summary = outcome["summary"]
    results = outcome["results"]
    verdicts = ("ALLOW_PROPOSAL", "ESCALATE", "DENY")
    confusion = {actual: {expected: 0 for expected in verdicts}
                 for actual in (*verdicts, "ERROR")}
    adversarial_allow = []
    rule_hits: dict[str, int] = {}
    for item in results:
        actual = item["actual"] if item["actual"] in verdicts else "ERROR"
        expected = item["expected"] if item["expected"] in verdicts else "ERROR"
        if expected in verdicts:
            confusion[actual][expected] += 1
        for rule_id in item.get("rule_ids", []):
            rule_hits[rule_id] = rule_hits.get(rule_id, 0) + 1
        spec = json.loads((root / "fixtures" / "scenarios" /
                           f"{item['scenario']}.json").read_text())
        if is_false_allow(spec, item["actual"]):
            adversarial_allow.append(item["scenario"])

    per_verdict = {}
    for verdict in verdicts:
        true_pos = confusion[verdict][verdict]
        predicted = sum(confusion[verdict].values())
        actual_total = sum(confusion[actual][verdict] for actual in confusion)
        per_verdict[verdict] = {
            "precision": (true_pos / predicted) if predicted else None,
            "recall": (true_pos / actual_total) if actual_total else None,
            "support": actual_total,
        }

    report = {
        "tool_version": TOOL_VERSION,
        "timestamp_utc": utc_now_iso(),
        "scope": "offline pipeline behavior on synthetic scenarios (no providers called)",
        "total": summary["total"],
        "matched": summary["matched"],
        "accuracy": (summary["matched"] / summary["total"]
                     if summary["total"] else None),
        "per_verdict": per_verdict,
        "confusion_actual_vs_expected": confusion,
        "rule_triggers": dict(sorted(rule_hits.items())),
        "adversarial_scenarios": sum(
            1 for item in results
            if json.loads((root / "fixtures" / "scenarios" /
                           f"{item['scenario']}.json").read_text()).get("attack_type")),
        "adversarial_false_allow": adversarial_allow,
        "elapsed_ms": elapsed_ms,
        "results": results,
    }
    out_dir = root / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "phase3_eval.json", report)
    lines = ["# Phase 3 offline evaluation", "",
             f"Matched: **{summary['matched']}/{summary['total']}**  ",
             f"Adversarial false-ALLOW: **{len(adversarial_allow)}**  ",
             f"Elapsed: {elapsed_ms} ms", "",
             "## Per-verdict", ""]
    for verdict in verdicts:
        stats = per_verdict[verdict]
        lines.append(f"- {verdict}: precision={stats['precision']} "
                     f"recall={stats['recall']} support={stats['support']}")
    lines += ["", "Details: `phase3_eval.json` (same directory).", ""]
    (out_dir / "phase3_eval.md").write_text("\n".join(lines),
                                            encoding="utf-8")
    print(f"Phase 3 eval: {summary['matched']}/{summary['total']} matched, "
          f"false-ALLOW={len(adversarial_allow)}")
    if adversarial_allow:
        print(f"  FALSE ALLOW: {adversarial_allow}")
        return 1
    return 0 if summary["matched"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
