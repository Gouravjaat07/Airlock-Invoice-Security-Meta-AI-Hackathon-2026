"""Integration tests: service validation branches and error paths."""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.services import (
    approval_service,
    case_service,
    mock_payment_service,
    proposal_service,
    vendor_service,
)
from app.schemas.vendor import VendorCreate, VendorUpdate
from tests.conftest import fixture_bytes


def _case(seeded_db, settings, store, invoice="invoices/clean.pdf"):
    return case_service.create_case(
        seeded_db, settings, store,
        [("invoice", "c.pdf", fixture_bytes(invoice))])


def _session(seeded_db, session_id):
    from app.storage.database import transaction
    from app.storage.repositories import SessionRepository
    with transaction(seeded_db):
        SessionRepository().create(
            seeded_db, session_id=session_id, token_hash="t" + session_id,
            csrf_hash="c" + session_id, now="t",
            expires_at="2999-01-01T00:00:00+00:00")


def test_case_get_and_list(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    fetched = case_service.get_case(seeded_db, settings,
                                    created["case"]["id"])
    assert fetched["case"]["id"] == created["case"]["id"]
    assert case_service.list_cases(seeded_db, limit=10, offset=0)
    with pytest.raises(AppError):
        case_service.get_case(seeded_db, settings, "case-missing")


def test_reject_illegal_states(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    with pytest.raises(AppError):
        case_service.reject_case(seeded_db, settings,
                                 created["case"]["id"],
                                 session_id="s")
    with pytest.raises(AppError):
        case_service.reject_case(seeded_db, settings, "case-missing",
                                 session_id="s")


def test_edit_fact_validation_matrix(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    case_id = created["case"]["id"]
    by_field = {fact["field"]: fact for fact in summary["facts"]}

    # Unknown case / fact / field.
    with pytest.raises(AppError):
        case_service.edit_fact(seeded_db, settings, store, "case-missing",
                               by_field["total"]["id"], "1",
                               session_id="s")
    with pytest.raises(AppError):
        case_service.edit_fact(seeded_db, settings, store, case_id,
                               "fact-missing", "1", session_id="s")
    other = _case(seeded_db, settings, store,
                  "invoices/arithmetic-mismatch.pdf")
    other_summary = case_service.process_case(seeded_db, settings, store,
                                              other["case"]["id"])
    with pytest.raises(AppError):
        case_service.edit_fact(seeded_db, settings, store, case_id,
                               other_summary["facts"][0]["id"], "1",
                               session_id="s")

    invalid = [("vendor_name", ""), ("vendor_name", "x" * 501),
               ("invoice_number", ""),
               ("issue_date", "not-a-date"), ("due_date", "2026-13-99"),
               ("currency", "usd"), ("currency", "US"),
               ("subtotal", "nan"), ("subtotal", "-5"),
               ("tax", "-1"), ("total", "-0.01"), ("total", "oops"),
               ("bank", ""), ("bank", "x" * 129),
               ("po_reference", "x" * 65),
               ("line_items", []), ("line_items", "nope"),
               ("line_items", [{"description": "a"}])]
    for field, value in invalid:
        with pytest.raises(AppError):
            case_service.edit_fact(seeded_db, settings, store, case_id,
                                   by_field[field]["id"], value,
                                   session_id="s")


def test_edit_bank_without_key(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    bank = next(fact for fact in summary["facts"]
                if fact["field"] == "bank")
    settings.bank_hash_key = None
    with pytest.raises(AppError):
        case_service.edit_fact(seeded_db, settings, store,
                               created["case"]["id"], bank["id"],
                               "SYN-NEW", session_id="s")


def test_edit_line_items_and_po_roundtrip(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    case_id = created["case"]["id"]
    by_field = {fact["field"]: fact for fact in summary["facts"]}
    items = [{"description": "Flour sack 25kg", "quantity": "5",
              "unit_price": "100.00"},
             {"description": "Yeast pack 500g", "quantity": "70",
              "unit_price": "10.00"}]
    fixed = case_service.edit_fact(seeded_db, settings, store, case_id,
                                   by_field["line_items"]["id"], items,
                                   session_id="s")
    assert fixed["verdict"]["verdict"] == "DENY"  # 1200 vs edited lines
    fresh = {fact["field"]: fact for fact in fixed["facts"]}
    fixed = case_service.edit_fact(seeded_db, settings, store, case_id,
                                   fresh["po_reference"]["id"], None,
                                   session_id="s")
    assert fixed["case"]["id"] == case_id


def test_edit_blocked_after_execution(seeded_db, settings, store, test_pin):
    from app.auth.pin import hash_pin
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    proposal_id = summary["proposal"]["proposal_id"]
    settings.pin_hash = hash_pin(test_pin)
    _session(seeded_db, "sess-1")
    challenge = approval_service.issue_challenge(
        seeded_db, settings, proposal_id, session_id="sess-1")
    approval_service.confirm(seeded_db, settings, proposal_id,
                             challenge_id=challenge["challenge_id"],
                             pin=test_pin, session_id="sess-1")
    with pytest.raises(AppError):
        case_service.edit_fact(seeded_db, settings, store,
                               created["case"]["id"],
                               summary["facts"][0]["id"], "x",
                               session_id="s")


def test_recover_validation(seeded_db, settings, store):
    with pytest.raises(AppError):
        case_service.recover_stuck(seeded_db, "case-missing")
    created = _case(seeded_db, settings, store)
    with pytest.raises(AppError):
        case_service.recover_stuck(seeded_db, created["case"]["id"])


def test_vendor_errors(seeded_db, settings):
    with pytest.raises(AppError):
        vendor_service.get_vendor(seeded_db, "ven-missing")
    with pytest.raises(AppError):
        vendor_service.update_vendor(seeded_db, settings, "ven-missing",
                                     VendorUpdate(status="inactive"),
                                     session_id="s")
    with pytest.raises(AppError):
        vendor_service.list_bank_changes(seeded_db, "ven-missing")
    with pytest.raises(AppError):
        vendor_service.request_bank_change(seeded_db, settings,
                                           "ven-missing", "SYN-X",
                                           session_id="s")
    # Duplicate catalogue item.
    from app.schemas.vendor import CatalogueItemIn
    with pytest.raises(AppError):
        vendor_service.create_vendor(
            seeded_db, settings,
            VendorCreate(name="Dup Cat", bank_reference="SYN-D",
                         catalogue=[CatalogueItemIn(item_id="a", label="A"),
                                    CatalogueItemIn(item_id="a", label="B")]),
            session_id="s")
    # Bad caps.
    with pytest.raises(AppError):
        vendor_service.create_vendor(
            seeded_db, settings,
            VendorCreate(name="Bad Cap", bank_reference="SYN-D",
                         per_invoice_cap="0"), session_id="s")
    with pytest.raises(AppError):
        vendor_service.create_vendor(
            seeded_db, settings,
            VendorCreate(name="   ", bank_reference="SYN-D"),
            session_id="s")


def test_vendor_create_race_is_duplicate(seeded_db, settings, monkeypatch):
    """Regression (F11): UNIQUE race -> E_DUPLICATE, no driver text leaks."""
    import sqlite3
    from app.schemas.vendor import VendorCreate
    from app.storage.repositories import VendorRepository

    def _race(*args, **kwargs):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: vendors.name_norm")
    monkeypatch.setattr(VendorRepository, "create", _race)
    with pytest.raises(AppError) as exc_info:
        vendor_service.create_vendor(
            seeded_db, settings,
            VendorCreate(name="Race Vendor", bank_reference="SYN-R"),
            session_id="s")
    assert exc_info.value.code == "E_DUPLICATE"
    assert exc_info.value.message == "Vendor conflicts with an existing record"


def test_vendor_update_paths(seeded_db, settings):
    updated = vendor_service.update_vendor(
        seeded_db, settings, "ven-acme-flour",
        VendorUpdate(name="Acme Flour Company",
                     per_invoice_cap="9000.00"), session_id="s")
    assert updated["name"] == "Acme Flour Company"
    assert updated["per_invoice_cap"] == "9000.00"
    with pytest.raises(AppError):
        vendor_service.update_vendor(
            seeded_db, settings, "ven-acme-flour",
            VendorUpdate(name="Bluebell Dairy Farms"), session_id="s")
    with pytest.raises(AppError):
        vendor_service.update_vendor(
            seeded_db, settings, "ven-acme-flour",
            VendorUpdate(status="active"), session_id="s",
            expected_version=999)
    with pytest.raises(AppError):
        vendor_service.update_vendor(
            seeded_db, settings, "ven-acme-flour",
            VendorUpdate(name="  "), session_id="s")


def test_vendor_bank_key_missing(seeded_db, settings):
    settings.bank_hash_key = None
    with pytest.raises(AppError):
        vendor_service.create_vendor(
            seeded_db, settings,
            VendorCreate(name="No Key", bank_reference="SYN-1"),
            session_id="s")
    with pytest.raises(AppError):
        vendor_service.request_bank_change(seeded_db, settings,
                                           "ven-acme-flour", "SYN-2",
                                           session_id="s")


def test_activate_all_due_counts(seeded_db, settings):
    assert vendor_service.activate_all_due(seeded_db) == 0
    vendor_service.request_bank_change(seeded_db, settings,
                                       "ven-acme-flour", "SYN-NEW",
                                       session_id="s")
    seeded_db.execute("UPDATE vendor_bank_changes SET effective_at="
                      "'2000-01-01T00:00:00+00:00'")
    assert vendor_service.activate_all_due(seeded_db) == 1


def test_proposal_service_errors(seeded_db, settings, store):
    with pytest.raises(AppError):
        proposal_service.get_proposal(seeded_db, "prop-missing")
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    proposal_id = summary["proposal"]["proposal_id"]
    seeded_db.execute("UPDATE proposals SET amount='0.01' WHERE proposal_id=?",
                      (proposal_id,))
    with pytest.raises(AppError):
        proposal_service.get_proposal(seeded_db, proposal_id)


def test_proposal_expiry_marks_expired(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    proposal_id = summary["proposal"]["proposal_id"]
    seeded_db.execute("UPDATE proposals SET expires_at="
                      "'2000-01-01T00:00:00+00:00' WHERE proposal_id=?",
                      (proposal_id,))
    with pytest.raises(AppError) as exc_info:
        proposal_service.require_pending(seeded_db, proposal_id)
    assert exc_info.value.code == "E_EXPIRED"
    row = seeded_db.execute("SELECT status FROM proposals WHERE proposal_id=?",
                            (proposal_id,)).fetchone()
    assert row[0] == "EXPIRED"


def test_challenge_rate_limit(seeded_db, settings, store):
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    proposal_id = summary["proposal"]["proposal_id"]
    _session(seeded_db, "sess-rl")
    for _ in range(10):
        approval_service.issue_challenge(seeded_db, settings, proposal_id,
                                         session_id="sess-rl")
    with pytest.raises(AppError) as exc_info:
        approval_service.issue_challenge(seeded_db, settings, proposal_id,
                                         session_id="sess-rl")
    assert exc_info.value.code == "E_RATE_LIMIT"


def test_confirm_stale_and_nonallow(seeded_db, settings, store, test_pin):
    from app.auth.pin import hash_pin
    settings.pin_hash = hash_pin(test_pin)
    _session(seeded_db, "sess-2")
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    case_id = created["case"]["id"]
    proposal_id = summary["proposal"]["proposal_id"]
    challenge = approval_service.issue_challenge(
        seeded_db, settings, proposal_id, session_id="sess-2")
    # Supersede the verdict with a reprocess, then confirm must refuse.
    total = next(fact for fact in summary["facts"]
                 if fact["field"] == "total")
    case_service.edit_fact(seeded_db, settings, store, case_id,
                           total["id"], "1240.00", session_id="sess-2")
    with pytest.raises(AppError) as exc_info:
        approval_service.confirm(seeded_db, settings, proposal_id,
                                 challenge_id=challenge["challenge_id"],
                                 pin=test_pin, session_id="sess-2")
    assert exc_info.value.code in ("E_POLICY_DENY", "E_STATE_TRANSITION")


def test_confirm_lockout(seeded_db, settings, store, test_pin):
    from app.auth.pin import hash_pin
    settings.pin_hash = hash_pin(test_pin)
    _session(seeded_db, "sess-3")
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    proposal_id = summary["proposal"]["proposal_id"]
    challenge = approval_service.issue_challenge(
        seeded_db, settings, proposal_id, session_id="sess-3")
    for _ in range(5):
        with pytest.raises(AppError):
            approval_service.confirm(seeded_db, settings, proposal_id,
                                     challenge_id=challenge["challenge_id"],
                                     pin="wrong", session_id="sess-3")
    with pytest.raises(AppError) as exc_info:
        approval_service.confirm(seeded_db, settings, proposal_id,
                                 challenge_id=challenge["challenge_id"],
                                 pin="wrong", session_id="sess-3")
    assert exc_info.value.code == "E_RATE_LIMIT"


def test_mock_payment_views(seeded_db, settings, store, test_pin):
    from app.auth.pin import hash_pin
    settings.pin_hash = hash_pin(test_pin)
    _session(seeded_db, "sess-4")
    with pytest.raises(AppError):
        mock_payment_service.get_payment(seeded_db, "pay-missing")
    assert mock_payment_service.list_for_case(seeded_db, "case-x") == []
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    proposal_id = summary["proposal"]["proposal_id"]
    challenge = approval_service.issue_challenge(
        seeded_db, settings, proposal_id, session_id="sess-4")
    payment = approval_service.confirm(
        seeded_db, settings, proposal_id,
        challenge_id=challenge["challenge_id"], pin=test_pin,
        session_id="sess-4")
    fetched = mock_payment_service.get_payment(seeded_db,
                                               payment["payment_id"])
    assert fetched["mock"] is True


def test_execute_rechecks(seeded_db, settings, store, test_pin):
    from app.auth.pin import hash_pin
    from app.auth import challenges
    from app.storage.database import transaction
    from app.storage.repositories import SessionRepository
    settings.pin_hash = hash_pin(test_pin)
    with transaction(seeded_db):
        SessionRepository().create(seeded_db, session_id="sess-5",
                                   token_hash="t", csrf_hash="c", now="t",
                                   expires_at="2999-01-01T00:00:00+00:00")
    created = _case(seeded_db, settings, store)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    proposal_id = summary["proposal"]["proposal_id"]
    challenge = challenges.issue(seeded_db, settings,
                                 proposal_hash=summary["proposal"]["proposal_hash"],
                                 session_id="sess-5")
    # Expire the proposal: execute must refuse inside the transaction.
    seeded_db.execute("UPDATE proposals SET expires_at="
                      "'2000-01-01T00:00:00+00:00' WHERE proposal_id=?",
                      (proposal_id,))
    proposal = proposal_service.get_proposal(seeded_db, proposal_id)
    with pytest.raises(AppError) as exc_info:
        mock_payment_service.execute(seeded_db, settings, proposal,
                                     challenge_id=challenge,
                                     session_id="sess-5")
    assert exc_info.value.code == "E_EXPIRED"
