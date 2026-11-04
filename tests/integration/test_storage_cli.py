"""Integration tests: storage edges, repositories, CLI, scripts."""

from __future__ import annotations

import json

import pytest

from app.core.errors import AppError
from app.services import case_service
from app.storage import database
from app.storage.database import transaction
from app.storage.repositories import (
    CaseRepository,
    EvalRepository,
    FactRepository,
    InvoiceIndexRepository,
    PaymentRepository,
    PurchaseOrderRepository,
    RateLimitRepository,
    VendorRepository,
)
from tests.conftest import fixture_bytes


def test_store_read_delete_errors(settings, store):
    with pytest.raises(AppError) as exc_info:
        store.read_bytes("aa/missing.pdf")
    # Regression (F3): no filesystem path in the client-facing message.
    assert exc_info.value.message == "Cannot read artifact"
    store.delete("aa/missing.pdf")  # missing_ok: no error


def test_store_write_failure(settings, tmp_path, monkeypatch):
    from app.storage.artifacts import LocalBlobStore
    blob_store = LocalBlobStore(settings)
    blob_store.ensure_root()

    def _boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("builtins.open", _boom)
    with pytest.raises(AppError) as exc_info:
        blob_store.store_bytes(b"data", artifact_id="art-x",
                               extension=".pdf", sha256="ab" * 32)
    assert exc_info.value.code == "E_STORAGE"
    assert exc_info.value.message == "Cannot store artifact"


def test_sweep_orphans(seeded_db, settings, store):
    created = case_service.create_case(
        seeded_db, settings, store,
        [("invoice", "c.pdf", fixture_bytes("invoices/clean.pdf"))])
    assert created["case"]["id"]
    stray = store.root / "zz" / "orphan.pdf"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"junk")
    assert store.sweep_orphans(seeded_db) == 1
    assert not stray.exists()
    # Referenced blobs survive.
    assert store.sweep_orphans(seeded_db) == 0


def test_sweep_missing_root(settings, seeded_db):
    from pathlib import Path
    from app.storage.artifacts import LocalBlobStore
    settings.blob_dir = str(Path(settings.blob_dir) / "nope")
    assert LocalBlobStore(settings).sweep_orphans(seeded_db) == 0


def test_intake_failure_cleans_blobs(seeded_db, settings, store,
                                     monkeypatch):

    def _fail(*args, **kwargs):
        raise AppError("E_DATABASE", "boom")
    monkeypatch.setattr(CaseRepository, "create", _fail)
    before = {path.name for path in store.root.rglob("*") if path.is_file()}
    with pytest.raises(AppError):
        case_service.create_case(
            seeded_db, settings, store,
            [("invoice", "c.pdf", fixture_bytes("invoices/clean.pdf"))])
    after = {path.name for path in store.root.rglob("*") if path.is_file()}
    assert after == before


def test_database_connect_failure(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    from app.config import Settings
    settings = Settings(db_path=str(blocker / "db.sqlite"))
    with pytest.raises(AppError):
        database.connect(settings)


def test_database_bad_migration_filename(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(database, "MIGRATIONS_DIR", tmp_path)
    (tmp_path / "oops.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(AppError):
        database.upgrade(settings)


def test_database_migration_failure(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(database, "MIGRATIONS_DIR", tmp_path)
    (tmp_path / "001_bad.sql").write_text("CREATE TABLE nope (;",
                                          encoding="utf-8")
    with pytest.raises(AppError):
        database.upgrade(settings)


def test_transaction_error_paths(seeded_db):
    with pytest.raises(AppError) as exc_info:
        with transaction(seeded_db):
            seeded_db.execute("SELECT * FROM missing_table")
    # Regression (F3): driver text (table names, SQL) stays server-side.
    assert exc_info.value.message == "Database error"
    class _Boom(Exception):
        pass
    with pytest.raises(_Boom):
        with transaction(seeded_db):
            raise _Boom()
    with pytest.raises(AppError):
        with transaction(seeded_db):
            pass
        with transaction(seeded_db):
            seeded_db.execute("BEGIN IMMEDIATE")
            raise AppError("E_INTERNAL", "x")


def test_transaction_begin_failure(settings):
    conn = database.connect(settings)
    conn.close()  # execute on a closed connection raises sqlite3.Error
    with pytest.raises(AppError):
        with transaction(conn):
            pass


def test_integrity_failure(settings, tmp_path):
    settings.db_path = str(tmp_path / "broken.db")
    Path = __import__("pathlib").Path
    Path(settings.db_path).write_bytes(b"not a database at all" * 100)
    ok, _ = database.is_integrity_ok(settings)
    assert ok is False


def test_repository_edges(seeded_db):
    conn = seeded_db
    vendors = VendorRepository()
    assert vendors.candidates_by_prefix(conn, "zzz-nope") == []
    assert vendors.update(conn, vendor_id="ven-acme-flour",
                          expected_version=1, now="t") is True
    assert vendors.list_bank_changes(conn, "ven-acme-flour") == []
    assert PurchaseOrderRepository().get(conn, "po-missing") is None
    assert PurchaseOrderRepository().update_remaining(
        conn, po_id="po-acme-1001", remaining="1",
        expected_version=999) is False
    assert InvoiceIndexRepository().get(conn, "k-missing") is None
    assert PaymentRepository().get_by_proposal(conn, "p-missing") is None
    assert PaymentRepository().list_for_case(conn, "c-missing") == []
    assert FactRepository().list_for_case(conn, "c-missing") == []
    assert EvalRepository().get(conn, "run-missing") is None
    assert RateLimitRepository().get(conn, "k-missing") is None
    from app.storage.repositories import (
        ArtifactRepository,
        ChallengeRepository,
        ProposalRepository,
        VerdictRepository,
    )
    assert ArtifactRepository().count_for_case(conn, "c-missing") == 0
    assert ChallengeRepository().get(conn, "ch-missing") is None
    assert ProposalRepository().get_by_case(conn, "c-missing") is None
    assert VerdictRepository().latest_for_case(conn, "c-missing") is None
    assert VerdictRepository().list_for_case(conn, "c-missing") == []
    assert CaseRepository().get_by_idempotency(conn, "k-missing") is None


def test_eval_repo_finish(seeded_db):
    from app.storage.database import transaction
    repo = EvalRepository()
    with transaction(seeded_db):
        repo.create(seeded_db, run_id="run-1", now="t")
        repo.finish(seeded_db, run_id="run-1", status="completed",
                    summary={"a": 1}, results=[{"b": 2}])
    row = repo.get(seeded_db, "run-1")
    assert json.loads(row["summary_json"]) == {"a": 1}


def test_audit_repo_latest_empty(seeded_db):
    from app.storage.repositories import AuditRepository
    assert AuditRepository().latest(seeded_db) is None
    assert AuditRepository().list_for_case(seeded_db, "c") == []


def test_cli_db_and_health(settings, monkeypatch, capsys):
    from app import cli as cli_mod
    monkeypatch.setenv("AIRLOCK_DB_PATH", settings.db_path)
    monkeypatch.setenv("AIRLOCK_BLOB_DIR", settings.blob_dir)
    assert cli_mod.main(["db", "upgrade"]) == 0
    assert cli_mod.main(["health"]) == 0
    out = capsys.readouterr().out
    assert "current_version" in out and '"status": "ok"' in out
    assert cli_mod.main(["storage", "sweep"]) == 0
    monkeypatch.setenv("AIRLOCK_ENV", "production")
    monkeypatch.setenv("AIRLOCK_ALLOW_INSECURE_COOKIES", "1")
    assert cli_mod.main(["health"]) == 1


def test_cli_health_degraded(monkeypatch, tmp_path, capsys):
    from app import cli as cli_mod
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"junk" * 100)
    monkeypatch.setenv("AIRLOCK_DB_PATH", str(broken))
    assert cli_mod.main(["health"]) == 1


def test_setup_seed_verify_scripts(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    import seed_demo
    import setup_airlock
    import verify_audit_chain
    db_path = tmp_path / "demo.db"
    blob_dir = tmp_path / "blobs"
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", "demo-pin-9")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\n',
                                             encoding="utf-8")
    assert setup_airlock.main(["--non-interactive",
                               "--env-file", "test.env"]) == 0
    content = (tmp_path / "test.env").read_text(encoding="utf-8")
    assert "AIRLOCK_PIN_HASH=" in content
    assert "demo-pin-9" not in content
    monkeypatch.setenv("AIRLOCK_DB_PATH", str(db_path))
    monkeypatch.setenv("AIRLOCK_BLOB_DIR", str(blob_dir))
    values = dict(line.split("=", 1) for line in content.splitlines()
                  if "=" in line and not line.startswith("#"))
    monkeypatch.setenv("AIRLOCK_BANK_HASH_KEY",
                       values["AIRLOCK_BANK_HASH_KEY"])
    assert seed_demo.main([]) == 0
    assert seed_demo.main([]) == 0  # idempotent
    assert seed_demo.main(["--force"]) == 1  # --force needs --yes
    assert verify_audit_chain.main([]) == 0
    assert db_path.is_file()


def test_setup_short_pin_rejected(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    import setup_airlock
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\n',
                                             encoding="utf-8")
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", "abc")
    assert setup_airlock.main(["--non-interactive"]) == 1


def test_reset_demo_refusals(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, "scripts")
    import reset_demo
    assert reset_demo.main([]) == 1  # refuses without --yes
    # Database outside the project root is never deleted (pytest tmp dirs
    # live inside the repo, so point at the drive root instead).
    outside = __import__("pathlib").Path(tmp_path.anchor) / "airlock-outside-test"
    monkeypatch.setenv("AIRLOCK_DB_PATH", str(outside / "x.db"))
    monkeypatch.setenv("AIRLOCK_BLOB_DIR", str(outside / "blobs"))
    assert reset_demo.main(["--yes"]) == 1


def test_make_fixtures_check():
    import sys
    sys.path.insert(0, "scripts")
    import make_fixtures
    assert make_fixtures.main(["--check"]) == 0
