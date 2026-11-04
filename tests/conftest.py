"""Pytest path setup: make scripts/ importable for all Phase 1 tests."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# --- Phase 2 shared fixtures (isolated settings, seeded DB, API client) ---
# App imports stay inside fixtures so Phase 1 tests never require app deps.

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _provider_pool_isolation():
    from app.providers.http import POOL
    from app.providers.resilience import GUARDS
    GUARDS.reset_for_tests()
    POOL.clear_test_transports()
    yield
    GUARDS.reset_for_tests()
    POOL.clear_test_transports()


@pytest.fixture()
def workdir(tmp_path):
    (tmp_path / "blobs").mkdir()
    return tmp_path


@pytest.fixture()
def test_pin():
    import secrets as _secrets
    return "pin-" + _secrets.token_hex(4)


@pytest.fixture()
def settings(workdir, test_pin):
    import secrets as _secrets
    from app.auth.pin import hash_pin
    from app.config import Settings
    try:
        pin_hash = hash_pin(test_pin)
    except RuntimeError:
        # argon2-cffi not installed: auth tests fail loudly below, while
        # non-auth tests can still run. Never a committed hash.
        pin_hash = "ARGON2-MISSING"
    return Settings(
        pin_hash=pin_hash,
        session_secret=_secrets.token_urlsafe(24),
        bank_hash_key=("test-bank-key-" + _secrets.token_hex(8)).encode(),
        db_path=str(workdir / "airlock.db"),
        blob_dir=str(workdir / "blobs"),
        environment="test",
        allow_insecure_cookies=True,
        fixture_reader_enabled=True,
        fixtures_dir=str(ROOT_DIR / "fixtures"),
        enable_eval_api=True,
        login_max_attempts=5,
        lockout_minutes=15,
    )


@pytest.fixture()
def db_conn(settings):
    from app.storage import database
    database.upgrade(settings)
    conn = database.connect(settings)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def seeded_db(db_conn, settings):
    """Database upgraded + synthetic registry seeded with the test bank key."""
    import json as _json
    from app.core.clock import SYSTEM_CLOCK
    from app.core.security import bank_fingerprint
    from app.domain.vendors import normalize_vendor_name
    from app.storage.database import transaction
    from app.storage.repositories import (
        PurchaseOrderRepository,
        VendorRepository,
    )
    data = _json.loads((ROOT_DIR / "registry" / "synthetic_vendors.json").read_text())
    now = SYSTEM_CLOCK.now().isoformat()
    vendors = VendorRepository()
    pos = PurchaseOrderRepository()
    with transaction(db_conn):
        for entry in data["vendors"]:
            vendors.create(
                db_conn, vendor_id=entry["vendor_id"], name=entry["name"],
                name_norm=normalize_vendor_name(entry["name"]),
                bank_fp=bank_fingerprint(entry["bank_reference"],
                                         settings.bank_hash_key),
                catalogue_json=_json.dumps(entry.get("catalogue", [])),
                cap=entry.get("per_invoice_cap"), now=now)
        for entry in data["purchase_orders"]:
            pos.create(db_conn, po_id=entry["po_id"],
                       vendor_id=entry["vendor_id"],
                       po_reference=entry["po_reference"],
                       currency=entry["currency"],
                       original=entry["original_amount"],
                       remaining=entry["remaining_amount"])
            if entry.get("status", "open") != "open":
                db_conn.execute("UPDATE purchase_orders SET status = ?"
                                " WHERE po_id = ?",
                                (entry["status"], entry["po_id"]))
    return db_conn


@pytest.fixture()
def store(settings):
    from app.storage.artifacts import LocalBlobStore
    blob_store = LocalBlobStore(settings)
    blob_store.ensure_root()
    return blob_store


@pytest.fixture()
def app_client(settings, seeded_db):
    """Socket-free ASGI client bound to the test settings (isolated DB)."""
    from app.config import override_settings
    from app.main import create_app
    from tests.asgi_harness import ASGIClient
    override_settings(settings)
    try:
        yield ASGIClient(create_app())
    finally:
        override_settings(None)


@pytest.fixture()
def authed_client(app_client, test_pin):
    """Client with an owner session cookie; CSRF token attached."""
    response = app_client.post("/api/v1/auth/login", json={"pin": test_pin})
    assert response.status_code == 200, response.text
    csrf = response.json()["csrf_token"]
    app_client.headers["X-CSRF-Token"] = csrf
    return app_client


def fixture_bytes(name: str) -> bytes:
    return (ROOT_DIR / "fixtures" / name).read_bytes()


def upload_case(client, invoice: str, *, delivery=None, voice=None):
    files = [("invoice", (invoice.split("/")[-1], fixture_bytes(invoice),
                          "application/octet-stream"))]
    if delivery:
        files.append(("delivery", (delivery.split("/")[-1],
                                   fixture_bytes(delivery),
                                   "application/octet-stream")))
    if voice:
        files.append(("voice", (voice.split("/")[-1], fixture_bytes(voice),
                                "application/octet-stream")))
    response = client.post("/api/v1/cases", files=files)
    assert response.status_code == 200, response.text
    return response.json()
