"""Authentication endpoints: login, logout, session info."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request, Response

from app.auth import sessions
from app.config import Settings
from app.dependencies import current_session, db_dep, settings_dep
from app.domain.enums import ActorType
from app.schemas.requests import LoginRequest
from app.schemas.responses import SessionInfo
from app.services import audit_service
from app.storage.database import transaction

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "airlock_session"


@router.post("/login")
async def login(data: LoginRequest, request: Request, response: Response,
          settings: Settings = Depends(settings_dep),
          conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = request  # lockout is global (login:owner); no client-IP/XFF trust.
    session_id, token, csrf = sessions.login(conn, settings, data.pin)
    with transaction(conn):
        audit_service.record(conn, audit_service.SESSION_CREATED,
                             actor_type=ActorType.OWNER, actor_id=session_id,
                             payload={})
    secure = not (settings.allow_insecure_cookies and settings.environment != "production")
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure,
                        samesite="lax", path="/", max_age=settings.session_duration_minutes * 60)
    row = sessions._sessions.get(conn, session_id)
    # The raw session token travels only in the HttpOnly cookie, never in
    # the response body.
    return {"session_id": session_id, "csrf_token": csrf,
            "expires_at": row["expires_at"] if row else None}


@router.post("/logout")
async def logout(request: Request, response: Response,
           session: dict = Depends(current_session),
           conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    sessions.logout(conn, str(session["session_id"]))
    with transaction(conn):
        audit_service.record(conn, audit_service.SESSION_REVOKED,
                             actor_type=ActorType.OWNER,
                             actor_id=str(session["session_id"]), payload={})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=SessionInfo)
async def me(session: dict = Depends(current_session)) -> dict:
    return {"authenticated": True,
            "session_id": session["session_id"],
            "expires_at": session["expires_at"]}


@router.post("/csrf-refresh")
async def csrf_refresh(session: dict = Depends(current_session),
                       conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    """Rotate the session CSRF token (e.g. after a browser refresh).

    No CSRF check here by design: this is the bootstrap that issues the
    token, and only the session owner can read the same-origin response.
    The previous token is invalidated immediately.
    """
    token = sessions.rotate_csrf(conn, str(session["session_id"]))
    return {"csrf_token": token}
