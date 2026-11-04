"""Secure intake: validate uploads, store artifacts, create cases."""

from __future__ import annotations

import hashlib
import sqlite3

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.domain.enums import ActorType, CaseState
from app.services import audit_service
from app.storage.artifacts import LocalBlobStore, intake_bytes, sanitize_filename
from app.storage.database import transaction
from app.storage.repositories import ArtifactRepository, CaseRepository

_cases = CaseRepository()
_artifacts = ArtifactRepository()

KIND_BY_MEDIA = {
    "application/pdf": "invoice",
    "image/png": "invoice",
    "image/jpeg": "invoice",
}


def classify_upload(media_type: str, field_name: str) -> str:
    if field_name == "delivery":
        if media_type not in ("image/png", "image/jpeg", "video/mp4"):
            raise AppError(ErrorCode.UPLOAD, "Delivery evidence must be an image or MP4")
        return "delivery"
    if field_name == "voice":
        if media_type != "audio/wav":
            raise AppError(ErrorCode.UPLOAD, "Voice note must be a WAV file")
        return "voice"
    if media_type in KIND_BY_MEDIA:
        return "invoice"
    raise AppError(ErrorCode.UPLOAD, "Invoice must be a PDF or image")


def create_case(conn: sqlite3.Connection, settings: Settings, store: LocalBlobStore,
                files: list[tuple[str, str, bytes]], *,
                idempotency_key: str | None = None) -> dict:
    """Validate files, persist artifacts + case atomically.

    `files` is a list of (field_name, filename, bytes). Returns the case row.
    Duplicate idempotency keys return the original case (no second case).
    """
    if idempotency_key:
        existing = _cases.get_by_idempotency(conn, idempotency_key)
        if existing is not None:
            return existing
    if not files:
        raise AppError(ErrorCode.UPLOAD, "At least one invoice file is required")
    if len(files) > settings.max_files_per_case:
        raise AppError(ErrorCode.UPLOAD,
                       f"Too many files: {len(files)} (limit {settings.max_files_per_case})")
    field_names = [item[0] for item in files]
    if "invoice" not in field_names:
        raise AppError(ErrorCode.UPLOAD, "Field 'invoice' is required")
    unexpected = [name for name in field_names
                  if name not in ("invoice", "delivery", "voice")]
    if unexpected:
        raise AppError(ErrorCode.UPLOAD, f"Unexpected upload field: {unexpected[0]}")

    stored: list[dict] = []
    for field_name, filename, data in files:
        clean_name = sanitize_filename(filename)
        digest = hashlib.sha256(data).hexdigest()
        duplicate = _artifacts.find_by_sha(conn, digest)
        if duplicate is not None:
            stored.append({"field": field_name, "filename": clean_name,
                           "duplicate_of": duplicate["id"],
                           "storage_key": duplicate["storage_key"],
                           "sha256": digest,
                           "media_type": duplicate["media_type"],
                           "extension": duplicate["extension"],
                           "size_bytes": len(data)})
            continue
        artifact = intake_bytes(data, filename=clean_name, settings=settings,
                                store=store)
        stored.append({"field": field_name, "filename": clean_name,
                       "duplicate_of": None,
                       "storage_key": artifact.storage_key,
                       "sha256": artifact.sha256,
                       "media_type": artifact.media_type,
                       "extension": artifact.extension,
                       "size_bytes": artifact.size_bytes})

    now = SYSTEM_CLOCK.now().isoformat()
    case_id = new_id("case")
    try:
        with transaction(conn):
            _cases.create(conn, case_id=case_id, state=CaseState.UPLOADED.value,
                          now=now, idempotency_key=idempotency_key)
            audit_service.record(conn, audit_service.CASE_CREATED,
                                 case_id=case_id,
                                 actor_type=ActorType.SYSTEM,
                                 payload={"files": len(stored)})
            for item in stored:
                kind = classify_upload(item["media_type"], item["field"])
                _artifacts.create(
                    conn, artifact_id=new_id("art"), case_id=case_id,
                    sha256=item["sha256"], kind=kind,
                    media_type=item["media_type"],
                    extension=item["extension"],
                    size_bytes=item["size_bytes"],
                    storage_key=item["storage_key"], now=now)
                if item["duplicate_of"] is not None:
                    audit_service.record(
                        conn, audit_service.ARTIFACT_DEDUPLICATED,
                        case_id=case_id,
                        payload={"sha256": item["sha256"],
                                 "duplicate_of": item["duplicate_of"]})
                else:
                    audit_service.record(
                        conn, audit_service.ARTIFACT_UPLOADED, case_id=case_id,
                        payload={"sha256": item["sha256"], "kind": kind,
                                 "size_bytes": item["size_bytes"]})
    except Exception:
        # Roll back the stored blobs for this failed intake (deduplicated
        # blobs are shared and must be kept).
        for item in stored:
            if item["duplicate_of"] is None:
                try:
                    store.delete(item["storage_key"])
                except AppError:
                    pass
        raise
    row = _cases.get(conn, case_id)
    assert row is not None
    return row
