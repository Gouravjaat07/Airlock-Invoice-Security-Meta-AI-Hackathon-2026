"""Phase E/F: genuine R4 duplicate detection across separate documents.

The canonical duplicate scenario reuses identical bytes; these tests prove
the real Invoice A/B property: two DIFFERENT PDFs carrying the SAME
business identity (vendor + invoice number + total + issue date) are
detected as duplicates, while any identity-component change is not.

R4 identity rule under test (app/pipeline/corroborate.py::duplicate_key):
`vendor_id | NORMALIZED_NUMBER | QUANTIZED_TOTAL | ISSUE_DATE`.
Filename and PDF SHA-256 are never part of the key.

All tests use isolated temp databases and temp fixture directories;
the real database and canonical fixtures are never touched.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from app.core.errors import AppError
from app.services import audit_service, case_service

ALLOW_ITEMS = [
    {"description": "Flour sack 25kg", "quantity": "10",
     "unit_price": "100.00"},
    {"description": "Yeast pack 500g", "quantity": "20",
     "unit_price": "10.00"},
]


def _pdf_bytes(label: str) -> bytes:
    return (
        "%PDF-1.4\n"
        "% Synthetic duplicate-detection fixture\n"
        f"% {label}\n"
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        "trailer<</Root 1 0 R>>\n"
        "%%EOF\n"
    ).encode("ascii")


def _extraction(*, vendor="Acme Flour Co", number="INV-2026-9100",
                bank="SYN-ACME-0001", po="PO-1001",
                issue="2026-10-01", due="2026-10-31",
                subtotal="1200.00", tax="40.00", total="1240.00",
                items=None) -> dict:
    return {
        "vendor_name": vendor,
        "invoice_number": number,
        "issue_date": issue,
        "due_date": due,
        "currency": "USD",
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "bank_reference": bank,
        "po_reference": po,
        "line_items": items if items is not None else [dict(i) for i in ALLOW_ITEMS],
    }


def _register(settings, tmp_path, name, pdf_bytes, extraction,
              expected="ALLOW_PROPOSAL"):
    from app import cli_fixtures
    custom_dir = tmp_path / "custom"
    settings.custom_fixtures_dir = str(custom_dir)
    invoice_file = tmp_path / f"{name}.pdf"
    extraction_file = tmp_path / f"{name}.extraction.json"
    invoice_file.write_bytes(pdf_bytes)
    extraction_file.write_text(json.dumps(extraction), encoding="utf-8")
    return cli_fixtures.register(
        settings, name=name, invoice=str(invoice_file),
        extraction=str(extraction_file), expected_verdict=expected,
        custom_dir=str(custom_dir))


def _create(seeded_db, settings, store, pdf_bytes, filename="invoice.pdf"):
    return case_service.create_case(
        seeded_db, settings, store, [("invoice", filename, pdf_bytes)])


def _process(seeded_db, settings, store, pdf_bytes, filename="invoice.pdf"):
    created = _create(seeded_db, settings, store, pdf_bytes, filename)
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    return created, summary


def _rules(seeded_db, case_id) -> dict[str, dict]:
    from app.storage.repositories import VerdictRepository
    verdict = VerdictRepository().latest_for_case(seeded_db, case_id)
    assert verdict is not None
    details = json.loads(str(verdict["rule_details_json"]))
    return {rule["rule_id"]: rule for rule in details}


def _failed(rules) -> list[str]:
    return sorted(rid for rid, rule in rules.items() if not rule["passed"])


def _audit_types(conn, case_id) -> list[str]:
    rows = conn.execute("SELECT event_type FROM audit_events WHERE case_id = ?"
                        " ORDER BY id", (case_id,)).fetchall()
    return [row[0] for row in rows]


# --- Genuine R4: different PDFs, same business identity ------------------


def test_second_pdf_same_identity_denies_only_r4(seeded_db, settings, store,
                                                 tmp_path):
    """Core Invoice A/B property: distinct bytes, same identity → R4 DENY."""
    pdf_a = _pdf_bytes("dup-case-A")
    pdf_b = _pdf_bytes("dup-case-B")
    assert hashlib.sha256(pdf_a).hexdigest() != hashlib.sha256(pdf_b).hexdigest()
    extraction = _extraction(number="INV-2026-9100")
    _register(settings, tmp_path, "dup-case-a", pdf_a, extraction)
    _register(settings, tmp_path, "dup-case-b", pdf_b, extraction,
              expected="DENY")

    created_a, summary_a = _process(seeded_db, settings, store, pdf_a, "a.pdf")
    assert summary_a["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    rules_a = _rules(seeded_db, created_a["case"]["id"])
    assert _failed(rules_a) == []  # first invoice is not its own duplicate
    assert rules_a["R4"]["reason_code"] == "not-duplicate"
    assert summary_a["proposal"] is not None

    created_b, summary_b = _process(seeded_db, settings, store, pdf_b, "b.pdf")
    assert summary_b["case"]["state"] == "REJECTED"
    assert summary_b["verdict"]["verdict"] == "DENY"
    rules_b = _rules(seeded_db, created_b["case"]["id"])
    assert _failed(rules_b) == ["R4"]
    assert rules_b["R4"]["reason_code"] == "duplicate"
    # R4/R5 isolation: 1240.00 is below the 10000.00 cap, so R5 passes
    # and the DENY is attributable to duplication alone.
    assert rules_b["R5"]["passed"] is True
    assert rules_b["R1"]["passed"] is True
    assert rules_b["R2"]["passed"] is True
    # No duplicate proposal or payment may exist for case B.
    assert summary_b["proposal"] is None
    assert summary_b["payments"] == []
    assert audit_service.verify_chain(seeded_db)["ok"] is True


def test_duplicate_reprocessing_is_stable(seeded_db, settings, store, tmp_path):
    """Repeated processing of the duplicate returns the same stored verdict."""
    pdf_a = _pdf_bytes("dup-stable-A")
    pdf_b = _pdf_bytes("dup-stable-B")
    extraction = _extraction(number="INV-2026-9101")
    _register(settings, tmp_path, "dup-stable-a", pdf_a, extraction)
    _register(settings, tmp_path, "dup-stable-b", pdf_b, extraction,
              expected="DENY")
    _process(seeded_db, settings, store, pdf_a)
    created_b, summary_b = _process(seeded_db, settings, store, pdf_b)
    assert summary_b["verdict"]["verdict"] == "DENY"
    verdict_id = summary_b["verdict"]["verdict_id"]
    again = case_service.process_case(seeded_db, settings, store,
                                      created_b["case"]["id"])
    assert again["verdict"]["verdict_id"] == verdict_id
    assert again["proposal"] is None
    assert again["payments"] == []


# --- Identity components: any change breaks the duplicate key ------------


def test_changed_amount_is_not_duplicate(seeded_db, settings, store, tmp_path):
    pdf_a = _pdf_bytes("dup-amount-A")
    pdf_b = _pdf_bytes("dup-amount-B")
    _register(settings, tmp_path, "dup-amount-a", pdf_a,
              _extraction(number="INV-2026-9102"))
    # Same vendor/number/date, different total (40.00 -> 41.00 tax keeps
    # the arithmetic exact: 1200.00 + 41.00 == 1241.00).
    _register(settings, tmp_path, "dup-amount-b", pdf_b,
              _extraction(number="INV-2026-9102", tax="41.00",
                          total="1241.00"))
    _process(seeded_db, settings, store, pdf_a)
    created_b, summary_b = _process(seeded_db, settings, store, pdf_b)
    assert summary_b["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    rules_b = _rules(seeded_db, created_b["case"]["id"])
    assert rules_b["R4"]["passed"] is True
    assert summary_b["proposal"] is not None


def test_same_number_different_vendor_is_not_duplicate(seeded_db, settings,
                                                       store, tmp_path):
    pdf_a = _pdf_bytes("dup-vendor-A")
    pdf_b = _pdf_bytes("dup-vendor-B")
    _register(settings, tmp_path, "dup-vendor-a", pdf_a,
              _extraction(number="INV-2026-9103"))
    # Same invoice number, total and date — but a different trusted vendor
    # (Bluebell has no lookalike, so R10 stays quiet; no PO keeps R5
    # to the cap check, 1240.00 < 2500.00).
    _register(settings, tmp_path, "dup-vendor-b", pdf_b,
              _extraction(number="INV-2026-9103",
                          vendor="Bluebell Dairy Farms",
                          bank="SYN-DAIRY-0004", po=None))
    _process(seeded_db, settings, store, pdf_a)
    created_b, summary_b = _process(seeded_db, settings, store, pdf_b)
    assert summary_b["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    rules_b = _rules(seeded_db, created_b["case"]["id"])
    assert rules_b["R4"]["passed"] is True


def test_changed_issue_date_is_not_duplicate(seeded_db, settings, store,
                                             tmp_path):
    pdf_a = _pdf_bytes("dup-date-A")
    pdf_b = _pdf_bytes("dup-date-B")
    _register(settings, tmp_path, "dup-date-a", pdf_a,
              _extraction(number="INV-2026-9104"))
    _register(settings, tmp_path, "dup-date-b", pdf_b,
              _extraction(number="INV-2026-9104", issue="2026-10-02"))
    _process(seeded_db, settings, store, pdf_a)
    created_b, summary_b = _process(seeded_db, settings, store, pdf_b)
    assert summary_b["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    rules_b = _rules(seeded_db, created_b["case"]["id"])
    assert rules_b["R4"]["passed"] is True


def test_invoice_number_normalization_detects_duplicate(seeded_db, settings,
                                                        store, tmp_path):
    """Case/whitespace variants of the number share one R4 key."""
    pdf_a = _pdf_bytes("dup-norm-A")
    pdf_b = _pdf_bytes("dup-norm-B")
    _register(settings, tmp_path, "dup-norm-a", pdf_a,
              _extraction(number="INV-2026-9105"))
    _register(settings, tmp_path, "dup-norm-b", pdf_b,
              _extraction(number="  inv-2026-9105 "), expected="DENY")
    _process(seeded_db, settings, store, pdf_a)
    created_b, summary_b = _process(seeded_db, settings, store, pdf_b)
    assert summary_b["verdict"]["verdict"] == "DENY"
    rules_b = _rules(seeded_db, created_b["case"]["id"])
    assert _failed(rules_b) == ["R4"]
    assert rules_b["R4"]["reason_code"] == "duplicate"


def test_unresolved_vendor_duplicate_unverifiable(seeded_db, settings, store,
                                                  tmp_path):
    """Without a resolved vendor, R4 fails as unverifiable (DENY, no key)."""
    pdf = _pdf_bytes("dup-noverdor")
    _register(settings, tmp_path, "dup-noverdor", pdf,
              _extraction(number="INV-2026-9106",
                          vendor="Nonexistent Corp"), expected="DENY")
    created, summary = _process(seeded_db, settings, store, pdf)
    assert summary["verdict"]["verdict"] == "DENY"
    rules = _rules(seeded_db, created["case"]["id"])
    assert rules["R1"]["passed"] is False
    assert rules["R4"]["passed"] is False
    assert rules["R4"]["reason_code"] == "duplicate-unverifiable"
    assert summary["proposal"] is None


# --- Byte/filename handling around duplicates -----------------------------


def test_same_bytes_different_filename_dedups_and_denies(seeded_db, settings,
                                                         store, tmp_path):
    """Identical bytes under another name reuse the blob, then R4 DENY."""
    pdf = _pdf_bytes("dup-filename")
    _register(settings, tmp_path, "dup-filename", pdf,
              _extraction(number="INV-2026-9107"))
    created_a, summary_a = _process(seeded_db, settings, store, pdf,
                                    "original-name.pdf")
    assert summary_a["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    created_b, summary_b = _process(seeded_db, settings, store, pdf,
                                    "renamed-copy.pdf")
    assert summary_b["verdict"]["verdict"] == "DENY"
    key_a = next(a["storage_key"] for a in summary_a["artifacts"]
                 if a["kind"] == "invoice")
    key_b = next(a["storage_key"] for a in summary_b["artifacts"]
                 if a["kind"] == "invoice")
    assert key_a == key_b
    assert "artifact.deduplicated" in _audit_types(seeded_db,
                                                  created_b["case"]["id"])
    assert created_a["case"]["id"] != created_b["case"]["id"]


def test_same_bytes_twice_within_one_case(seeded_db, settings, store,
                                          tmp_path):
    """Two invoice parts with identical bytes in one intake stay coherent."""
    pdf = _pdf_bytes("dup-twice")
    _register(settings, tmp_path, "dup-twice", pdf,
              _extraction(number="INV-2026-9108"))
    created = case_service.create_case(
        seeded_db, settings, store,
        [("invoice", "first.pdf", pdf), ("invoice", "second.pdf", pdf)])
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    invoices = [a for a in summary["artifacts"] if a["kind"] == "invoice"]
    assert len(invoices) == 2
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    # Service-level summaries carry raw fact rows (value_json, not value).
    by_field = {fact["field"]: json.loads(str(fact["value_json"]))
                for fact in summary["facts"]}
    assert by_field["invoice_number"] == "INV-2026-9108"


def test_unregistered_second_pdf_is_reader_error_not_duplicate(
        seeded_db, settings, store, tmp_path):
    """Registration failure and duplicate verdict are distinct outcomes."""
    pdf_a = _pdf_bytes("dup-unreg-A")
    pdf_b = _pdf_bytes("dup-unreg-B-never-registered")
    _register(settings, tmp_path, "dup-unreg-a", pdf_a,
              _extraction(number="INV-2026-9109"))
    _process(seeded_db, settings, store, pdf_a)
    created_b = _create(seeded_db, settings, store, pdf_b)
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created_b["case"]["id"])
    assert exc_info.value.code == "E_READER_UNAVAILABLE"
