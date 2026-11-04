"""Record a sanitized smoke-test outcome (Phase 1).

Validates fields, rejects credential-bearing values, and stores JSON history
under results/phase1/ without overwriting prior records by default.

USER_REPORTED_TESTED is never auto-upgraded: only a record backed by local
log evidence may carry PASS/VERIFIED_FROM_LOG.
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import atomic_write_json  # noqa: E402

ALLOWED_STATUSES = frozenset({
    "NOT_TESTED",
    "USER_REPORTED_TESTED",
    "VERIFIED_FROM_LOG",
    "PASS",
    "FAIL",
    "UNAVAILABLE",
    "NOT_INTEGRATED",
    "CONDITIONAL",
})

ALLOWED_TEST_TYPES = frozenset({"preflight", "live-smoke", "preflight-or-live-smoke"})

# Patterns that indicate a credential leaked into a report field.
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
    re.compile(r"api[_-]?key\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def build_record(test_id: str, component: str, test_type: str, status: str,
                 model_id: Optional[str], endpoint: Optional[str],
                 http_status: Optional[int], latency_ms: Optional[int],
                 evidence_file: Optional[str], error_category: Optional[str],
                 notes: str, timestamp_utc: Optional[str] = None) -> dict:
    return {
        "test_id": test_id,
        "component": component,
        "test_type": test_type,
        "status": status,
        "model_id": model_id,
        "endpoint": endpoint,
        "timestamp_utc": timestamp_utc or utc_now_iso(),
        "http_status": http_status,
        "latency_ms": latency_ms,
        "evidence_file": evidence_file,
        "error_category": error_category,
        "notes": notes,
    }


def validate_record(record: dict) -> list[str]:
    """Return a list of validation errors (empty means valid)."""
    errors: list[str] = []
    for field in ("test_id", "component", "test_type", "status"):
        if not record.get(field) or not str(record[field]).strip():
            errors.append(f"missing required field: {field}")
    if record.get("status") not in ALLOWED_STATUSES:
        errors.append(f"invalid status `{record.get('status')}`; allowed: "
                      f"{', '.join(sorted(ALLOWED_STATUSES))}")
    if record.get("test_type") not in ALLOWED_TEST_TYPES:
        errors.append(f"invalid test_type `{record.get('test_type')}`; allowed: "
                      f"{', '.join(sorted(ALLOWED_TEST_TYPES))}")
    # PASS requires real evidence: an HTTP status, an evidence file, or latency.
    if record.get("status") == "PASS":
        if record.get("http_status") is None and not record.get("evidence_file") \
                and record.get("latency_ms") is None:
            errors.append("status PASS requires real evidence: --http-status, "
                          "--evidence-file, or --latency-ms must be provided")
    if record.get("status") == "VERIFIED_FROM_LOG" and not record.get("evidence_file"):
        errors.append("status VERIFIED_FROM_LOG requires --evidence-file pointing at the log")
    # Credential rejection across all free-text fields.
    for field, value in record.items():
        if isinstance(value, str) and contains_secret(value):
            errors.append(f"field `{field}` appears to contain a credential; refused")
    http_status = record.get("http_status")
    if http_status is not None:
        try:
            http_ok = 100 <= int(http_status) <= 599
        except (TypeError, ValueError):
            http_ok = False
        if not http_ok:
            errors.append(f"http_status out of range: {http_status}")
    latency = record.get("latency_ms")
    if latency is not None:
        try:
            latency_ok = int(latency) >= 0
        except (TypeError, ValueError):
            latency_ok = False
        if not latency_ok:
            errors.append(f"latency_ms must be >= 0: {latency}")
    return errors


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Record a sanitized smoke-test outcome.")
    parser.add_argument("--test-id", default=None, help="Unique test id (default: generated).")
    parser.add_argument("--component", required=True, help="Component name, e.g. meta-spark.")
    parser.add_argument("--test-type", required=True, choices=sorted(ALLOWED_TEST_TYPES))
    parser.add_argument("--status", required=True, help=f"One of: {', '.join(sorted(ALLOWED_STATUSES))}")
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--http-status", type=int, default=None)
    parser.add_argument("--latency-ms", type=int, default=None)
    parser.add_argument("--evidence-file", default=None)
    parser.add_argument("--error-category", default=None)
    parser.add_argument("--notes", default="No live request performed")
    parser.add_argument("--out-dir", default="results/phase1")
    parser.add_argument("--overwrite", action="store_true",
                        help="Allow overwriting an existing record file (default: refuse).")
    args = parser.parse_args(argv)

    test_id = args.test_id or f"{args.component}-{uuid.uuid4().hex[:8]}"
    record = build_record(
        test_id=test_id, component=args.component, test_type=args.test_type,
        status=args.status, model_id=args.model_id, endpoint=args.endpoint,
        http_status=args.http_status, latency_ms=args.latency_ms,
        evidence_file=args.evidence_file, error_category=args.error_category,
        notes=args.notes)

    errors = validate_record(record)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create output dir: {exc}", file=sys.stderr)
        return 1
    out_path = out_dir / f"smoke-{args.component}-{test_id}.json"
    if out_path.exists() and not args.overwrite:
        print(f"ERROR: refusing to overwrite existing record: {out_path} "
              "(pass --overwrite to replace)", file=sys.stderr)
        return 1
    try:
        atomic_write_json(out_path, record)
    except OSError as exc:
        print(f"ERROR: cannot write record: {exc}", file=sys.stderr)
        return 1

    print(f"Recorded {args.status} for {args.component} -> {out_path}")
    if args.status in ("USER_REPORTED_TESTED", "NOT_TESTED"):
        print("Note: this status is unverified locally. Remaining uncertainty: no local "
              "request/response log exists for this integration in this workspace.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
