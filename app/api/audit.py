"""Audit endpoints: case events (sanitized) and chain verification."""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, Depends, Request

from app.dependencies import current_session, db_dep, parse_pagination
from app.services import audit_service
from app.storage.database import transaction
from app.storage.repositories import AuditRepository

router = APIRouter(tags=["audit"])

_repo = AuditRepository()


def _event_view(event: dict) -> dict:
    return {**event, "payload": json.loads(str(event["payload_json"]))}


# NOTE: declared before /audit/{case_id} so "recent" is not captured
# as a case id (FastAPI matches routes in declaration order).
@router.get("/audit/recent")
async def recent_audit(request: Request,
                       session: dict = Depends(current_session),
                       conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    query = parse_pagination(request)
    events = _repo.recent(conn, limit=query.limit, offset=query.offset)
    return {"events": [_event_view(event) for event in events],
            "limit": query.limit, "offset": query.offset}


@router.get("/audit/{case_id}")
async def case_audit(case_id: str,
               session: dict = Depends(current_session),
               conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    events = _repo.list_for_case(conn, case_id)
    return {"case_id": case_id,
            "events": [_event_view(event) for event in events]}


@router.post("/audit/verify")
async def verify_audit(session: dict = Depends(current_session),
                 conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    result = audit_service.verify_chain(conn)
    with transaction(conn):
        audit_service.record(conn, audit_service.AUDIT_VERIFIED,
                             payload={"ok": result["ok"],
                                      "events": result["events"]})
    return result
