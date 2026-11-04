"""Case endpoints: create, list, inspect, process, reject, edit facts."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response

from app.auth.sessions import validate_csrf
from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.dependencies import (
    current_session,
    db_dep,
    parse_pagination,
    settings_dep,
    store_dep,
)
from app.schemas.requests import FactEditRequest
from app.services import case_service
from app.storage.artifacts import LocalBlobStore

router = APIRouter(tags=["cases"])

MAX_FORM_BYTES = 64 * 1024 * 1024  # defense in depth; per-file limit is smaller


async def offload_sync(fn: Callable[[], Any]) -> Any:
    """Run blocking pipeline work off the event loop when one exists.

    Under uvicorn the sync pipeline (including minutes-long model
    calls) runs in a worker thread so one slow provider cannot freeze
    unrelated requests. Under the loop-free ASGI test harness there is
    no running loop, so the work runs inline instead — same code, same
    behavior, no `asyncio` awaitable is ever touched there (AD-24).

    The per-request sqlite connection is created with
    `check_same_thread=False` and used sequentially (never shared
    across concurrent threads), so the thread hop is safe.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn()
    return await asyncio.to_thread(fn)


@router.post("/cases")
async def create_case(request: Request,
                      settings: Settings = Depends(settings_dep),
                      conn: sqlite3.Connection = Depends(db_dep),
                      store: LocalBlobStore = Depends(store_dep)) -> dict:
    form = await request.form()
    files: list[tuple[str, str, bytes]] = []
    total = 0
    for field_name, item in form.multi_items():
        if not hasattr(item, "read"):
            raise AppError(ErrorCode.UPLOAD, f"Unexpected form field: {field_name}")
        data = await item.read()
        total += len(data)
        if total > MAX_FORM_BYTES:
            raise AppError(ErrorCode.UPLOAD, "Request body too large")
        files.append((field_name, item.filename or "upload", data))
    summary = case_service.create_case(
        conn, settings, store, files,
        idempotency_key=request.headers.get("idempotency-key"))
    return _summary_view(summary)


@router.get("/cases")
async def list_cases(request: Request,
                     conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    query = parse_pagination(request)
    return {"cases": case_service.list_cases(conn, limit=query.limit,
                                             offset=query.offset),
            "limit": query.limit, "offset": query.offset}


@router.get("/cases/{case_id}")
async def get_case(case_id: str,
             settings: Settings = Depends(settings_dep),
             conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    return _summary_view(case_service.get_case(conn, settings, case_id))


@router.post("/cases/{case_id}/process")
async def process_case(case_id: str,
                 settings: Settings = Depends(settings_dep),
                 conn: sqlite3.Connection = Depends(db_dep),
                 store: LocalBlobStore = Depends(store_dep)) -> dict:
    # Processing always returns the deterministic outcome (verdict in body);
    # E_POLICY_* errors are reserved for refused approval attempts.
    summary = await offload_sync(
        lambda: case_service.process_case(conn, settings, store, case_id))
    return _summary_view(summary)


@router.get("/cases/{case_id}/artifacts/{artifact_id}/content")
async def artifact_content(case_id: str, artifact_id: str,
                           session: dict = Depends(current_session),
                           conn: sqlite3.Connection = Depends(db_dep),
                           store: LocalBlobStore = Depends(store_dep)):
    """Owner-only artifact bytes for document preview (case-bound).

    Stricter than the public case metadata endpoints: invoice artifacts
    carry PII. Served inline with the server-sniffed media type.
    """
    _ = session
    data, media_type = case_service.get_artifact_content(
        conn, store, case_id, artifact_id)
    return Response(content=data, media_type=media_type, headers={
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=3600"})


@router.post("/cases/{case_id}/reject")
async def reject_case(case_id: str, request: Request,
                x_csrf_token: Annotated[str | None, Header()] = None,
                session: dict = Depends(current_session),
                settings: Settings = Depends(settings_dep),
                conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    validate_csrf(session, x_csrf_token,
                  via_cookie=bool(getattr(request.state, "via_cookie", False)))
    summary = case_service.reject_case(conn, settings, case_id,
                                       session_id=str(session["session_id"]))
    return _summary_view(summary)


@router.post("/cases/{case_id}/facts/{fact_id}/edit")
async def edit_fact(case_id: str, fact_id: str, data: FactEditRequest,
              request: Request,
              x_csrf_token: Annotated[str | None, Header()] = None,
              session: dict = Depends(current_session),
              settings: Settings = Depends(settings_dep),
              conn: sqlite3.Connection = Depends(db_dep),
              store: LocalBlobStore = Depends(store_dep)) -> dict:
    validate_csrf(session, x_csrf_token or data.csrf_token,
                  via_cookie=bool(getattr(request.state, "via_cookie", False)))
    summary = await offload_sync(
        lambda: case_service.edit_fact(conn, settings, store, case_id, fact_id,
                                       data.value,
                                       session_id=str(session["session_id"])))
    return _summary_view(summary)


def _summary_view(summary: dict) -> dict:
    import json as _json

    case = dict(summary["case"])
    verdict = summary["verdict"]
    proposal = summary["proposal"]
    return {
        "case": {"id": case["id"], "state": case["state"],
                 "created_at": case["created_at"],
                 "updated_at": case["updated_at"],
                 "completed_at": case.get("completed_at"),
                 "error_code": case.get("error_code"),
                 "error_summary": case.get("error_summary"),
                 "version": case["version"]},
        "artifacts": [{"id": a["id"], "kind": a["kind"],
                       "media_type": a["media_type"],
                       "size_bytes": a["size_bytes"],
                       "sha256": a["sha256"]} for a in summary["artifacts"]],
        "facts": [{"id": f["id"], "field": f["field"],
                   "value": _safe_fact_value(f),
                   "taint_class": f["taint_class"],
                   "validation_status": f["validation_status"],
                   "validated_by": f["validated_by"],
                   "source": _json.loads(str(f["source_json"])),
                   "producer": _json.loads(str(f["producer_json"]))}
                  for f in summary["facts"]],
        "verdict": verdict,
        "proposal": proposal,
        "payments": summary["payments"],
        "explanation": summary["explanation"],
    }


def _safe_fact_value(fact: dict) -> object:
    import json as _json
    value = _json.loads(str(fact["value_json"]))
    if fact["field"] == "bank" and isinstance(value, dict):
        return {"fingerprint": value.get("fingerprint"),
                "match": value.get("match")}
    return value
