"""Evaluation endpoints (dev-only; disabled unless explicitly enabled)."""

from __future__ import annotations

import json
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.auth.sessions import validate_csrf
from app.config import Settings
from app.dependencies import current_session, db_dep, settings_dep, store_dep
from app.evaluation import policy_eval
from app.schemas.requests import EvalRunRequest
from app.storage.artifacts import LocalBlobStore
from app.storage.repositories import EvalRepository

router = APIRouter(tags=["evaluation"])

_repo = EvalRepository()


@router.post("/evaluation/run")
async def run_evaluation(data: EvalRunRequest, request: Request,
                   x_csrf_token: Annotated[str | None, Header()] = None,
                   session: dict = Depends(current_session),
                   settings: Settings = Depends(settings_dep),
                   conn: sqlite3.Connection = Depends(db_dep),
                   store: LocalBlobStore = Depends(store_dep)) -> dict:
    validate_csrf(session, x_csrf_token or data.csrf_token,
                  via_cookie=bool(getattr(request.state, "via_cookie", False)))
    return policy_eval.run_scenarios(conn, settings, store, data.scenarios)


@router.get("/evaluation/runs/{run_id}")
async def get_run(run_id: str,
            session: dict = Depends(current_session),
            conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    return policy_eval.get_run(conn, run_id)


@router.get("/evaluation/results/{run_id}")
async def get_results(run_id: str,
                session: dict = Depends(current_session),
                conn: sqlite3.Connection = Depends(db_dep)) -> dict:
    _ = session
    row = _repo.get(conn, run_id)
    if row is None:
        from app.core.errors import AppError, ErrorCode
        raise AppError(ErrorCode.SCHEMA, "Evaluation run not found", status=404)
    return {"run_id": row["run_id"],
            "results": json.loads(str(row["results_json"]))}
