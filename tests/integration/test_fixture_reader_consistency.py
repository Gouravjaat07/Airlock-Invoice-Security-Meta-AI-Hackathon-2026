"""Phase C extras: fixture index consistency and registry integrity.

The main registration workflow is covered by
tests/integration/test_fixture_registration.py; these tests pin the
remaining consistency properties:

- re-registration is deterministic (no silent overwrite);
- corrupted or deleted registered files fail closed (never crash, never
  resolve to another fixture);
- invalid scenario files are skipped without breaking valid fixtures;
- custom bytes can never shadow canonical bytes;
- a fresh reader sees new registrations (no restart needed once the
  backend has the custom directory configured).

All tests use isolated temp databases and temp fixture directories;
the real database and canonical fixtures are never touched.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from app.core.errors import AppError
from app.services import case_service

ALLOW_ITEMS = [
    {"description": "Flour sack 25kg", "quantity": "10",
     "unit_price": "100.00"},
    {"description": "Yeast pack 500g", "quantity": "20",
     "unit_price": "10.00"},
]


def _pdf_bytes(label: str) -> bytes:
    return (
        "%PDF-1.4\n"
        "% Synthetic reader-consistency fixture\n"
        f"% {label}\n"
        "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        "trailer<</Root 1 0 R>>\n"
        "%%EOF\n"
    ).encode("ascii")


def _extraction(*, number="INV-2026-9200") -> dict:
    return {
        "vendor_name": "Acme Flour Co",
        "invoice_number": number,
        "issue_date": "2026-10-01",
        "due_date": "2026-10-31",
        "currency": "USD",
        "subtotal": "1200.00",
        "tax": "40.00",
        "total": "1240.00",
        "bank_reference": "SYN-ACME-0001",
        "po_reference": "PO-1001",
        "line_items": [dict(i) for i in ALLOW_ITEMS],
    }


def _stage(tmp_path, name, pdf_bytes, extraction) -> tuple[str, str]:
    invoice_file = tmp_path / f"{name}.pdf"
    extraction_file = tmp_path / f"{name}.extraction.json"
    invoice_file.write_bytes(pdf_bytes)
    extraction_file.write_text(json.dumps(extraction), encoding="utf-8")
    return str(invoice_file), str(extraction_file)


def _register(settings, tmp_path, name, pdf_bytes, extraction,
              expected="ALLOW_PROPOSAL", **kwargs):
    from app import cli_fixtures
    custom_dir = tmp_path / "custom"
    settings.custom_fixtures_dir = str(custom_dir)
    invoice_file, extraction_file = _stage(tmp_path, name, pdf_bytes,
                                           extraction)
    return cli_fixtures.register(
        settings, name=name, invoice=invoice_file,
        extraction=extraction_file, expected_verdict=expected,
        custom_dir=str(custom_dir), **kwargs)


def test_same_bytes_different_filename_resolves_to_same_fixture(
        settings, tmp_path):
    """Content addressing: the filename plays no role in resolution."""
    from app import cli_fixtures
    pdf = _pdf_bytes("consistency-filename")
    result = _register(settings, tmp_path, "consistency-filename", pdf,
                       _extraction(number="INV-2026-9201"))
    renamed = tmp_path / "totally-different-name.pdf"
    renamed.write_bytes(pdf)
    found = cli_fixtures.verify_bytes(settings, renamed)
    assert found["registered"] is True
    assert found["role"] == "invoice"
    assert found["scenario"] == "consistency-filename"
    assert found["sha256"] == result["sha256"]


def test_reregistration_without_force_is_duplicate(settings, tmp_path):
    """Re-registering a name never silently overwrites the fixture."""
    from app import cli_fixtures
    pdf = _pdf_bytes("consistency-reregister")
    first = _register(settings, tmp_path, "consistency-reregister", pdf,
                      _extraction(number="INV-2026-9202"))
    invoice_file, extraction_file = _stage(
        tmp_path, "consistency-reregister", pdf,
        _extraction(number="INV-2026-9202"))
    with pytest.raises(AppError) as exc_info:
        cli_fixtures.register(
            settings, name="consistency-reregister",
            invoice=invoice_file, extraction=extraction_file,
            expected_verdict="ALLOW_PROPOSAL",
            custom_dir=str(tmp_path / "custom"))
    assert exc_info.value.code == "E_DUPLICATE"
    # Explicit --force re-registration of identical bytes is deterministic.
    forced = cli_fixtures.register(
        settings, name="consistency-reregister",
        invoice=invoice_file, extraction=extraction_file,
        expected_verdict="ALLOW_PROPOSAL",
        custom_dir=str(tmp_path / "custom"), force=True)
    assert forced["sha256"] == first["sha256"]
    assert forced["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert cli_fixtures.verify_bytes(
        settings, invoice_file)["registered"] is True


def test_corrupted_registered_file_fails_closed(seeded_db, settings, store,
                                                tmp_path):
    """Post-registration tampering with the fixture file unresolves it."""
    from app import cli_fixtures
    pdf = _pdf_bytes("consistency-corrupt")
    _register(settings, tmp_path, "consistency-corrupt", pdf,
              _extraction(number="INV-2026-9203"))
    stored = tmp_path / "custom" / "invoices" / "consistency-corrupt.pdf"
    assert stored.read_bytes() == pdf
    stored.write_bytes(_pdf_bytes("consistency-corrupt-tampered"))
    # The original bytes no longer resolve (and never resolve elsewhere).
    assert cli_fixtures.verify_bytes(
        settings, tmp_path / "consistency-corrupt.pdf")["registered"] is False
    created = case_service.create_case(
        seeded_db, settings, store, [("invoice", "c.pdf", pdf)])
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_READER_UNAVAILABLE"


def test_missing_registered_file_fails_closed(seeded_db, settings, store,
                                              tmp_path):
    """A deleted registered file unresolves the bytes without crashing."""
    from app import cli_fixtures
    pdf = _pdf_bytes("consistency-missing")
    _register(settings, tmp_path, "consistency-missing", pdf,
              _extraction(number="INV-2026-9204"))
    (tmp_path / "custom" / "invoices" / "consistency-missing.pdf").unlink()
    assert cli_fixtures.verify_bytes(
        settings, tmp_path / "consistency-missing.pdf")["registered"] is False
    created = case_service.create_case(
        seeded_db, settings, store, [("invoice", "c.pdf", pdf)])
    with pytest.raises(AppError) as exc_info:
        case_service.process_case(seeded_db, settings, store,
                                  created["case"]["id"])
    assert exc_info.value.code == "E_READER_UNAVAILABLE"


def test_invalid_scenario_files_are_skipped(settings, tmp_path):
    """Garbage scenario files never break valid fixture resolution."""
    from app import cli_fixtures
    pdf = _pdf_bytes("consistency-skip")
    _register(settings, tmp_path, "consistency-skip", pdf,
              _extraction(number="INV-2026-9205"))
    scenarios = tmp_path / "custom" / "scenarios"
    (scenarios / "garbage.json").write_text("{not valid json", encoding="utf-8")
    (scenarios / "nondict.json").write_text("[1, 2, 3]", encoding="utf-8")
    (scenarios / "noartifact.json").write_text(
        json.dumps({"name": "noartifact", "extraction": {}}), encoding="utf-8")
    found = cli_fixtures.verify_bytes(
        settings, tmp_path / "consistency-skip.pdf")
    assert found["registered"] is True
    assert found["scenario"] == "consistency-skip"
    listing = cli_fixtures.list_fixtures(settings)
    assert any(item["name"] == "consistency-skip"
               for item in listing["fixtures"])


def test_custom_bytes_cannot_shadow_canonical(settings, tmp_path):
    """Registering canonical bytes under a custom name stays inert."""
    from tests.conftest import fixture_bytes
    canonical = fixture_bytes("invoices/clean.pdf")
    _register(settings, tmp_path, "shadow-attempt", canonical,
              _extraction(number="INV-2026-9206"))
    from app.adapters.readers import FixtureReader
    spec = FixtureReader(settings).scenario_for_invoice(canonical)
    assert spec is not None
    assert spec.get("_fixture_kind") == "canonical"


def test_fresh_reader_sees_new_registration_without_restart(
        seeded_db, settings, store, tmp_path):
    """Resolution happens per request: registering then processing works."""
    from app import cli_fixtures
    from app.providers.registry import resolve_reader
    pdf = _pdf_bytes("consistency-fresh")
    before = resolve_reader(settings)
    with pytest.raises(AppError) as exc_info:
        before.read(pdf)
    assert exc_info.value.code == "E_READER_UNAVAILABLE"
    result = _register(settings, tmp_path, "consistency-fresh", pdf,
                       _extraction(number="INV-2026-9207"))
    after = resolve_reader(settings)
    found = after.read(pdf)
    assert found.artifact_sha256 == result["sha256"]
    assert found.scenario == "consistency-fresh"
    # End to end through the real pipeline in the same settings session.
    created = case_service.create_case(
        seeded_db, settings, store, [("invoice", "c.pdf", pdf)])
    summary = case_service.process_case(seeded_db, settings, store,
                                        created["case"]["id"])
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    assert cli_fixtures.verify_bytes(
        settings, tmp_path / "consistency-fresh.pdf")["kind"] == "custom"
