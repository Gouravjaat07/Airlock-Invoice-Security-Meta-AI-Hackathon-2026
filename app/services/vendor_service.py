"""Vendor registry service: CRUD + bank-change cooling-off workflow."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.security import bank_fingerprint
from app.domain.enums import ActorType
from app.domain.vendors import normalize_vendor_name
from app.schemas.invoice import parse_money
from app.schemas.vendor import CatalogueItemIn, VendorCreate, VendorUpdate
from app.services import audit_service
from app.storage.database import transaction
from app.storage.repositories import VendorRepository

logger = get_logger("airlock.vendors")

_vendors = VendorRepository()


def _catalogue_json(items: list[CatalogueItemIn]) -> str:
    seen: set[str] = set()
    clean = []
    for item in items:
        if item.item_id in seen:
            raise AppError(ErrorCode.SCHEMA, f"Duplicate catalogue item {item.item_id}")
        seen.add(item.item_id)
        clean.append({"item_id": item.item_id, "label": item.label,
                      "tolerance": item.tolerance})
    return json.dumps(clean)


def _cap_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = parse_money(value, field_name="per-invoice cap")
    except ValueError as exc:
        raise AppError(ErrorCode.SCHEMA, str(exc)) from exc
    if parsed <= 0:
        raise AppError(ErrorCode.SCHEMA, "per-invoice cap must be positive")
    return str(parsed)


def create_vendor(conn: sqlite3.Connection, settings: Settings, data: VendorCreate,
                  *, session_id: str) -> dict:
    if settings.bank_hash_key is None:
        raise AppError(ErrorCode.DATABASE, "Bank verification is not configured")
    normalized = normalize_vendor_name(data.name)
    if not normalized:
        raise AppError(ErrorCode.SCHEMA, "Vendor name normalizes to empty")
    if _vendors.get_by_norm(conn, normalized) is not None:
        raise AppError(ErrorCode.DUPLICATE, "A vendor with this normalized name exists")
    try:
        fingerprint = bank_fingerprint(data.bank_reference, settings.bank_hash_key)
    except ValueError as exc:
        raise AppError(ErrorCode.SCHEMA, str(exc)) from exc
    vendor_id = new_id("ven")
    now = SYSTEM_CLOCK.now().isoformat()
    with transaction(conn):
        try:
            _vendors.create(conn, vendor_id=vendor_id, name=data.name.strip(),
                            name_norm=normalized, bank_fp=fingerprint,
                            catalogue_json=_catalogue_json(data.catalogue),
                            cap=_cap_str(data.per_invoice_cap), now=now)
        except AppError:
            raise
        except sqlite3.IntegrityError as exc:
            # Lost a create race on a UNIQUE key (id or normalized name).
            raise AppError(ErrorCode.DUPLICATE,
                           "Vendor conflicts with an existing record"
                           ) from exc
        except Exception as exc:
            logger.error("vendor create failed: %r", exc)
            raise AppError(ErrorCode.DATABASE, "Cannot create vendor") from exc
        audit_service.record(conn, audit_service.VENDOR_CREATED,
                             actor_type=ActorType.OWNER, actor_id=session_id,
                             payload={"vendor_id": vendor_id})
    row = _vendors.get(conn, vendor_id)
    assert row is not None
    return _public(row)


def _public(row: dict) -> dict:
    return {
        "vendor_id": row["vendor_id"],
        "name": row["name"],
        "name_norm": row["name_norm"],
        "active_bank_fingerprint": row["active_bank_fingerprint"],
        "catalogue": json.loads(str(row["catalogue_json"] or "[]")),
        "per_invoice_cap": row["per_invoice_cap"],
        "status": row["status"],
        "version": row["version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_vendor(conn: sqlite3.Connection, vendor_id: str) -> dict:
    row = _vendors.get(conn, vendor_id)
    if row is None:
        raise AppError(ErrorCode.SCHEMA, "Vendor not found", status=404)
    return _public(row)


def list_vendors(conn: sqlite3.Connection, *, limit: int, offset: int) -> list[dict]:
    return [_public(row) for row in _vendors.list(conn, limit=limit, offset=offset)]


def update_vendor(conn: sqlite3.Connection, settings: Settings, vendor_id: str,
                  data: VendorUpdate, *, session_id: str,
                  expected_version: int | None = None) -> dict:
    row = _vendors.get(conn, vendor_id)
    if row is None:
        raise AppError(ErrorCode.SCHEMA, "Vendor not found", status=404)
    fields: dict = {}
    if data.name is not None:
        normalized = normalize_vendor_name(data.name)
        if not normalized:
            raise AppError(ErrorCode.SCHEMA, "Vendor name normalizes to empty")
        clash = _vendors.get_by_norm(conn, normalized)
        if clash is not None and clash["vendor_id"] != vendor_id:
            raise AppError(ErrorCode.DUPLICATE, "A vendor with this normalized name exists")
        fields["name"] = data.name.strip()
        fields["name_norm"] = normalized
    if data.catalogue is not None:
        fields["catalogue_json"] = _catalogue_json(data.catalogue)
    if data.per_invoice_cap is not None:
        fields["per_invoice_cap"] = _cap_str(data.per_invoice_cap)
    if data.status is not None:
        fields["status"] = data.status
    with transaction(conn):
        ok = _vendors.update(conn, vendor_id=vendor_id,
                             expected_version=expected_version or int(row["version"]),
                             now=SYSTEM_CLOCK.now().isoformat(), **fields)
        if not ok:
            raise AppError(ErrorCode.CONFLICT, "Vendor modified concurrently")
        _activate_due(conn, vendor_id)
        audit_service.record(conn, audit_service.VENDOR_UPDATED,
                             actor_type=ActorType.OWNER, actor_id=session_id,
                             payload={"vendor_id": vendor_id,
                                      "fields": sorted(fields)})
    updated = _vendors.get(conn, vendor_id)
    assert updated is not None
    return _public(updated)


def request_bank_change(conn: sqlite3.Connection, settings: Settings,
                        vendor_id: str, bank_reference: str, *,
                        session_id: str) -> dict:
    """Owner-initiated bank change: pending until the cooling-off elapses.

    The old fingerprint stays authoritative until activation; invoices
    presenting the new fingerprint fail R2 meanwhile.
    """
    row = _vendors.get(conn, vendor_id)
    if row is None:
        raise AppError(ErrorCode.SCHEMA, "Vendor not found", status=404)
    if settings.bank_hash_key is None:
        raise AppError(ErrorCode.DATABASE, "Bank verification is not configured")
    try:
        fingerprint = bank_fingerprint(bank_reference, settings.bank_hash_key)
    except ValueError as exc:
        raise AppError(ErrorCode.SCHEMA, str(exc)) from exc
    now = SYSTEM_CLOCK.now()
    effective = now + timedelta(hours=settings.bank_change_cooldown_hours)
    change_id = new_id("bc")
    with transaction(conn):
        _vendors.add_bank_change(conn, change_id=change_id, vendor_id=vendor_id,
                                 new_fp=fingerprint, initiated_by=session_id,
                                 requested_at=now.isoformat(),
                                 effective_at=effective.isoformat())
        ref = audit_service.record(conn, audit_service.BANK_CHANGE_REQUESTED,
                                   actor_type=ActorType.OWNER,
                                   actor_id=session_id,
                                   payload={"vendor_id": vendor_id,
                                            "change_id": change_id,
                                            "effective_at": effective.isoformat()})
        conn.execute("UPDATE vendor_bank_changes SET audit_ref = ? WHERE id = ?",
                     (str(ref), change_id))
    changes = _vendors.list_bank_changes(conn, vendor_id)
    return next(change for change in changes if change["id"] == change_id)


def list_bank_changes(conn: sqlite3.Connection, vendor_id: str) -> list[dict]:
    if _vendors.get(conn, vendor_id) is None:
        raise AppError(ErrorCode.SCHEMA, "Vendor not found", status=404)
    return _vendors.list_bank_changes(conn, vendor_id)


def _activate_due(conn: sqlite3.Connection, vendor_id: str) -> None:
    """Activate matured pending changes (called on vendor read/write paths)."""
    now = SYSTEM_CLOCK.now().isoformat()
    due = _vendors.activate_due_changes(conn, vendor_id=vendor_id, now=now)
    for change in due:
        row = _vendors.get(conn, vendor_id)
        assert row is not None
        _vendors.update(conn, vendor_id=vendor_id,
                        expected_version=int(row["version"]), now=now,
                        active_bank_fingerprint=change["new_fingerprint"])


def refresh_bank_activation(conn: sqlite3.Connection, vendor_id: str) -> dict:
    with transaction(conn):
        _activate_due(conn, vendor_id)
    return get_vendor(conn, vendor_id)


def activate_all_due(conn: sqlite3.Connection) -> int:
    """Activate every matured pending bank change. Returns count activated."""
    now = SYSTEM_CLOCK.now().isoformat()
    activated = 0
    with transaction(conn):
        for vendor_id in _vendors.due_vendor_ids(conn, now):
            due = _vendors.activate_due_changes(conn, vendor_id=vendor_id, now=now)
            for change in due:
                row = _vendors.get(conn, vendor_id)
                assert row is not None
                _vendors.update(conn, vendor_id=vendor_id,
                                expected_version=int(row["version"]), now=now,
                                active_bank_fingerprint=change["new_fingerprint"])
                activated += 1
    return activated
