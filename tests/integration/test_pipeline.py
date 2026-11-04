"""Integration tests: intake + processing pipeline (service level)."""

from __future__ import annotations


import pytest

from app.core.errors import AppError, ErrorCode
from app.services import case_service, vendor_service
from app.storage.repositories import (
    CaseRepository,
    InvoiceIndexRepository,
    ProposalRepository,
    VerdictRepository,
)
from tests.conftest import fixture_bytes

_verdicts = VerdictRepository()
_proposals = ProposalRepository()
_index = InvoiceIndexRepository()


def make_case(seeded_db, settings, store, invoice, **kwargs):
    files = [("invoice", invoice.split("/")[-1], fixture_bytes(invoice))]
    if kwargs.get("delivery"):
        files.append(("delivery", "d.png", fixture_bytes(kwargs["delivery"])))
    if kwargs.get("voice"):
        files.append(("voice", "v.wav", fixture_bytes(kwargs["voice"])))
    return case_service.create_case(seeded_db, settings, store, files)


def process(seeded_db, settings, store, case_id):
    return case_service.process_case(seeded_db, settings, store, case_id)


def test_clean_case_allows_and_proposes(seeded_db, settings, store):
    created = make_case(seeded_db, settings, store, "invoices/clean.pdf")
    summary = process(seeded_db, settings, store, created["case"]["id"])
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    assert summary["case"]["state"] == "PROPOSED"
    assert summary["proposal"] is not None
    assert summary["proposal"]["amount"] == "1240.00"
    assert len(summary["facts"]) == 11
    assert summary["explanation"]


def test_process_is_idempotent(seeded_db, settings, store):
    created = make_case(seeded_db, settings, store, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    first = process(seeded_db, settings, store, case_id)
    second = process(seeded_db, settings, store, case_id)
    assert first["proposal"]["proposal_id"] == second["proposal"]["proposal_id"]
    assert len(_verdicts.list_for_case(seeded_db, case_id)) == 1


def test_changed_bank_denies_without_proposal(seeded_db, settings, store):
    created = make_case(seeded_db, settings, store,
                        "invoices/changed-bank.pdf")
    summary = process(seeded_db, settings, store, created["case"]["id"])
    assert summary["verdict"]["verdict"] == "DENY"
    assert summary["case"]["state"] == "REJECTED"
    assert summary["proposal"] is None


def test_duplicate_second_run_denies(seeded_db, settings, store):
    first = make_case(seeded_db, settings, store, "invoices/clean.pdf")
    process(seeded_db, settings, store, first["case"]["id"])
    second = make_case(seeded_db, settings, store, "invoices/clean.pdf")
    summary = process(seeded_db, settings, store, second["case"]["id"])
    assert summary["verdict"]["verdict"] == "DENY"
    assert "R4" in summary["verdict"]["rule_ids_json"]


def test_unknown_artifact_reader_unavailable(seeded_db, settings, store):
    # Valid PDF bytes that are NOT a registered fixture.
    data = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")
    created = case_service.create_case(seeded_db, settings, store,
                                       [("invoice", "stranger.pdf", data)])
    with pytest.raises(AppError) as exc_info:
        process(seeded_db, settings, store, created["case"]["id"])
    assert exc_info.value.code == ErrorCode.READER_UNAVAILABLE
    case = CaseRepository().get(seeded_db, created["case"]["id"])
    assert case["state"] == "ERROR"


def test_fact_edit_triggers_reprocess(seeded_db, settings, store):
    created = make_case(seeded_db, settings, store,
                        "invoices/arithmetic-mismatch.pdf")
    case_id = created["case"]["id"]
    summary = process(seeded_db, settings, store, case_id)
    assert summary["verdict"]["verdict"] == "DENY"
    total_fact = next(f for f in summary["facts"] if f["field"] == "total")
    fixed = case_service.edit_fact(seeded_db, settings, store, case_id,
                                   total_fact["id"], "1240.00",
                                   session_id="sess-test")
    assert fixed["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    edited = next(f for f in fixed["facts"] if f["field"] == "total")
    assert edited["taint_class"] == "T0"


def test_fact_edit_cannot_bypass_r2(seeded_db, settings, store):
    created = make_case(seeded_db, settings, store,
                        "invoices/changed-bank.pdf")
    case_id = created["case"]["id"]
    summary = process(seeded_db, settings, store, case_id)
    assert summary["verdict"]["verdict"] == "DENY"
    vendor_fact = next(f for f in summary["facts"]
                       if f["field"] == "vendor_name")
    # Renaming the vendor cannot conjure a matching bank record.
    fixed = case_service.edit_fact(seeded_db, settings, store, case_id,
                                   vendor_fact["id"], "Bluebell Dairy Farms",
                                   session_id="sess-test")
    assert fixed["verdict"]["verdict"] == "DENY"


def test_bank_change_cooling_off(seeded_db, settings, store):
    change = vendor_service.request_bank_change(
        seeded_db, settings, "ven-acme-flour", "SYN-ACME-NEW",
        session_id="sess-test")
    assert change["status"] == "pending"
    # Old fingerprint still authoritative: clean invoice still allows.
    created = make_case(seeded_db, settings, store, "invoices/clean.pdf")
    summary = process(seeded_db, settings, store, created["case"]["id"])
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"


def test_bank_change_activation_flips_r2(seeded_db, settings, store):
    vendor_service.request_bank_change(seeded_db, settings, "ven-acme-flour",
                                       "SYN-ACME-NEW", session_id="sess-test")
    seeded_db.execute(
        "UPDATE vendor_bank_changes SET effective_at='2000-01-01T00:00:00+00:00'"
        " WHERE vendor_id='ven-acme-flour'")
    vendor_service.refresh_bank_activation(seeded_db, "ven-acme-flour")
    created = make_case(seeded_db, settings, store, "invoices/clean.pdf")
    summary = process(seeded_db, settings, store, created["case"]["id"])
    assert summary["verdict"]["verdict"] == "DENY"  # old bank no longer valid


def test_reject_case_transitions(seeded_db, settings, store):
    created = make_case(seeded_db, settings, store, "invoices/over-cap.pdf")
    case_id = created["case"]["id"]
    summary = process(seeded_db, settings, store, case_id)
    assert summary["case"]["state"] == "NEEDS_REVIEW"
    rejected = case_service.reject_case(seeded_db, settings, case_id,
                                        session_id="sess-test")
    assert rejected["case"]["state"] == "REJECTED"


def test_recover_stuck_case(seeded_db, settings, store):
    created = make_case(seeded_db, settings, store, "invoices/clean.pdf")
    case_id = created["case"]["id"]
    seeded_db.execute("UPDATE cases SET state='READING' WHERE id=?", (case_id,))
    recovered = case_service.recover_stuck(seeded_db, case_id)
    assert recovered["state"] == "UPLOADED"
    summary = process(seeded_db, settings, store, case_id)
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"
