"""FastAPI dependency injection: settings, db, store, auth.

Everything is `async def` (bodies are plain sync code): FastAPI would run
`def` handlers/dependencies in a worker threadpool, which needs an event
loop. Async declarations keep the app drivable without one.
"""

from __future__ import annotations

import sqlite3
from typing import AsyncIterator

from fastapi import Depends, Header, Request

from app.auth import sessions
from app.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.schemas.common import PagedQuery
from app.storage.artifacts import LocalBlobStore
from app.storage.database import connect


async def settings_dep() -> Settings:
    return get_settings()


async def db_dep(settings: Settings = Depends(settings_dep)) -> AsyncIterator[sqlite3.Connection]:
    conn = connect(settings)
    try:
        yield conn
    finally:
        conn.close()


async def store_dep(settings: Settings = Depends(settings_dep)) -> LocalBlobStore:
    return LocalBlobStore(settings)


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def current_session(request: Request,
                          settings: Settings = Depends(settings_dep),
                          conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    token = _bearer_token(request.headers.get("authorization"))
    via_cookie = False
    if token is None:
        token = request.cookies.get("airlock_session")
        via_cookie = token is not None
    session = sessions.validate_session(conn, settings, token)
    request.state.session = session
    request.state.via_cookie = via_cookie
    return session


async def optional_session(request: Request,
                           settings: Settings = Depends(settings_dep),
                           conn: sqlite3.Connection = Depends(db_dep)) -> dict | None:
    token = _bearer_token(request.headers.get("authorization"))
    if token is None:
        token = request.cookies.get("airlock_session")
    if not token:
        return None
    try:
        return sessions.validate_session(conn, settings, token)
    except Exception:
        return None


async def csrf_dep(request: Request,
                   x_csrf_token: str | None = Header(default=None)) -> str | None:
    body_token = getattr(request.state, "body_csrf", None)
    return x_csrf_token or body_token


def parse_pagination(request: Request) -> PagedQuery:
    """Validate limit/offset synchronously (a Pydantic-model Depends()
    would run in a worker threadpool, which needs an event loop)."""
    from pydantic import ValidationError as _ValidationError
    try:
        return PagedQuery.model_validate(dict(request.query_params))
    except _ValidationError as exc:
        raise AppError(ErrorCode.SCHEMA, "Invalid pagination parameters",
                       details=[{"code": "pagination",
                                 "message": str(exc.errors()[0]["msg"])}],
                       status=422) from exc
