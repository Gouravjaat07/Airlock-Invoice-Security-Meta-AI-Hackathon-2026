"""Mock payment endpoints (read-only views; execution is via confirm)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from app.dependencies import current_session, db_dep
from app.services import mock_payment_service

router = APIRouter(tags=["payments"])


@router.get("/payments/mock/{payment_id}")
async def get_payment(payment_id: str,
                session: dict = Depends(current_session),
                conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    return mock_payment_service.get_payment(conn, payment_id)


@router.get("/cases/{case_id}/payments/mock")
async def list_case_payments(case_id: str,
                       session: dict = Depends(current_session),
                       conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    return {"payments": mock_payment_service.list_for_case(conn, case_id)}
