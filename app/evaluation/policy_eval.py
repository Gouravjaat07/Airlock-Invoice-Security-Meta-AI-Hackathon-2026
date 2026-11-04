"""Scenario evaluation: run synthetic cases end-to-end, compare verdicts."""

from __future__ import annotations

import json
import sqlite3

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.evaluation import fixtures as fixture_io
from app.services import case_service
from app.storage.artifacts import LocalBlobStore
from app.storage.database import transaction
from app.storage.repositories import EvalRepository

_repo = EvalRepository()


def run_scenarios(conn: sqlite3.Connection, settings: Settings,
                  store: LocalBlobStore, names: list[str]) -> dict:
    if not settings.enable_eval_api:
        raise AppError(ErrorCode.AUTH, "Evaluation API is disabled", status=403)
    run_id = new_id("eval")
    now = SYSTEM_CLOCK.now().isoformat()
    with transaction(conn):
        _repo.create(conn, run_id=run_id, now=now)
    results: list[dict] = []
    for name in names:
        results.append(_run_single(conn, settings, store, name))
    matched = sum(1 for item in results if item["match"])
    summary = {"run_id": run_id, "total": len(results), "matched": matched,
               "mismatched": len(results) - matched}
    with transaction(conn):
        _repo.finish(conn, run_id=run_id, status="completed",
                     summary=summary, results=results)
    return {"summary": summary, "results": results}


def _run_single(conn: sqlite3.Connection, settings: Settings,
                store: LocalBlobStore, name: str) -> dict:
    case_id = None
    try:
        spec = fixture_io.load_scenario(settings, name)
        files: list[tuple[str, str, bytes]] = []
        invoice_rel = spec.get("invoice_artifact")
        if not invoice_rel:
            return _mismatch(name, None, "scenario has no invoice_artifact")
        files.append(("invoice", str(invoice_rel).split("/")[-1],
                      fixture_io.read_artifact_bytes(settings, str(invoice_rel))))
        if spec.get("delivery_artifact"):
            files.append(("delivery", str(spec["delivery_artifact"]).split("/")[-1],
                          fixture_io.read_artifact_bytes(
                              settings, str(spec["delivery_artifact"]))))
        if spec.get("voice_artifact"):
            files.append(("voice", str(spec["voice_artifact"]).split("/")[-1],
                          fixture_io.read_artifact_bytes(
                              settings, str(spec["voice_artifact"]))))
        summary = case_service.create_case(
            conn, settings, store, files,
            idempotency_key=f"eval:{new_id('k')}")
        case_id = summary["case"]["id"]
        summary = case_service.process_case(conn, settings, store, case_id)
    except AppError as exc:
        # Always report the documented expectation (never null it away),
        # and honor declared failure injections: a scenario whose spec
        # carries `reader_error` documents the fail-closed ERROR path
        # ("no verdict"), so the exact injected error with no proposal
        # is a match. Anything else stays a mismatch for investigation.
        expected = None
        injected_match = False
        try:
            spec = fixture_io.load_scenario(settings, name)
            expected = spec.get("expected_verdict")
            declared = spec.get("reader_error")
            injected_match = (
                isinstance(declared, dict)
                and str(declared.get("code")) == exc.code)
        except AppError:
            pass
        return {"scenario": name, "expected": expected,
                "actual": f"ERROR:{exc.code}", "match": injected_match,
                "case_id": case_id, "rule_ids": [],
                "proposal": False, "error": exc.message[:200]}
    verdict = summary["verdict"]
    actual = verdict["verdict"] if verdict else None
    expected = spec.get("expected_verdict")
    rule_ids = json.loads(str(verdict["rule_ids_json"])) if verdict else []
    return {"scenario": name, "expected": expected, "actual": actual,
            "match": actual == expected,
            "case_id": summary["case"]["id"], "rule_ids": rule_ids,
            "proposal": summary["proposal"] is not None}


def _mismatch(name: str, expected: str | None, reason: str) -> dict:
    return {"scenario": name, "expected": expected, "actual": None,
            "match": False, "case_id": None, "rule_ids": [],
            "proposal": False, "error": reason}


def get_run(conn: sqlite3.Connection, run_id: str) -> dict:
    row = _repo.get(conn, run_id)
    if row is None:
        raise AppError(ErrorCode.SCHEMA, "Evaluation run not found", status=404)
    return {"run_id": row["run_id"], "created_at": row["created_at"],
            "status": row["status"],
            "summary": json.loads(str(row["summary_json"]))}
