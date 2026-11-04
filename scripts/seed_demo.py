"""Seed synthetic demo vendors and purchase orders (idempotent).

Reads registry/synthetic_vendors.json (external data, never real records).
Existing vendor/PO ids are skipped unless --force --yes is passed.

Usage: python scripts/seed_demo.py [--force --yes]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_settings  # noqa: E402
from app.core.security import bank_fingerprint  # noqa: E402
from app.domain.vendors import normalize_vendor_name  # noqa: E402
from app.schemas.invoice import parse_money  # noqa: E402
from app.storage import database  # noqa: E402
from app.storage.database import transaction  # noqa: E402
from app.storage.repositories import (  # noqa: E402
    PurchaseOrderRepository,
    VendorRepository,
)

_vendors = VendorRepository()
_pos = PurchaseOrderRepository()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed synthetic demo registry.")
    parser.add_argument("--force", action="store_true",
                        help="Update existing records (requires --yes).")
    parser.add_argument("--yes", action="store_true",
                        help="Confirm overwriting existing records.")
    args = parser.parse_args(argv)
    if args.force and not args.yes:
        print("ERROR: --force requires --yes.", file=sys.stderr)
        return 1

    try:
        settings = load_settings()
    except Exception as exc:
        print(f"ERROR: invalid configuration: {exc}", file=sys.stderr)
        return 1
    if settings.bank_hash_key is None:
        print("ERROR: AIRLOCK_BANK_HASH_KEY is not set. Run setup_airlock.py first.",
              file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent.parent
    data_path = root / "registry" / "synthetic_vendors.json"
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot read {data_path}: {exc}", file=sys.stderr)
        return 1

    database.upgrade(settings)
    conn = database.connect(settings)
    created_v = skipped_v = updated_v = 0
    created_p = skipped_p = 0
    try:
        from app.core.clock import SYSTEM_CLOCK
        now = SYSTEM_CLOCK.now().isoformat()
        with transaction(conn):
            for entry in data.get("vendors", []):
                normalized = normalize_vendor_name(entry["name"])
                fingerprint = bank_fingerprint(entry["bank_reference"],
                                               settings.bank_hash_key)
                cap = str(parse_money(entry["per_invoice_cap"])) \
                    if entry.get("per_invoice_cap") else None
                catalogue = json.dumps(entry.get("catalogue", []))
                existing = _vendors.get(conn, entry["vendor_id"])
                if existing is None:
                    _vendors.create(conn, vendor_id=entry["vendor_id"],
                                    name=entry["name"], name_norm=normalized,
                                    bank_fp=fingerprint, catalogue_json=catalogue,
                                    cap=cap, now=now)
                    created_v += 1
                elif args.force:
                    _vendors.update(conn, vendor_id=entry["vendor_id"],
                                    expected_version=int(existing["version"]),
                                    now=now, name=entry["name"],
                                    name_norm=normalized,
                                    active_bank_fingerprint=fingerprint,
                                    catalogue_json=catalogue,
                                    per_invoice_cap=cap)
                    updated_v += 1
                else:
                    skipped_v += 1
            for entry in data.get("purchase_orders", []):
                if _pos.get(conn, entry["po_id"]) is None:
                    _pos.create(conn, po_id=entry["po_id"],
                                vendor_id=entry["vendor_id"],
                                po_reference=entry["po_reference"],
                                currency=entry["currency"],
                                original=str(parse_money(entry["original_amount"])),
                                remaining=str(parse_money(entry["remaining_amount"])))
                    created_p += 1
                else:
                    skipped_p += 1
    finally:
        conn.close()
    print(f"Vendors: {created_v} created, {updated_v} updated, {skipped_v} skipped. "
          f"POs: {created_p} created, {skipped_p} skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
