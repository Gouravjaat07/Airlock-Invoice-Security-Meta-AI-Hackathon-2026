"""Case service: intake, processing, rejection, owner fact edits."""

from __future__ import annotations

import sqlite3

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.security import bank_fingerprint
from app.domain.enums import ActorType, CaseState
from app.domain.taint import TaintClass
from app.pipeline import ingest, process
from app.pipeline.state_machine import check_transition
from app.schemas.invoice import LineItem, parse_iso_date, parse_money
from app.services import audit_service
from app.storage.artifacts import LocalBlobStore
from app.storage.database import transaction
from app.storage.repositories import (
    ArtifactRepository,
    CaseRepository,
    FactRepository,
    PaymentRepository,
    ProposalRepository,
)

_cases = CaseRepository()
_facts = FactRepository()
_artifacts = ArtifactRepository()
_proposals = ProposalRepository()
_payments = PaymentRepository()

EDITABLE_STATES = frozenset({
    CaseState.UPLOADED, CaseState.ERROR, CaseState.EXPIRED,
    CaseState.REJECTED, CaseState.NEEDS_REVIEW, CaseState.PROPOSED,
})

EDITABLE_FIELDS = frozenset({
    "vendor_name", "invoice_number", "issue_date", "due_date", "currency",
    "subtotal", "tax", "total", "bank", "po_reference", "line_items",
})


def create_case(conn: sqlite3.Connection, settings: Settings,
                store: LocalBlobStore,
                files: list[tuple[str, str, bytes]],
                idempotency_key: str | None = None) -> dict:
    case = ingest.create_case(conn, settings, store, files,
                              idempotency_key=idempotency_key)
    return process.summarize(conn, settings, case["id"])


def process_case(conn: sqlite3.Connection, settings: Settings,
                 store: LocalBlobStore, case_id: str) -> dict:
    return process.run_case(conn, settings, store, case_id)


def get_case(conn: sqlite3.Connection, settings: Settings, case_id: str) -> dict:
    return process.summarize(conn, settings, case_id)


def list_cases(conn: sqlite3.Connection, *, limit: int, offset: int) -> list[dict]:
    return _cases.list(conn, limit=limit, offset=offset)


def reject_case(conn: sqlite3.Connection, settings: Settings, case_id: str,
                *, session_id: str) -> dict:
    case = _cases.get(conn, case_id)
    if case is None:
        raise AppError(ErrorCode.SCHEMA, "Case not found", status=404)
    current = CaseState(case["state"])
    if current not in (CaseState.NEEDS_REVIEW, CaseState.PROPOSED):
        raise AppError(ErrorCode.STATE_TRANSITION,
                       f"Only cases needing review or proposed can be rejected (is {current.value})")
    with transaction(conn):
        check_transition(current, CaseState.REJECTED)
        ok = _cases.update_state(conn, case_id=case_id, state=CaseState.REJECTED.value,
                                 now=SYSTEM_CLOCK.now().isoformat(),
                                 expected_version=int(case["version"]))
        if not ok:
            raise AppError(ErrorCode.CONFLICT, "Case modified concurrently")
        audit_service.record(conn, audit_service.PROPOSAL_REJECTED, case_id=case_id,
                             actor_type=ActorType.OWNER, actor_id=session_id,
                             payload={"from_state": current.value})
    return process.summarize(conn, settings, case_id)


def _validate_edit_value(field_name: str, value: object, settings: Settings) -> object:
    if field_name in ("vendor_name", "invoice_number"):
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise AppError(ErrorCode.SCHEMA, f"Invalid {field_name}")
        return value.strip()
    if field_name in ("issue_date", "due_date"):
        try:
            return parse_iso_date(value, field_name=field_name).isoformat()
        except ValueError as exc:
            raise AppError(ErrorCode.SCHEMA, str(exc)) from exc
    if field_name == "currency":
        if not isinstance(value, str) or len(value.strip()) != 3 \
                or not value.strip().isalpha() or not value.strip().isupper():
            raise AppError(ErrorCode.SCHEMA, "Currency must be a 3-letter uppercase code")
        return value.strip()
    if field_name in ("subtotal", "tax", "total"):
        try:
            parsed = parse_money(value, field_name=field_name)
        except ValueError as exc:
            raise AppError(ErrorCode.SCHEMA, str(exc)) from exc
        if parsed < 0:
            raise AppError(ErrorCode.SCHEMA,
                           f"{field_name} must be non-negative")
        return str(parsed)
    if field_name == "bank":
        # Transient raw reference -> fingerprint immediately; raw never stored.
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise AppError(ErrorCode.SCHEMA, "Invalid bank reference")
        if settings.bank_hash_key is None:
            raise AppError(ErrorCode.DATABASE, "Bank verification is not configured")
        try:
            fingerprint = bank_fingerprint(value, settings.bank_hash_key)
        except ValueError as exc:
            raise AppError(ErrorCode.SCHEMA, str(exc)) from exc
        return {"fingerprint": fingerprint, "match": None}
    if field_name == "po_reference":
        if value is not None and (not isinstance(value, str) or len(value) > 64):
            raise AppError(ErrorCode.SCHEMA, "Invalid PO reference")
        return value.strip() if isinstance(value, str) and value.strip() else None
    if field_name == "line_items":
        if not isinstance(value, list) or not value or len(value) > 200:
            raise AppError(ErrorCode.SCHEMA, "line_items must be a non-empty list")
        items = []
        for entry in value:
            if not isinstance(entry, dict):
                raise AppError(ErrorCode.SCHEMA, "Invalid line item")
            try:
                item = LineItem.model_validate(entry)
            except Exception as exc:
                raise AppError(ErrorCode.SCHEMA, f"Invalid line item: {exc}") from exc
            items.append({"description": item.description,
                          "quantity": str(item.quantity),
                          "unit_price": str(item.unit_price),
                          "catalogue_item_id": item.catalogue_item_id,
                          "extracted_item_id": item.extracted_item_id})
        return items
    raise AppError(ErrorCode.SCHEMA, f"Field '{field_name}' cannot be edited")


def edit_fact(conn: sqlite3.Connection, settings: Settings, store: LocalBlobStore,
              case_id: str, fact_id: str, value: object, *,
              session_id: str) -> dict:
    """Authenticated owner correction: typed, provenanced, audited, re-run."""
    case = _cases.get(conn, case_id)
    if case is None:
        raise AppError(ErrorCode.SCHEMA, "Case not found", status=404)
    if CaseState(case["state"]) not in EDITABLE_STATES:
        raise AppError(ErrorCode.STATE_TRANSITION,
                       f"Case in state {case['state']} cannot be edited")
    fact = _facts.get(conn, fact_id)
    if fact is None or fact["case_id"] != case_id:
        raise AppError(ErrorCode.SCHEMA, "Fact not found", status=404)
    if fact["field"] not in EDITABLE_FIELDS:
        raise AppError(ErrorCode.SCHEMA, f"Field '{fact['field']}' cannot be edited")
    clean = _validate_edit_value(fact["field"], value, settings)
    with transaction(conn):
        _facts.update_value(conn, fact_id=fact_id, value=clean,
                            status="UNCONFIRMED",
                            validated_by=[f"owner:{session_id}"])
        _facts.update_taint(conn, fact_id=fact_id,
                            taint=TaintClass.T0_OWNER.value,
                            validated_by=[f"owner:{session_id}"])
        audit_service.record(conn, audit_service.FACT_EDITED, case_id=case_id,
                             actor_type=ActorType.OWNER, actor_id=session_id,
                             payload={"fact_id": fact_id,
                                      "field": fact["field"]})
    # Re-run corroboration + policy deterministically (trusted event).
    return process.run_case(conn, settings, store, case_id, force=True)


def recover_stuck(conn: sqlite3.Connection, case_id: str) -> dict:
    """Move a case stuck in a transient state back to a safe checkpoint.

    Only READING/CORROBORATING/VERDICT older than the processing timeout
    may be reset to UPLOADED (ERROR path otherwise). Never fabricates
    verdicts or payments.
    """
    case = _cases.get(conn, case_id)
    if case is None:
        raise AppError(ErrorCode.SCHEMA, "Case not found", status=404)
    if CaseState(case["state"]) not in (CaseState.READING, CaseState.CORROBORATING,
                                        CaseState.VERDICT):
        raise AppError(ErrorCode.STATE_TRANSITION,
                       f"Case in state {case['state']} needs no recovery")
    with transaction(conn):
        _cases.update_state(conn, case_id=case_id, state=CaseState.UPLOADED.value,
                            now=SYSTEM_CLOCK.now().isoformat(),
                            expected_version=int(case["version"]),
                            error_code="E_RECOVERED",
                            error_summary="Recovered from stuck processing state")
        audit_service.record(conn, audit_service.READER_ERROR, case_id=case_id,
                             payload={"code": "E_RECOVERED"})
    updated = _cases.get(conn, case_id)
    assert updated is not None
    return updated


def get_artifact_content(conn: sqlite3.Connection, store: LocalBlobStore,
                         case_id: str, artifact_id: str) -> tuple[bytes, str]:
    """Case-bound artifact bytes + stored media type for owner preview.

    404 whether the case, the artifact, or the binding is wrong (no
    existence oracle). The media type is the server-sniffed value, never
    client-supplied.
    """
    case = _cases.get(conn, case_id)
    artifact = _artifacts.get(conn, artifact_id)
    if case is None or artifact is None or artifact["case_id"] != case_id:
        raise AppError(ErrorCode.SCHEMA, "Artifact not found", status=404)
    data = store.read_bytes(str(artifact["storage_key"]))
    return data, str(artifact["media_type"])


def dashboard_summary(conn: sqlite3.Connection,
                      *, recent_limit: int = 5) -> dict:
    """Read-only owner-console aggregates (existing repositories only)."""
    recent = _cases.list(conn, limit=recent_limit, offset=0)
    return {
        "cases_by_state": _cases.count_by_state(conn),
        "proposals_by_status": _proposals.count_by_status(conn),
        "payments_total": _payments.count_all(conn),
        "recent_cases": [{
            "id": case["id"], "state": case["state"],
            "created_at": case["created_at"],
            "updated_at": case["updated_at"],
        } for case in recent],
    }
