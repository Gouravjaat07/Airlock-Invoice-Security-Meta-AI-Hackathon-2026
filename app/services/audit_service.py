"""Append-only hash-chained audit log.

Each event hashes the canonical payload plus the previous event hash.
Business operations write their audit event in the same transaction.
Verification replays the chain and detects modification/deletion/reorder.

Limitation: tamper-evident, not tamper-proof against a privileged DB
administrator who can rewrite history and recompute hashes.
"""

from __future__ import annotations

import json
import sqlite3

from app.core.canonical_json import canonical_sha256
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.domain.enums import ActorType
from app.storage.repositories import AuditRepository

GENESIS_HASH = "GENESIS"
_repo = AuditRepository()

# Stable event vocabulary (additive only).
CASE_CREATED = "case.created"
ARTIFACT_UPLOADED = "artifact.uploaded"
ARTIFACT_DEDUPLICATED = "artifact.deduplicated"
READER_STARTED = "reader.started"
READER_COMPLETED = "reader.completed"
READER_ERROR = "reader.error"
EXTRACTION_VALIDATED = "extraction.validated"
EXTRACTION_REJECTED = "extraction.rejected"
VENDOR_MATCH = "vendor.match"
VENDOR_AMBIGUITY = "vendor.ambiguity"
BANK_MISMATCH = "bank.mismatch"
ARITHMETIC_CHECK = "arithmetic.check"
DUPLICATE_CHECK = "duplicate.check"
PO_CHECK = "po.check"
SAM_EVIDENCE = "sam.evidence"
VOICE_TRANSCRIPT = "voice.transcript"
CORROBORATION_COMPLETED = "corroboration.completed"
POLICY_EVALUATED = "policy.evaluated"
VERDICT_CREATED = "verdict.created"
PROPOSAL_CREATED = "proposal.created"
FACT_EDITED = "fact.edited"
VENDOR_CREATED = "vendor.created"
VENDOR_UPDATED = "vendor.updated"
BANK_CHANGE_REQUESTED = "bank_change.requested"
SESSION_CREATED = "session.created"
SESSION_REVOKED = "session.revoked"
CHALLENGE_CREATED = "challenge.created"
APPROVAL_FAILED = "approval.failed"
APPROVAL_SUCCEEDED = "approval.succeeded"
PROPOSAL_REJECTED = "proposal.rejected"
MOCK_PAYMENT_EXECUTED = "mock_payment.executed"
AUDIT_VERIFIED = "audit.verified"


def _event_hash(*, ts: str, event_type: str, case_id: str | None,
                actor_type: str, actor_id: str | None, payload: dict,
                prev_hash: str) -> str:
    return canonical_sha256({
        "ts": ts,
        "event_type": event_type,
        "case_id": case_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "payload": payload,
        "prev_hash": prev_hash,
    })


def record(conn: sqlite3.Connection, event_type: str, *,
           case_id: str | None = None,
           actor_type: ActorType = ActorType.SYSTEM,
           actor_id: str | None = None,
           payload: dict | None = None) -> int:
    """Append one event inside the caller's transaction. Returns event id."""
    latest = _repo.latest(conn)
    prev_hash = latest["event_hash"] if latest else GENESIS_HASH
    ts = SYSTEM_CLOCK.now().isoformat()
    clean = dict(payload or {})
    event_hash = _event_hash(ts=ts, event_type=event_type, case_id=case_id,
                             actor_type=actor_type.value, actor_id=actor_id,
                             payload=clean, prev_hash=prev_hash)
    try:
        return _repo.insert(conn, ts=ts, case_id=case_id, event_type=event_type,
                            actor_type=actor_type.value, actor_id=actor_id,
                            payload=clean, prev_hash=prev_hash, event_hash=event_hash)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(ErrorCode.AUDIT, f"Audit write failed: {exc}") from exc


def verify_chain(conn: sqlite3.Connection) -> dict:
    """Replay the full chain. Returns {ok, events, break_at, reason}."""
    events = _repo.all_ordered(conn)
    prev_hash = GENESIS_HASH
    expected_id: int | None = None
    for event in events:
        if expected_id is not None and event["id"] != expected_id:
            return {"ok": False, "events": len(events), "break_at": event["id"],
                    "reason": f"sequence gap before event {event['id']}"}
        expected_id = int(event["id"]) + 1
        if event["prev_hash"] != prev_hash:
            return {"ok": False, "events": len(events), "break_at": event["id"],
                    "reason": f"prev_hash mismatch at event {event['id']}"}
        recomputed = _event_hash(
            ts=str(event["ts"]), event_type=str(event["event_type"]),
            case_id=event["case_id"], actor_type=str(event["actor_type"]),
            actor_id=event["actor_id"],
            payload=json.loads(str(event["payload_json"])),
            prev_hash=str(event["prev_hash"]))
        if recomputed != event["event_hash"]:
            return {"ok": False, "events": len(events), "break_at": event["id"],
                    "reason": f"event hash mismatch at event {event['id']}"}
        prev_hash = str(event["event_hash"])
    return {"ok": True, "events": len(events), "break_at": None, "reason": None}
