"""Dashboard summary endpoint (owner-only, read-only aggregates)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from app.dependencies import current_session, db_dep
from app.services import case_service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary")
async def get_summary(session: dict = Depends(current_session),
                      conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    return case_service.dashboard_summary(conn)
