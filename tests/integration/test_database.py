"""Integration tests: migrations, repositories, transactions."""

from __future__ import annotations


import pytest

from app.core.errors import AppError
from app.storage import database
from app.storage.database import transaction
from app.storage.repositories import CaseRepository, VendorRepository


def test_upgrade_is_idempotent(settings):
    first = database.upgrade(settings)
    second = database.upgrade(settings)
    assert first["current_version"] >= 1
    assert second["applied"] == []
    assert second["current_version"] == first["current_version"]


def test_current_version_matches_latest(settings):
    database.upgrade(settings)
    conn = database.connect(settings)
    try:
        assert database.current_version(conn) == database.latest_version()
    finally:
        conn.close()


def test_integrity_ok(settings, seeded_db):
    ok, detail = database.is_integrity_ok(settings)
    assert ok, detail


def test_foreign_keys_enforced(seeded_db):
    with pytest.raises(AppError):
        with transaction(seeded_db):
            seeded_db.execute(
                "INSERT INTO artifacts (id, case_id, sha256, kind, media_type,"
                " extension, size_bytes, storage_key, created_at)"
                " VALUES ('a','no-such-case','x','invoice','application/pdf',"
                "'.pdf',1,'k','t')")


def test_unique_vendor_norm(seeded_db):
    vendors = VendorRepository()
    with pytest.raises(AppError):  # integrity violation -> E_DATABASE
        with transaction(seeded_db):
            vendors.create(seeded_db, vendor_id="ven-dup",
                           name="ACME FLOUR co.", name_norm="acme flour co",
                           bank_fp="v1:abc", catalogue_json="[]", cap=None,
                           now="2026-10-31T00:00:00+00:00")


def test_transaction_rolls_back_on_app_error(seeded_db):
    cases = CaseRepository()
    with pytest.raises(AppError):
        with transaction(seeded_db):
            cases.create(seeded_db, case_id="case-rollback",
                         state="UPLOADED", now="t", idempotency_key=None)
            raise AppError("E_INTERNAL", "boom")
    assert cases.get(seeded_db, "case-rollback") is None


def test_optimistic_locking(seeded_db):
    from app.core.clock import SYSTEM_CLOCK
    cases = CaseRepository()
    now = SYSTEM_CLOCK.now().isoformat()
    with transaction(seeded_db):
        cases.create(seeded_db, case_id="case-lock", state="UPLOADED",
                     now=now, idempotency_key=None)
    assert cases.update_state(seeded_db, case_id="case-lock",
                              state="READING", now=now,
                              expected_version=1)
    assert not cases.update_state(seeded_db, case_id="case-lock",
                                  state="READING", now=now,
                                  expected_version=1)  # stale


def test_migration_002_adds_proposal_policy(settings):
    # Simulate a version-1 database, then upgrade: the column appears
    # with a backfilled default and the version row advances.
    from pathlib import Path
    conn = database.connect(settings)
    try:
        sql = (Path(database.MIGRATIONS_DIR) / "001_init.sql").read_text()
        conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("INSERT INTO schema_migrations (version, applied_at)"
                     " VALUES (1, 't')")
        conn.execute(
            "INSERT INTO proposals (proposal_id, case_id, vendor_id,"
            " payee_display_name, amount, currency, due_date,"
            " invoice_reference, verdict_id, proposal_hash, expires_at,"
            " status, created_at) VALUES ('p','c','v','n','1','USD','d',"
            " 'i','vdt','h','e','PENDING','t')")
    finally:
        conn.close()
    result = database.upgrade(settings)
    assert result["current_version"] == database.latest_version()
    assert 2 in result["applied"]
    conn = database.connect(settings)
    try:
        row = conn.execute("SELECT policy_version FROM proposals"
                           " WHERE proposal_id='p'").fetchone()
        assert row[0] == "2.0.0"
    finally:
        conn.close()


def test_migration_003_hashes_challenges(settings):
    # Simulate a version-2 database with one pending (plaintext) challenge,
    # then upgrade: the table is rebuilt on challenge_hash, the pending
    # bearer is invalidated (fail-closed), and business rows are untouched.
    from pathlib import Path
    conn = database.connect(settings)
    try:
        sql = (Path(database.MIGRATIONS_DIR) / "001_init.sql").read_text()
        conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("ALTER TABLE proposals ADD COLUMN policy_version TEXT"
                     " NOT NULL DEFAULT '2.0.0'")
        conn.execute("INSERT INTO schema_migrations (version, applied_at)"
                     " VALUES (1, 't'), (2, 't')")
        conn.execute(
            "INSERT INTO auth_challenges (challenge_id, proposal_hash,"
            " session_id, created_at, expires_at) VALUES ('ch_pending','h',"
            " 's','t','2999-01-01T00:00:00+00:00')")
        conn.execute(
            "INSERT INTO audit_events (ts, event_type, actor_type, payload_json,"
            " prev_hash, event_hash) VALUES ('t','e','system','{}','g','h')")
    finally:
        conn.close()
    result = database.upgrade(settings)
    assert result["current_version"] == database.latest_version()
    assert 3 in result["applied"]
    conn = database.connect(settings)
    try:
        cols = [row[1] for row in
                conn.execute("PRAGMA table_info(auth_challenges)").fetchall()]
        assert "challenge_hash" in cols and "challenge_id" not in cols
        leftovers = conn.execute(
            "SELECT COUNT(*) FROM auth_challenges").fetchone()[0]
        assert leftovers == 0  # pending approval invalidated, not migrated
        kept = conn.execute(
            "SELECT COUNT(*) FROM audit_events").fetchone()[0]
        assert kept == 1  # business/audit rows preserved
    finally:
        conn.close()


def test_busy_timeout_configured(settings, seeded_db):
    row = seeded_db.execute("PRAGMA busy_timeout").fetchone()
    assert int(row[0]) == database.BUSY_TIMEOUT_MS
    row = seeded_db.execute("PRAGMA foreign_keys").fetchone()
    assert int(row[0]) == 1
