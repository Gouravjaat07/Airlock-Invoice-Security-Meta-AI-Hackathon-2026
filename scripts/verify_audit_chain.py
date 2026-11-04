"""Verify the audit hash chain (read-only).

Usage: python scripts/verify_audit_chain.py [--json PATH]
Exit 0 when the chain verifies, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common import atomic_write_json, default_audit_root, provenance_envelope  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.services import audit_service  # noqa: E402
from app.storage import database  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the audit hash chain.")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Write the verification report as JSON.")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        database.upgrade(settings)
        conn = database.connect(settings)
        try:
            result = audit_service.verify_chain(conn)
        finally:
            conn.close()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    status = "OK" if result["ok"] else "BROKEN"
    print(f"Audit chain: {status} ({result['events']} events)")
    if not result["ok"]:
        print(f"Break at event {result['break_at']}: {result['reason']}")
    exit_code = 0 if result["ok"] else 1
    if args.json_path:
        report = {"verification": result,
                  "provenance": provenance_envelope(
                      "verify_audit_chain", argv=argv, root=default_audit_root(),
                      extra={"exit_code": exit_code})}
        try:
            atomic_write_json(args.json_path, report)
        except OSError as exc:
            print(f"ERROR: cannot write report: {exc}", file=sys.stderr)
            return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
