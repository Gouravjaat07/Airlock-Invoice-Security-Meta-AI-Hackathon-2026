"""Pipeline gap tests: transitions, evidence edges, error handlers."""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.core.errors import AppError
from app.pipeline import process
from app.pipeline.ingest import classify_upload
from app.services import case_service
from app.storage.repositories import CaseRepository, VerdictRepository
from tests.conftest import fixture_bytes


def _case(seeded_db, settings, store, invoice="invoices/clean.pdf",
          **extra):
    files = [("invoice", "c.pdf", fixture_bytes(invoice))]
    if extra.get("delivery"):
        files.append(("delivery", "d.png",
                      fixture_bytes(extra["delivery"])))
    if extra.get("voice"):
        files.append(("voice", "v.wav", fixture_bytes(extra["voice"])))
    return case_service.create_case(seeded_db, settings, store, files)


def test_classify_upload_errors():
    with pytest.raises(AppError):
        classify_upload("application/pdf", "delivery")
    with pytest.raises(AppError):
        classify_upload("image/png", "voice")
    with pytest.raises(AppError):
        classify_upload("audio/wav", "invoice")
    assert classify_upload("video/mp4", "delivery") == "delivery"


def test_create_case_input_errors(seeded_db, settings, store):
    with pytest.raises(AppError):
        case_service.create_case(seeded_db, settings, store, [])
    many = [("invoice", f"{i}.pdf", fixture_bytes("invoices/clean.pdf"))
            for i in range(9)]
    with pytest.raises(AppError):
        case_service.create_case(seeded_db, settings, store, many)
    with pytest.raises(AppError):
        case_service.create_case(
            seeded_db, settings, store,
            [("delivery", "d.png", fixture_bytes("delivery/sam-ok.png"))])


def test_idempotency_key_reuse(seeded_db, settings, store):
    first = case_service.create_case(
        seeded_db, settings, store,
        [("invoice", "c.pdf", fixture_bytes("invoices/clean.pdf"))],
        idempotency_key="idem-1")
    second = case_service.create_case(
        seeded_db, settings, store,
        [("invoice", "c.pdf", fixture_bytes("invoices/clean.pdf"))],
        idempotency_key="idem-1")
    assert first["case"]["id"] == second["case"]["id"]


def test_run_case_missing_and_busy(seeded_db, settings, store):
    with pytest.raises(AppError):
        case_service.process_case(seeded_db, settings, store,
                                  "case-missing")
    created = _case(seeded_db, settings, store)
    seeded_db.execute("UPDATE cases SET state='READING' WHERE id=?",
                      (created["case"]["id"],))
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_STATE_TRANSITION"


def test_process_rejected_returns_summary(seeded_db, settings, store):
    created = _case(seeded_db, settings, store,
                    "invoices/changed-bank.pdf")
    first = case_service.process_case(seeded_db, settings, store,
                                      created["case"]["id"])
    assert first["verdict"]["verdict"] == "DENY"
    second = case_service.process_case(seeded_db, settings, store,
                                       created["case"]["id"])
    assert second["verdict"]["verdict"] == "DENY"
    assert len(VerdictRepository().list_for_case(
        seeded_db, created["case"]["id"])) == 1


def test_process_without_invoice_artifact(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    seeded_db.execute("DELETE FROM artifacts WHERE case_id=?",
                      (created["case"]["id"],))
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_UPLOAD"


def test_processing_capacity_exhausted(seeded_db, settings, store):
    settings.max_concurrent_processing = 1
    limiter = process._limiter(1)
    assert limiter.acquire(blocking=False)
    try:
        created = _case(seeded_db, settings, store)
        with pytest.raises(AppError) as exc_info:
            case_service.process_case(seeded_db, settings, store,
                                      created["case"]["id"])
        assert exc_info.value.code == "E_RATE_LIMIT"
    finally:
        limiter.release()


def test_transition_conflict(seeded_db, settings, store, monkeypatch):
    created = _case(seeded_db, settings, store)
    monkeypatch.setattr(CaseRepository, "update_state",
                        lambda *a, **k: False)
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_CONFLICT"


def test_unexpected_error_fails_closed(seeded_db, settings, store,
                                       monkeypatch):
    import app.pipeline.process as proc_mod
    created = _case(seeded_db, settings, store)

    def _boom(*args, **kwargs):
        raise RuntimeError("adapter exploded")
    monkeypatch.setattr(proc_mod, "resolve_vendor", _boom)
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_INTERNAL"
    case = CaseRepository().get(seeded_db, created["case"]["id"])
    assert case["state"] == "ERROR"
    # Regression (F7): raw exception text never lands in the API-served summary.
    assert case["error_summary"] == "Processing failed"


def test_error_transition_conflict_tolerated(seeded_db, settings, store,
                                             monkeypatch):
    created = case_service.create_case(
        seeded_db, settings, store,
        [("invoice", "s.pdf", b"%PDF-1.4 stranger\n%%EOF\n")])
    real = CaseRepository.update_state
    calls = {"n": 0}

    def _flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return real(self, *args, **kwargs)
        return False
    monkeypatch.setattr(CaseRepository, "update_state", _flaky)
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_READER_UNAVAILABLE"


def test_reprocess_invalid_facts_denies(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    seeded_db.execute("UPDATE facts SET value_json='\"oops\"'"
                      " WHERE case_id=? AND field='total'",
                      (created["case"]["id"],))
    rerun = process.run_case(seeded_db, settings, store,
                             created["case"]["id"], force=True)
    assert rerun["verdict"]["verdict"] == "DENY"


def test_sam_skipped_without_catalogue(seeded_db, settings, store):
    seeded_db.execute("UPDATE vendors SET catalogue_json='[]'"
                      " WHERE vendor_id='ven-acme-flour'")
    created = _case(seeded_db, settings, store,
                    delivery="delivery/sam-ok.png")
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"


def test_voice_failure_nonfatal(seeded_db, settings, store):
    import struct
    header = (b"RIFF" + struct.pack("<I", 44) + b"WAVE" + b"fmt " +
              struct.pack("<I", 16) +
              struct.pack("<HHIIHH", 1, 1, 8000, 8000, 1, 8) + b"data" +
              struct.pack("<I", 8))
    created = case_service.create_case(
        seeded_db, settings, store,
        [("invoice", "c.pdf", fixture_bytes("invoices/clean.pdf")),
         ("voice", "strange.wav", header + b"\x00" * 8)])
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"


def test_duplicate_race_at_proposal(seeded_db, settings, store,
                                    monkeypatch):
    import app.pipeline.propose as propose_mod
    created = _case(seeded_db, settings, store)
    _ = created

    def _race(*args, **kwargs):
        raise sqlite3.IntegrityError("dup")
    monkeypatch.setattr(propose_mod, "build_proposal", _race)
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_DUPLICATE"


def test_tmp_fixture_nondict_and_blank_bank(seeded_db, settings, store,
                                            tmp_path):
    root = tmp_path / "fx"
    (root / "scenarios").mkdir(parents=True)
    (root / "invoices").mkdir()
    nondict_pdf = b"%PDF-1.4 nondict\n%%EOF\n"
    (root / "invoices" / "nondict.pdf").write_bytes(nondict_pdf)
    (root / "scenarios" / "nondict.json").write_text(json.dumps({
        "name": "nondict", "invoice_artifact": "invoices/nondict.pdf",
        "extraction": [1]}))
    blank_pdf = b"%PDF-1.4 blank\n%%EOF\n"
    (root / "invoices" / "blank.pdf").write_bytes(blank_pdf)
    (root / "scenarios" / "blank.json").write_text(json.dumps({
        "name": "blank", "invoice_artifact": "invoices/blank.pdf",
        "extraction": {
            "vendor_name": "Acme Flour Co", "invoice_number": "INV-TMP-1",
            "issue_date": "2026-10-01", "due_date": "2026-10-31",
            "currency": "USD", "subtotal": "10.00", "tax": "0.00",
            "total": "10.00", "bank_reference": "   ",
            "line_items": [{"description": "a", "quantity": "1",
                            "unit_price": "10.00"}]}}))
    settings.fixtures_dir = str(root)
    created = case_service.create_case(
        seeded_db, settings, store, [("invoice", "n.pdf", nondict_pdf)])
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "DENY"
    created = case_service.create_case(
        seeded_db, settings, store, [("invoice", "b.pdf", blank_pdf)])
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "DENY"


def test_detect_voice_conflict_amounts(seeded_db, settings):
    from app.pipeline.process import detect_voice_conflict
    from app.pipeline.validate import validate_extraction
    extraction = validate_extraction({
        "vendor_name": "Acme Flour Co", "invoice_number": "INV-1",
        "issue_date": "2026-10-01", "due_date": "2026-10-31",
        "currency": "USD", "subtotal": "10.00", "tax": "0.00",
        "total": "10.00", "bank_reference": "SYN-ACME-0001",
        "line_items": [{"description": "a", "quantity": "1",
                        "unit_price": "10.00"}]})
    assert detect_voice_conflict("the total is 10.00, thanks",
                                 extraction) is False
    assert detect_voice_conflict("the total is 99.99, thanks",
                                 extraction) is True


def test_po_currency_mismatch_and_fractional_sam(seeded_db, settings):
    import copy
    from app.pipeline import policy
    from app.pipeline.corroborate import corroborate
    from app.pipeline.registry import resolve_vendor
    from app.pipeline.validate import validate_extraction
    from app.storage.database import transaction
    from app.storage.repositories import PurchaseOrderRepository
    with transaction(seeded_db):
        PurchaseOrderRepository().create(
            seeded_db, po_id="po-eur", vendor_id="ven-acme-flour",
            po_reference="PO-EUR", currency="EUR", original="9999.00",
            remaining="9999.00")
    base = {"vendor_name": "Acme Flour Co", "invoice_number": "INV-FX-1",
            "issue_date": "2026-10-01", "due_date": "2026-10-31",
            "currency": "USD", "subtotal": "10.00", "tax": "0.00",
            "total": "10.00", "bank_reference": "SYN-ACME-0001",
            "po_reference": "PO-EUR",
            "line_items": [{"description": "a", "quantity": "1",
                            "unit_price": "10.00"}]}
    extraction = validate_extraction(copy.deepcopy(base))
    match = resolve_vendor(seeded_db, extraction.vendor_name)
    corr = corroborate(seeded_db, settings, extraction, match)
    assert corr.po_ok is False
    verdict, _ = policy.evaluate_policy(settings, extraction, corr,
                                        schema_ok=True)
    assert verdict.value == "ESCALATE"
    fractional = copy.deepcopy(base)
    fractional["po_reference"] = None
    fractional["line_items"] = [{"description": "a", "quantity": "1.5",
                                 "unit_price": "10.00"}]
    fractional["subtotal"] = "15.00"
    fractional["total"] = "15.00"
    extraction = validate_extraction(fractional)
    match = resolve_vendor(seeded_db, extraction.vendor_name)
    corr = corroborate(seeded_db, settings, extraction, match,
                       sam_count=2, sam_item_tolerance=5)
    assert corr.sam_ok is False


def test_orphan_cleanup_tolerates_delete_failure(seeded_db, settings, store,
                                                 monkeypatch):
    monkeypatch.setattr(store, "delete",
                        lambda key: (_ for _ in ()).throw(
                            AppError("E_STORAGE", "gone")))

    def _fail(*args, **kwargs):
        raise AppError("E_DATABASE", "boom")
    monkeypatch.setattr(CaseRepository, "create", _fail)
    with pytest.raises(AppError):
        case_service.create_case(
            seeded_db, settings, store,
            [("invoice", "c.pdf", fixture_bytes("invoices/clean.pdf"))])


def test_database_directory_path_error(tmp_path):
    from app.config import Settings
    from app.storage import database
    settings = Settings(db_path=str(tmp_path))  # a directory, not a file
    with pytest.raises(AppError):
        database.connect(settings)


def test_replaced_blob_bytes_fail_closed(seeded_db, settings, store):
    from pathlib import Path

    created = _case(seeded_db, settings, store)
    row = seeded_db.execute(
        "SELECT storage_key FROM artifacts WHERE case_id = ? AND kind = ?",
        (created["case"]["id"], "invoice")).fetchone()
    blob = Path(settings.blob_dir) / row["storage_key"]
    blob.write_bytes(b"%PDF-1.4 replaced bytes\n%%EOF\n")
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_DATABASE"


def test_delivery_blob_replacement_surfaces_as_verifier_error(
        seeded_db, settings, store):
    from pathlib import Path

    created = _case(seeded_db, settings, store,
                    delivery="delivery/sam-ok.png")
    row = seeded_db.execute(
        "SELECT storage_key FROM artifacts WHERE case_id = ? AND kind = ?",
        (created["case"]["id"], "delivery")).fetchone()
    blob = Path(settings.blob_dir) / row["storage_key"]
    blob.write_bytes(b"\x89PNG replaced")
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    # The invoice still processes; the replaced delivery evidence
    # fails the required verifier (R9 DENY), never passes as genuine.
    assert summary["verdict"]["verdict"] == "DENY"


# --- Artifact integrity handling -------------------------------------------


def _blob_path(settings, seeded_db, case_id, kind):
    from pathlib import Path
    row = seeded_db.execute(
        "SELECT storage_key FROM artifacts WHERE case_id = ? AND kind = ?",
        (case_id, kind)).fetchone()
    return Path(settings.blob_dir) / row["storage_key"]


def test_delivery_video_blob_replacement_denies_r9(seeded_db, settings, store):
    created = _case(seeded_db, settings, store,
                    delivery="delivery/clip.mp4")
    _blob_path(settings, seeded_db, created["case"]["id"],
               "delivery").write_bytes(b"\x00\x00 swapped video")
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "DENY"


def test_voice_blob_replacement_is_nonfatal(seeded_db, settings, store):
    created = _case(seeded_db, settings, store,
                    voice="voice/voice-instruction.wav")
    _blob_path(settings, seeded_db, created["case"]["id"],
               "voice").write_bytes(b"RIFF swapped")
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    # Voice is optional: corruption is recorded, the valid invoice
    # still processes.
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"


def test_invoice_blob_missing_at_processing(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    _blob_path(settings, seeded_db, created["case"]["id"],
               "invoice").unlink()
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_STORAGE"


def test_delivery_blob_missing_denies_r9(seeded_db, settings, store):
    created = _case(seeded_db, settings, store,
                    delivery="delivery/sam-ok.png")
    _blob_path(settings, seeded_db, created["case"]["id"],
               "delivery").unlink()
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "DENY"


def test_invoice_hash_missing_fails_closed(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    seeded_db.execute("UPDATE artifacts SET sha256 = '' WHERE case_id = ?",
                      (created["case"]["id"],))
    seeded_db.commit()
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_DATABASE"


def test_identical_bytes_rewrite_processes_normally(seeded_db, settings,
                                                    store):
    created = _case(seeded_db, settings, store)
    blob = _blob_path(settings, seeded_db, created["case"]["id"], "invoice")
    blob.write_bytes(blob.read_bytes())  # same key, identical bytes
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"


def test_swapped_bytes_rejected_at_read_time(seeded_db, settings, store,
                                             monkeypatch):
    # Simulates replacement inside the intake->processing window: every
    # read rebinds bytes to the recorded hash.
    created = _case(seeded_db, settings, store)

    def _swapped(storage_key):
        return b"%PDF-1.4 swapped mid-flight\n%%EOF\n"

    monkeypatch.setattr(store, "read_bytes", _swapped)
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_DATABASE"


def test_corrupted_invoice_never_reaches_reader(seeded_db, settings, store,
                                                monkeypatch):
    created = _case(seeded_db, settings, store)
    _blob_path(settings, seeded_db, created["case"]["id"],
               "invoice").write_bytes(b"tampered")

    def _boom(settings):
        raise AssertionError("reader must not see tampered bytes")

    monkeypatch.setattr(process, "get_reader", _boom)
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_DATABASE"


def test_corrupted_delivery_never_reaches_segmenter(seeded_db, settings,
                                                    store, monkeypatch):
    created = _case(seeded_db, settings, store,
                    delivery="delivery/sam-ok.png")
    _blob_path(settings, seeded_db, created["case"]["id"],
               "delivery").write_bytes(b"tampered")

    def _boom(settings, **kwargs):
        raise AssertionError("segmenter must not see tampered bytes")

    monkeypatch.setattr(process, "resolve_vision", _boom)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "DENY"


def test_corrupted_voice_never_reaches_transcriber(seeded_db, settings,
                                                   store, monkeypatch):
    created = _case(seeded_db, settings, store,
                    voice="voice/voice-instruction.wav")
    _blob_path(settings, seeded_db, created["case"]["id"],
               "voice").write_bytes(b"tampered")

    def _boom(settings, **kwargs):
        raise AssertionError("transcriber must not see tampered bytes")

    monkeypatch.setattr(process, "resolve_voice", _boom)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"
