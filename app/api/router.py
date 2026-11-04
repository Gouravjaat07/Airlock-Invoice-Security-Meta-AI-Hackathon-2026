"""API router: all v1 routes plus health."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from app import __version__
from app.api import (
    audit,
    auth,
    cases,
    dashboard,
    evaluation,
    payments,
    proposals,
    providers,
    vendors,
)
from app.config import Settings
from app.dependencies import db_dep, settings_dep
from app.schemas.responses import HealthResponse
from app.storage.database import current_version, latest_version

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(cases.router)
router.include_router(dashboard.router)
router.include_router(vendors.router)
router.include_router(proposals.router)
router.include_router(payments.router)
router.include_router(audit.router)
router.include_router(evaluation.router)
router.include_router(providers.router)


@router.get("/health", tags=["health"], response_model=HealthResponse)
async def health(settings: Settings = Depends(settings_dep),
                 conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    try:
        version = current_version(conn)
        database = "ok" if version >= latest_version() else "migrations_pending"
    except Exception:
        version = -1
        database = "unavailable"
    return {"status": "ok" if database == "ok" else "degraded",
            "version": __version__,
            "database": database,
            "schema_version": version,
            "policy_version": settings.policy_version}
