"""Proposal and approval endpoints (owner auth + CSRF on mutations)."""

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
from app.schemas.proposal import ProposalView
from app.schemas.requests import ChallengeRequest, ConfirmRequest
from app.services import approval_service, proposal_service

router = APIRouter(tags=["proposals"])


@router.get("/proposals")
async def list_proposals(request: Request,
                         session: dict = Depends(current_session),
                         conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    query = parse_pagination(request)
    return {"proposals": proposal_service.list_proposals(
                conn, limit=query.limit, offset=query.offset),
            "limit": query.limit, "offset": query.offset}


@router.get("/proposals/{proposal_id}", response_model=ProposalView)
async def get_proposal(proposal_id: str,
                 session: dict = Depends(current_session),
                 conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    return proposal_service.get_proposal(conn, proposal_id)


@router.post("/proposals/{proposal_id}/challenge")
async def create_challenge(proposal_id: str, data: ChallengeRequest,
                     request: Request,
                     x_csrf_token: Annotated[str | None, Header()] = None,
                     session: dict = Depends(current_session),
                     settings: Settings = Depends(settings_dep),
                     conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    validate_csrf(session, x_csrf_token or data.csrf_token,
                  via_cookie=bool(getattr(request.state, "via_cookie", False)))
    return approval_service.issue_challenge(conn, settings, proposal_id,
                                            session_id=str(session["session_id"]))


@router.post("/proposals/{proposal_id}/confirm")
async def confirm_proposal(proposal_id: str, data: ConfirmRequest,
                     request: Request,
                     x_csrf_token: Annotated[str | None, Header()] = None,
                     session: dict = Depends(current_session),
                     settings: Settings = Depends(settings_dep),
                     conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    validate_csrf(session, x_csrf_token or data.csrf_token,
                  via_cookie=bool(getattr(request.state, "via_cookie", False)))
    return approval_service.confirm(conn, settings, proposal_id,
                                    challenge_id=data.challenge_id,
                                    pin=data.pin,
                                    session_id=str(session["session_id"]))
