"""Case processing orchestrator: read -> validate -> corroborate -> verdict.

Synchronous in Phase 2 (no background queue claimed). Idempotent: repeat
calls on completed cases return the existing outcome. Bounded in-process
concurrency; optimistic versioning prevents stale overwrites.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from decimal import Decimal

from app.adapters.explanations import TemplateExplainer
from app.providers.registry import resolve_voice, resolve_vision
from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.security import bank_fingerprint
from app.domain.enums import CaseState, FieldStatus, Verdict
from app.domain.taint import TaintClass
from app.domain.verdicts import RuleResult
from app.pipeline import propose
from app.pipeline.corroborate import Corroboration, corroborate
from app.pipeline.evidence import LaneOutcome, LaneStatus
from app.pipeline.reader import get_reader
from app.pipeline.registry import VendorMatch, resolve_vendor
from app.pipeline.state_machine import check_transition
from app.pipeline.validate import validate_extraction
from app.schemas.invoice import InvoiceExtraction
from app.services import audit_service
from app.storage.artifacts import LocalBlobStore
from app.storage.database import transaction
from app.storage.repositories import (
    ArtifactRepository,
    CaseRepository,
    FactRepository,
    InvoiceIndexRepository,
    ProposalRepository,
    PaymentRepository,
    VerdictRepository,
)

logger = get_logger("airlock.pipeline")

_cases = CaseRepository()
_artifacts = ArtifactRepository()
_facts = FactRepository()
_verdicts = VerdictRepository()
_proposals = ProposalRepository()
_payments = PaymentRepository()
_index = InvoiceIndexRepository()
_explainer = TemplateExplainer()

COMPLETED_STATES = frozenset({
    CaseState.PROPOSED, CaseState.CONFIRMED, CaseState.EXECUTED,
    CaseState.REJECTED, CaseState.NEEDS_REVIEW,
})

_semaphores: dict[int, threading.BoundedSemaphore] = {}
_semaphores_lock = threading.Lock()

VOICE_INSTRUCTION_MARKERS = ("ignor", "overrid", "bypass", "instead",
                             "do not verify", "don't verify", "keep secret")
_AMOUNT_RE = re.compile(r"\d+\.\d{2}")


def _limiter(max_concurrent: int) -> threading.BoundedSemaphore:
    with _semaphores_lock:
        semaphore = _semaphores.get(max_concurrent)
        if semaphore is None:
            semaphore = threading.BoundedSemaphore(max_concurrent)
            _semaphores[max_concurrent] = semaphore
        return semaphore


def _transition(conn: sqlite3.Connection, case: dict, nxt: CaseState,
                *, error_code: str | None = None,
                error_summary: str | None = None) -> dict:
    current = CaseState(case["state"])
    check_transition(current, nxt)
    now = SYSTEM_CLOCK.now().isoformat()
    ok = _cases.update_state(conn, case_id=case["id"], state=nxt.value,
                             now=now, expected_version=int(case["version"]),
                             error_code=error_code,
                             error_summary=error_summary)
    if not ok:
        raise AppError(ErrorCode.CONFLICT,
                       "Case was modified concurrently; retry the request")
    updated = _cases.get(conn, case["id"])
    assert updated is not None
    return updated


_PO_TOKEN_RE = re.compile(r"PO-[A-Za-z0-9][A-Za-z0-9-]{0,62}")
_INV_TOKEN_RE = re.compile(r"INV-[A-Za-z0-9][A-Za-z0-9-]{0,62}")
_MAX_REF_ECHO = 40


def _short_ref(value: str) -> str:
    # Conflict details travel into audit payloads and API responses:
    # transcript-controlled tokens are charset-safe but still truncated.
    return value[:_MAX_REF_ECHO]


def voice_conflict_details(transcript: str,
                           extraction: InvoiceExtraction) -> list[str]:
    """Deterministic transcript-vs-invoice conflict reasons (bounded).

    Each signal fires only when the transcript affirmatively states a
    conflicting fact; an absent mention is never a conflict. Reasons are
    short static templates with truncated token echoes (safe for audit).
    """
    details: list[str] = []
    lowered = transcript.lower()
    for marker in VOICE_INSTRUCTION_MARKERS:
        if marker in lowered:
            details.append("transcript contains instruction-like language")
            break
    # The regex guarantees Decimal-parseable matches; no fallback needed.
    for match in _AMOUNT_RE.findall(transcript):
        if Decimal(match) != extraction.total:
            details.append(f"transcript amount {match} != invoice total "
                           f"{extraction.total}")
            break
    if extraction.po_reference:
        claimed = extraction.po_reference.strip().upper()
        for token in _PO_TOKEN_RE.findall(transcript.upper()):
            if token != claimed:
                details.append(
                    f"transcript references PO {_short_ref(token)} but "
                    f"invoice claims PO "
                    f"{_short_ref(extraction.po_reference.strip())}")
                break
    claimed_inv = extraction.invoice_number.strip().upper()
    for token in _INV_TOKEN_RE.findall(transcript.upper()):
        if token != claimed_inv:
            details.append(
                f"transcript references invoice {_short_ref(token)} but "
                f"processing invoice "
                f"{_short_ref(extraction.invoice_number.strip())}")
            break
    return details


def detect_voice_conflict(transcript: str, extraction: InvoiceExtraction) -> bool:
    return bool(voice_conflict_details(transcript, extraction))


def _verified_bytes(artifact: dict, data: bytes) -> bytes:
    """Bind blob bytes to the recorded intake hash (replacement/tamper
    between intake and processing fails closed instead of silently
    processing different bytes)."""
    recorded = artifact.get("sha256")
    if not recorded:
        raise AppError(ErrorCode.DATABASE,
                       "Artifact record is missing its content hash")
    if hashlib.sha256(data).hexdigest() != recorded:
        raise AppError(ErrorCode.DATABASE,
                       "Artifact bytes do not match the recorded hash")
    return data


def _invoice_bytes(conn: sqlite3.Connection, store: LocalBlobStore,
                   case_id: str) -> tuple[dict, bytes]:
    for artifact in _artifacts.list_for_case(conn, case_id):
        if artifact["kind"] == "invoice":
            data = store.read_bytes(artifact["storage_key"])
            return artifact, _verified_bytes(artifact, data)
    raise AppError(ErrorCode.UPLOAD, "Case has no invoice artifact")


def _optional_bytes(conn: sqlite3.Connection, store: LocalBlobStore,
                    case_id: str, kind: str) -> tuple[dict, bytes] | None:
    for artifact in _artifacts.list_for_case(conn, case_id):
        if artifact["kind"] == kind:
            data = store.read_bytes(artifact["storage_key"])
            return artifact, _verified_bytes(artifact, data)
    return None


def run_case(conn: sqlite3.Connection, settings: Settings, store: LocalBlobStore,
             case_id: str, *, force: bool = False) -> dict:
    """Process a case through verdict/proposal. Returns the case summary."""
    case = _cases.get(conn, case_id)
    if case is None:
        raise AppError(ErrorCode.SCHEMA, "Case not found", status=404)
    if not force and CaseState(case["state"]) in COMPLETED_STATES:
        return summarize(conn, settings, case_id)
    if not force and CaseState(case["state"]) not in (
            CaseState.UPLOADED, CaseState.ERROR, CaseState.EXPIRED):
        # REJECTED/NEEDS_REVIEW need a trusted event (fact edit) to re-run.
        if CaseState(case["state"]) in (CaseState.REJECTED, CaseState.NEEDS_REVIEW):
            return summarize(conn, settings, case_id)
        raise AppError(ErrorCode.STATE_TRANSITION,
                       f"Case is {case['state']}; processing is already underway or finished")

    limiter = _limiter(max(1, settings.max_concurrent_processing))
    if not limiter.acquire(timeout=5):
        raise AppError(ErrorCode.RATE_LIMIT, "Processing capacity exhausted; retry shortly")
    try:
        from app.services import vendor_service
        vendor_service.activate_all_due(conn)
        return _run_inner(conn, settings, store, case, force=force)
    finally:
        limiter.release()


def _run_inner(conn: sqlite3.Connection, settings: Settings,
               store: LocalBlobStore, case: dict, *, force: bool) -> dict:
    case = _transition(conn, case, CaseState.READING)
    _cases.mark_processing(conn, case_id=case["id"],
                           now=SYSTEM_CLOCK.now().isoformat())
    reprocess = force and bool(_facts.list_for_case(conn, case["id"]))
    try:
        presented_fp: str | None = None
        if reprocess:
            extraction, schema_errors, producer, presented_fp = _reconstruct_from_facts(
                conn, case["id"])
        else:
            extraction, schema_errors, producer = _read_and_validate(
                conn, settings, store, case["id"])
        schema_ok = extraction is not None
        vendor_match = _resolve(conn, extraction)
        sam_count, sam_tolerance, sam_error, sam_required, sam_lane = _gather_sam(
            conn, settings, store, case["id"], vendor_match)
        voice_conflicts, voice_lane = _gather_voice(
            conn, settings, store, case["id"], extraction)
        corroboration = _corroborate(
            conn, settings, extraction, vendor_match, sam_count=sam_count,
            sam_item_tolerance=sam_tolerance, sam_error=sam_error,
            voice_conflicts=voice_conflicts, voice_lane=voice_lane,
            sam_lane=sam_lane, presented_bank_fp=presented_fp)
        required_errors = _required_verifier_errors(
            corroboration, sam_error=sam_error if sam_required else None)
        verdict, rules = _evaluate(
            settings, extraction, corroboration, schema_ok=schema_ok,
            schema_errors=schema_errors, required_errors=required_errors,
            voice_lane=voice_lane, sam_lane=sam_lane)
        _persist_outcome(conn, settings, case, extraction=extraction,
                         schema_ok=schema_ok, vendor_match=vendor_match,
                         corroboration=corroboration, verdict=verdict,
                         rules=rules, producer=producer,
                         sam_required=sam_required)
    except AppError as exc:
        fresh = _cases.get(conn, case["id"])
        assert fresh is not None
        try:
            _transition(conn, fresh, CaseState.ERROR,
                        error_code=exc.code,
                        error_summary=exc.message[:300])
        except AppError:
            pass
        with transaction(conn):
            audit_service.record(conn, audit_service.READER_ERROR,
                                 case_id=case["id"],
                                 payload={"code": exc.code,
                                          "message": exc.message[:200]})
        raise AppError(exc.code, exc.message, details=exc.details,
                       status=exc.status) from exc
    except Exception as exc:  # fail closed on unexpected errors
        fresh = _cases.get(conn, case["id"])
        assert fresh is not None
        logger.error("processing failed for case %s: %r", case["id"], exc)
        try:
            # Generic summary only: raw exception text may carry paths or
            # driver internals, and error_summary is served via the API.
            _transition(conn, fresh, CaseState.ERROR,
                        error_code=ErrorCode.INTERNAL,
                        error_summary="Processing failed")
        except AppError:
            pass
        with transaction(conn):
            audit_service.record(conn, audit_service.READER_ERROR,
                                 case_id=case["id"],
                                 payload={"code": ErrorCode.INTERNAL})
        raise AppError(ErrorCode.INTERNAL, "Processing failed") from exc
    return summarize(conn, settings, case["id"])


def _safe_error_details(exc: AppError, *, limit: int = 8) -> list[dict]:
    """Structured, bounded audit copy of validation failure details.

    `AppError.details` entries are `{code, message}` dicts with static,
    client-safe messages (Pydantic/validator text); anything else is
    coerced to a code-only entry so model-controlled text can never
    leak into the audit trail unbounded.
    """
    safe: list[dict] = []
    details = exc.details if isinstance(exc.details, list) else []
    for entry in details[:limit]:
        if isinstance(entry, dict) and isinstance(entry.get("code"), str):
            item: dict = {"code": entry["code"][:80]}
            if isinstance(entry.get("message"), str):
                item["message"] = entry["message"][:200]
            safe.append(item)
        else:
            safe.append({"code": str(entry)[:80]})
    if not safe:
        safe.append({"code": exc.code, "message": exc.message[:200]})
    return safe


def _read_and_validate(conn: sqlite3.Connection, settings: Settings,
                       store: LocalBlobStore, case_id: str):
    artifact, data = _invoice_bytes(conn, store, case_id)
    with transaction(conn):
        audit_service.record(conn, audit_service.READER_STARTED, case_id=case_id,
                             payload={"artifact_id": artifact["id"],
                                      "artifact_sha256": artifact["sha256"],
                                      "artifact_kind": artifact["kind"]})
    reader = get_reader(settings)
    producer = {"adapter": reader.adapter_id,
                "adapter_version": reader.adapter_version,
                "model_id": None,
                "prompt_version": None,
                "extracted_at": SYSTEM_CLOCK.now().isoformat(),
                "request_id": None}
    try:
        result = reader.read(data)
    except AppError as exc:
        with transaction(conn):
            audit_service.record(conn, audit_service.READER_ERROR, case_id=case_id,
                                 payload={"code": exc.code})
        if exc.code == ErrorCode.SCHEMA:
            # Malformed reader output is an R8 schema failure (DENY verdict),
            # not a processing error.
            with transaction(conn):
                audit_service.record(conn, audit_service.EXTRACTION_REJECTED,
                                     case_id=case_id,
                                     payload={"errors": _safe_error_details(exc)})
            return None, [exc.message], producer
        raise
    producer["model_id"] = result.model_id
    producer["prompt_version"] = result.prompt_version
    producer["request_id"] = result.request_id
    producer["evidence_pages"] = result.evidence_pages
    with transaction(conn):
        audit_service.record(conn, audit_service.READER_COMPLETED, case_id=case_id,
                             payload={"scenario": result.scenario,
                                      "adapter": reader.adapter_id,
                                      "model": result.model_id,
                                      "request_id": result.request_id,
                                      "usage": result.usage,
                                      "warnings": list(result.warnings)[:5]})
    try:
        extraction = validate_extraction(result.payload)
    except AppError as exc:
        with transaction(conn):
            audit_service.record(conn, audit_service.EXTRACTION_REJECTED,
                                 case_id=case_id,
                                 payload={"errors": _safe_error_details(exc)})
        return None, [exc.message], producer
    with transaction(conn):
        audit_service.record(conn, audit_service.EXTRACTION_VALIDATED,
                             case_id=case_id, payload={})
    return extraction, [], producer


def _reconstruct_from_facts(conn: sqlite3.Connection, case_id: str):
    """Rebuild extraction from current (possibly owner-edited) facts."""
    values = {row["field"]: json.loads(str(row["value_json"]))
              for row in _facts.list_for_case(conn, case_id)}
    bank = values.get("bank") or {}
    payload = {
        "vendor_name": values.get("vendor_name"),
        "invoice_number": values.get("invoice_number"),
        "issue_date": values.get("issue_date"),
        "due_date": values.get("due_date"),
        "currency": values.get("currency"),
        "subtotal": values.get("subtotal"),
        "tax": values.get("tax"),
        "total": values.get("total"),
        "bank_reference": values.get("bank_reference"),
        "po_reference": values.get("po_reference"),
        "line_items": values.get("line_items"),
        "_presented_bank_fp": bank.get("fingerprint"),
    }
    producer = {"adapter": "fact-reconstruction",
                "adapter_version": "2.0.0",
                "model_id": None, "prompt_version": None,
                "extracted_at": SYSTEM_CLOCK.now().isoformat()}
    presented = payload.pop("_presented_bank_fp")
    try:
        extraction = validate_extraction(payload)
    except AppError as exc:
        return None, [exc.message], producer, None
    with transaction(conn):
        audit_service.record(conn, audit_service.EXTRACTION_VALIDATED,
                             case_id=case_id,
                             payload={"source": "owner-facts"})
    return extraction, [], producer, presented


def _resolve(conn: sqlite3.Connection,
             extraction: InvoiceExtraction | None) -> VendorMatch:
    if extraction is None:
        return VendorMatch(vendor=None, candidates=[], normalized="")
    match = resolve_vendor(conn, extraction.vendor_name)
    with transaction(conn):
        if match.vendor is not None:
            audit_service.record(conn, audit_service.VENDOR_MATCH,
                                 payload={"vendor_id": match.vendor["vendor_id"]})
        elif match.ambiguous:
            audit_service.record(conn, audit_service.VENDOR_AMBIGUITY,
                                 payload={"candidates": len(match.candidates)})
    return match


def _gather_sam(conn: sqlite3.Connection, settings: Settings,
                store: LocalBlobStore, case_id: str,
                vendor_match: VendorMatch):
    """Segment delivery evidence; never confirm from unevaluated bytes.

    Returns (count, tolerance, error, required, lane). A completed empty
    stream yields count 0 (compared, usually a conflict); an uploaded
    artifact that could not be segmented is NOT_EVALUATED with an
    explicit audit record, never "no delivery evidence".
    """
    missing = LaneOutcome(lane="sam", status=LaneStatus.MISSING,
                          detail="no delivery evidence uploaded")
    try:
        found = _optional_bytes(conn, store, case_id, "delivery")
    except AppError as exc:
        # Required delivery evidence failed its recorded integrity
        # check (or is unreadable): record a failed required-verifier
        # result so R9 denies. The mismatched bytes are never sent to
        # SAM or any other verifier.
        with transaction(conn):
            audit_service.record(conn, audit_service.SAM_EVIDENCE,
                                 case_id=case_id,
                                 payload={"status": LaneStatus.FAILED.value,
                                          "error": exc.message[:200],
                                          "error_code": _provider_error_code(exc)})
        lane = LaneOutcome(lane="sam", status=LaneStatus.FAILED,
                           detail="delivery artifact unreadable")
        return None, None, exc.message[:200], True, lane
    if found is None:
        return None, None, None, False, missing
    artifact, delivery_bytes = found
    vendor = vendor_match.vendor
    if vendor is None:
        # R1 already denies; SAM genuinely cannot run without a trusted
        # catalogue label — but the bytes WERE uploaded, so say so.
        reason = "delivery uploaded; vendor unresolved, no concept to prompt"
        with transaction(conn):
            audit_service.record(conn, audit_service.SAM_EVIDENCE,
                                 case_id=case_id,
                                 payload={"status": LaneStatus.NOT_EVALUATED.value,
                                          "artifact_id": artifact["id"],
                                          "artifact_sha256": artifact["sha256"],
                                          "reason": reason})
        return None, None, None, False, LaneOutcome(
            lane="sam", status=LaneStatus.NOT_EVALUATED, detail=reason)
    catalogue = json.loads(str(vendor.get("catalogue_json") or "[]"))
    if not catalogue:
        reason = "delivery uploaded; vendor catalogue is empty"
        with transaction(conn):
            audit_service.record(conn, audit_service.SAM_EVIDENCE,
                                 case_id=case_id,
                                 payload={"status": LaneStatus.NOT_EVALUATED.value,
                                          "artifact_id": artifact["id"],
                                          "artifact_sha256": artifact["sha256"],
                                          "reason": reason})
        return None, None, None, False, LaneOutcome(
            lane="sam", status=LaneStatus.NOT_EVALUATED, detail=reason)
    item = catalogue[0]
    try:
        segmenter = resolve_vision(settings)
        evidence = segmenter.count(
            delivery_bytes, catalogue_item_id=str(item.get("item_id", "")),
            catalogue_label=str(item.get("label", "")))
    except AppError as exc:
        with transaction(conn):
            audit_service.record(conn, audit_service.SAM_EVIDENCE,
                                 case_id=case_id,
                                 payload={"status": LaneStatus.FAILED.value,
                                          "artifact_id": artifact["id"],
                                          "artifact_sha256": artifact["sha256"],
                                          "error": exc.message[:200],
                                          "error_code": _provider_error_code(exc)})
        lane = LaneOutcome(lane="sam", status=LaneStatus.FAILED,
                           detail="segmentation failed; not evaluated")
        return None, None, exc.message[:200], True, lane
    with transaction(conn):
        audit_service.record(
            conn, audit_service.SAM_EVIDENCE, case_id=case_id,
            payload={"status": LaneStatus.EVALUATED.value,
                     "artifact_id": artifact["id"],
                     "artifact_sha256": artifact["sha256"],
                     "count": evidence.count,
                     "item_id": evidence.catalogue_item_id,
                     "adapter": segmenter.adapter_id,
                     "model": evidence.model_id,
                     "frames": evidence.frames_observed,
                     "boxes": len(evidence.boxes),
                     "request_id": evidence.request_id,
                     "usage": evidence.usage,
                     "warnings": list(evidence.warnings)[:5]})
    tolerance = item.get("tolerance")
    lane = LaneOutcome(lane="sam", status=LaneStatus.EVALUATED)
    return (evidence.count,
            int(tolerance) if tolerance is not None else None, None, True,
            lane)


def _provider_error_code(exc: AppError) -> str:
    """Machine-readable failure category for audit/UI (never a secret)."""
    details = exc.details if isinstance(exc.details, list) else []
    if details and isinstance(details[0], dict):
        code = details[0].get("code")
        if isinstance(code, str) and code:
            return code[:64]
    return exc.code


def _gather_voice(conn: sqlite3.Connection, settings: Settings,
                  store: LocalBlobStore, case_id: str,
                  extraction: InvoiceExtraction | None
                  ) -> tuple[bool, LaneOutcome]:
    """Transcribe voice evidence independently of invoice extraction.

    The voice artifact is always sent to the configured transcriber when
    present — even when invoice extraction failed — so its processing
    status is explicit. Only the deterministic conflict comparison needs
    the extraction; without it the lane is NOT_EVALUATED, never clean.
    Voice stays optional corroboration: failures are recorded, never
    fatal to the case.
    """
    missing = LaneOutcome(lane="voice", status=LaneStatus.MISSING,
                          detail="no voice evidence uploaded")
    try:
        found = _optional_bytes(conn, store, case_id, "voice")
    except AppError as exc:
        # Optional voice evidence failed its integrity check: record
        # and continue without it. The mismatched bytes are never
        # transcribed.
        with transaction(conn):
            audit_service.record(conn, audit_service.VOICE_TRANSCRIPT,
                                 case_id=case_id,
                                 payload={"status": LaneStatus.FAILED.value,
                                          "error": exc.message[:200],
                                          "error_code": _provider_error_code(exc)})
        return False, LaneOutcome(lane="voice", status=LaneStatus.FAILED,
                                  detail=f"voice artifact unreadable: {exc.code}")
    if found is None:
        return False, missing
    artifact, voice_bytes = found
    try:
        transcriber = resolve_voice(settings)
        transcript = transcriber.transcribe(voice_bytes)
    except AppError as exc:
        # Voice is optional corroboration: failure is recorded, never fatal.
        with transaction(conn):
            audit_service.record(conn, audit_service.VOICE_TRANSCRIPT,
                                 case_id=case_id,
                                 payload={"status": LaneStatus.FAILED.value,
                                          "artifact_id": artifact["id"],
                                          "artifact_sha256": artifact["sha256"],
                                          "error": exc.message[:200],
                                          "error_code": _provider_error_code(exc)})
        return False, LaneOutcome(lane="voice", status=LaneStatus.FAILED,
                                  detail="transcription failed; not evaluated")
    if not transcript.text.strip():
        # Silence is never confirmation: recorded as empty, unevaluated.
        with transaction(conn):
            audit_service.record(
                conn, audit_service.VOICE_TRANSCRIPT, case_id=case_id,
                payload={"status": LaneStatus.EMPTY.value,
                         "artifact_id": artifact["id"],
                         "artifact_sha256": artifact["sha256"],
                         "reason": "empty transcript; nothing to compare",
                         "chars": len(transcript.text),
                         "conflict": False,
                         "adapter": transcriber.adapter_id,
                         "model": transcript.model_id,
                         "turns": len(transcript.turns),
                         "request_id": transcript.request_id,
                         "usage": transcript.usage,
                         "warnings": list(transcript.warnings)[:5]})
        return False, LaneOutcome(lane="voice", status=LaneStatus.EMPTY,
                                  detail="empty transcript; nothing to compare")
    if extraction is None:
        with transaction(conn):
            audit_service.record(
                conn, audit_service.VOICE_TRANSCRIPT, case_id=case_id,
                payload={"status": LaneStatus.NOT_EVALUATED.value,
                         "artifact_id": artifact["id"],
                         "artifact_sha256": artifact["sha256"],
                         "reason": "transcribed; comparison skipped "
                                   "without an extraction",
                         "chars": len(transcript.text),
                         "conflict": False,
                         "adapter": transcriber.adapter_id,
                         "model": transcript.model_id,
                         "turns": len(transcript.turns),
                         "request_id": transcript.request_id,
                         "usage": transcript.usage,
                         "warnings": list(transcript.warnings)[:5]})
        return False, LaneOutcome(
            lane="voice", status=LaneStatus.NOT_EVALUATED,
            detail="transcribed; comparison skipped without an extraction")
    reasons = voice_conflict_details(transcript.text, extraction)
    conflict = bool(reasons)
    with transaction(conn):
        audit_service.record(conn, audit_service.VOICE_TRANSCRIPT,
                             case_id=case_id,
                             payload={"status": LaneStatus.EVALUATED.value,
                                      "artifact_id": artifact["id"],
                                      "artifact_sha256": artifact["sha256"],
                                      "chars": len(transcript.text),
                                      "conflict": conflict,
                                      "conflict_detail": reasons[:3],
                                      "adapter": transcriber.adapter_id,
                                      "model": transcript.model_id,
                                      "turns": len(transcript.turns),
                                      "request_id": transcript.request_id,
                                      "usage": transcript.usage,
                                      "warnings": list(transcript.warnings)[:5]})
    return conflict, LaneOutcome(
        lane="voice", status=LaneStatus.EVALUATED, conflict=conflict,
        detail="; ".join(reasons[:3]))


def _corroborate(conn: sqlite3.Connection, settings: Settings,
                 extraction: InvoiceExtraction | None,
                 vendor_match: VendorMatch, **kwargs) -> Corroboration | None:
    if extraction is None:
        return None
    return corroborate(conn, settings, extraction, vendor_match, **kwargs)


def _required_verifier_errors(corroboration: Corroboration | None, *,
                              sam_error: str | None) -> list[str]:
    errors: list[str] = []
    if corroboration is not None:
        errors.extend(corroboration.verifier_errors)
    if sam_error is not None:
        errors.append(f"sam-verifier: {sam_error}")
    return errors


def _evaluate(settings: Settings, extraction, corroboration, *,
              schema_ok: bool, schema_errors: list[str],
              required_errors: list[str],
              voice_lane=None, sam_lane=None):
    from app.pipeline.policy import evaluate_policy
    return evaluate_policy(settings, extraction, corroboration,
                           schema_ok=schema_ok, schema_errors=schema_errors,
                           required_verifier_errors=required_errors,
                           voice_lane=voice_lane, sam_lane=sam_lane)


def _persist_outcome(conn: sqlite3.Connection, settings: Settings, case: dict, *,
                     extraction: InvoiceExtraction | None, schema_ok: bool,
                     vendor_match: VendorMatch,
                     corroboration: Corroboration | None,
                     verdict: Verdict, rules: list[RuleResult],
                     producer: dict, sam_required: bool) -> None:
    now = SYSTEM_CLOCK.now().isoformat()
    verdict_id = new_id("verdict")
    reasons = [f"{rule.rule_id}:{rule.reason_code}" for rule in rules
               if not rule.passed] or ["all-checks-passed"]
    rule_ids = [rule.rule_id for rule in rules if not rule.passed]
    rule_details = [
        {"rule_id": rule.rule_id, "passed": rule.passed,
         "reason_code": rule.reason_code, "message": rule.message,
         "evidence": rule.evidence}
        for rule in rules
    ]
    with transaction(conn):
        case = _transition(conn, case, CaseState.CORROBORATING)
        audit_service.record(conn, audit_service.CORROBORATION_COMPLETED,
                             case_id=case["id"],
                             payload={"fields": len(corroboration.outcomes)
                                      if corroboration else 0})
        case = _transition(conn, case, CaseState.VERDICT)
        if extraction is not None:
            # Preserve T0 markers for owner-edited fields across reprocessing.
            owner_fields = {row["field"]: json.loads(str(row["validated_by"]))
                            for row in _facts.list_for_case(conn, case["id"])
                            if row["taint_class"] == TaintClass.T0_OWNER.value}
            _facts.delete_for_case(conn, case["id"])
            _store_facts(conn, settings, case["id"], extraction, producer,
                         corroboration, now)
            for row in _facts.list_for_case(conn, case["id"]):
                if row["field"] in owner_fields:
                    _facts.update_taint(conn, fact_id=row["id"],
                                        taint=TaintClass.T0_OWNER.value,
                                        validated_by=owner_fields[row["field"]])
        _verdicts.create(conn, verdict_id=verdict_id, case_id=case["id"],
                         verdict=verdict.value, reasons=reasons,
                         rule_ids=rule_ids, rule_details=rule_details,
                         policy_version=settings.policy_version, now=now)
        audit_service.record(conn, audit_service.POLICY_EVALUATED,
                             case_id=case["id"],
                             payload={"verdict": verdict.value,
                                      "failed_rules": rule_ids})
        audit_service.record(conn, audit_service.VERDICT_CREATED,
                             case_id=case["id"],
                             payload={"verdict_id": verdict_id,
                                      "verdict": verdict.value})
        for stale in _proposals.list_pending_for_case(conn, case["id"]):
            _proposals.set_status(conn, stale["proposal_id"], "REJECTED")
            audit_service.record(conn, audit_service.PROPOSAL_REJECTED,
                                 case_id=case["id"],
                                 payload={"proposal_id": stale["proposal_id"],
                                          "reason": "superseded-by-reprocess"})
        _index.delete_proposed_for_case(conn, case["id"])
        if verdict == Verdict.ALLOW_PROPOSAL:
            assert extraction is not None and vendor_match.vendor is not None
            try:
                proposal = propose.build_proposal(
                    conn, settings, case_id=case["id"], extraction=extraction,
                    vendor=vendor_match.vendor, verdict_id=verdict_id,
                    rules=rules)
            except sqlite3.IntegrityError as exc:
                # Lost a duplicate-key race with a concurrent case: the
                # invoice is a duplicate; a retry will DENY via R4.
                raise AppError(ErrorCode.DUPLICATE,
                               "Duplicate invoice detected at proposal time") from exc
            audit_service.record(conn, audit_service.PROPOSAL_CREATED,
                                 case_id=case["id"],
                                 payload={"proposal_id": proposal["proposal_id"]})
            case = _transition(conn, case, CaseState.PROPOSED)
        elif verdict == Verdict.ESCALATE:
            case = _transition(conn, case, CaseState.NEEDS_REVIEW)
        else:
            case = _transition(conn, case, CaseState.REJECTED)
        _cases.mark_completed(conn, case_id=case["id"], now=now)


def _store_facts(conn: sqlite3.Connection, settings: Settings, case_id: str,
                 extraction: InvoiceExtraction, producer: dict,
                 corroboration: Corroboration | None, now: str) -> None:
    from app.domain.facts import Fact, Producer, Source
    artifacts = _artifacts.list_for_case(conn, case_id)
    invoice = next((a for a in artifacts if a["kind"] == "invoice"), artifacts[0])
    raw_pages = producer.get("evidence_pages")
    evidence_pages = raw_pages if isinstance(raw_pages, dict) else {}
    made_by = Producer(adapter=str(producer.get("adapter", "")),
                       adapter_version=str(producer.get("adapter_version", "")),
                       model_id=producer.get("model_id"),
                       prompt_version=producer.get("prompt_version"),
                       extracted_at=producer.get("extracted_at"),
                       request_id=producer.get("request_id"))
    outcomes = corroboration.outcomes if corroboration else {}
    presented_fp: str | None = None
    if extraction.bank_reference and settings.bank_hash_key:
        try:
            presented_fp = bank_fingerprint(extraction.bank_reference,
                                            settings.bank_hash_key)
        except ValueError:
            presented_fp = None
    values: dict[str, tuple[object, str]] = {
        "vendor_name": (extraction.vendor_name, "vendor"),
        "invoice_number": (extraction.invoice_number, "duplicate"),
        "issue_date": (extraction.issue_date.isoformat(), "dates"),
        "due_date": (extraction.due_date.isoformat(), "dates"),
        "currency": (extraction.currency, "dates"),
        "subtotal": (str(extraction.subtotal), "subtotal"),
        "tax": (str(extraction.tax), "tax"),
        "total": (str(extraction.total), "total"),
        "bank": ({"fingerprint": presented_fp,
                  "match": corroboration.bank_match if corroboration else None},
                 "bank"),
        "po_reference": (extraction.po_reference, "po"),
        "line_items": ([{"description": item.description,
                         "quantity": str(item.quantity),
                         "unit_price": str(item.unit_price),
                         "catalogue_item_id": item.catalogue_item_id,
                         "extracted_item_id": item.extracted_item_id}
                        for item in extraction.line_items], "total"),
    }
    for field_name, (value, outcome_key) in values.items():
        outcome = outcomes.get(outcome_key)
        status = outcome.status.value if outcome else FieldStatus.UNCONFIRMED.value
        validators = outcome.validators if outcome else []
        page = evidence_pages.get(field_name)
        if (not isinstance(page, int) or isinstance(page, bool)
                or page < 1):
            page = None
        source = Source(artifact_id=invoice["id"],
                        artifact_kind=invoice["kind"], page=page)
        fact = Fact(id=new_id("fact"), case_id=case_id, field=field_name,
                    value=value, source=source, producer=made_by,
                    taint=TaintClass.T2_MODEL,
                    validation_status=FieldStatus(status),
                    validated_by=validators, created_at=now)
        _facts.create(conn, fact_id=fact.id, case_id=fact.case_id,
                      field=fact.field, value=fact.value,
                      source=fact.source.to_dict(),
                      producer=fact.producer.to_dict(),
                      taint=fact.taint.value,
                      status=fact.validation_status.value,
                      validated_by=fact.validated_by, now=now)


def summarize(conn: sqlite3.Connection, settings: Settings, case_id: str) -> dict:
    case = _cases.get(conn, case_id)
    if case is None:
        raise AppError(ErrorCode.SCHEMA, "Case not found", status=404)
    verdict = _verdicts.latest_for_case(conn, case_id)
    proposal = _proposals.get_by_case(conn, case_id)
    explanation = None
    if verdict is not None:
        details = json.loads(str(verdict["rule_details_json"]))
        rules = [RuleResult(rule_id=d["rule_id"], rule_version=settings.policy_version,
                            passed=d["passed"], outcome=None,
                            reason_code=d["reason_code"], message=d["message"],
                            evidence=d.get("evidence", {}))
                 for d in details]
        explanation = _explainer.explain(Verdict(verdict["verdict"]), rules)
    return {
        "case": case,
        "artifacts": _artifacts.list_for_case(conn, case_id),
        "facts": _facts.list_for_case(conn, case_id),
        "verdict": verdict,
        "proposal": proposal,
        "payments": _payments.list_for_case(conn, case_id),
        "explanation": explanation,
    }
