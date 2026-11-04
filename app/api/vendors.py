"""Vendor registry endpoints (mutations require owner auth)."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.auth.sessions import validate_csrf
from app.config import Settings
from app.dependencies import (
    current_session,
    db_dep,
    parse_pagination,
    settings_dep,
)
from app.schemas.vendor import BankChangeRequest, VendorCreate, VendorUpdate
from app.services import vendor_service

router = APIRouter(tags=["vendors"])


def _csrf(request: Request, session: dict, token: str | None) -> None:
    validate_csrf(session, token,
                  via_cookie=bool(getattr(request.state, "via_cookie", False)))


@router.get("/vendors")
async def list_vendors(request: Request,
                       conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    query = parse_pagination(request)
    return {"vendors": vendor_service.list_vendors(conn, limit=query.limit,
                                                   offset=query.offset)}


@router.post("/vendors")
async def create_vendor(data: VendorCreate, request: Request,
                  x_csrf_token: Annotated[str | None, Header()] = None,
                  session: dict = Depends(current_session),
                  settings: Settings = Depends(settings_dep),
                  conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _csrf(request, session, x_csrf_token)
    return vendor_service.create_vendor(conn, settings, data,
                                        session_id=str(session["session_id"]))


@router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str,
               conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    return vendor_service.get_vendor(conn, vendor_id)


@router.patch("/vendors/{vendor_id}")
async def update_vendor(vendor_id: str, data: VendorUpdate, request: Request,
                  x_csrf_token: Annotated[str | None, Header()] = None,
                  session: dict = Depends(current_session),
                  settings: Settings = Depends(settings_dep),
                  conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _csrf(request, session, x_csrf_token)
    return vendor_service.update_vendor(conn, settings, vendor_id, data,
                                        session_id=str(session["session_id"]))


@router.post("/vendors/{vendor_id}/bank-change-requests")
async def request_bank_change(vendor_id: str, data: BankChangeRequest,
                        request: Request,
                        x_csrf_token: Annotated[str | None, Header()] = None,
                        session: dict = Depends(current_session),
                        settings: Settings = Depends(settings_dep),
                        conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _csrf(request, session, x_csrf_token)
    return vendor_service.request_bank_change(conn, settings, vendor_id,
                                              data.bank_reference,
                                              session_id=str(session["session_id"]))


@router.get("/vendors/{vendor_id}/bank-change-requests")
async def list_bank_changes(vendor_id: str,
                      session: dict = Depends(current_session),
                      conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    return {"changes": vendor_service.list_bank_changes(conn, vendor_id)}
