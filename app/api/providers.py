"""Provider availability endpoint (owner-only, no secrets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings
from app.dependencies import current_session, settings_dep
from app.providers.registry import all_statuses

router = APIRouter(tags=["providers"])


@router.get("/providers")
async def provider_status(session: dict = Depends(current_session),
                    settings: Settings = Depends(settings_dep)) -> dict:
    _ = session
    return {"providers": [status.as_dict()
                          for status in all_statuses(settings)]}
