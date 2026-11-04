"""Startup schema readiness: fail fast with the repair command.

Regression tests for the Phase 4 login outage: uvicorn booted against
an unmigrated database and login crashed with
`sqlite3.OperationalError: no such table: rate_limits` (the rate-limit
check is the first query in `sessions.login`). Migrations stay
owner-operated, but startup must refuse to serve and `/health` must
report degraded instead of pretending the app is functional.
"""

import asyncio

import pytest

from app.config import override_settings
from app.core.errors import AppError
from app.storage import database


def _startup(settings) -> None:
    """Run the real lifespan startup hook against `settings`."""
    from app.main import _lifespan, create_app

    override_settings(settings)
    try:
        app = create_app()
        asyncio.run(_lifespan(app).__aenter__())
    finally:
        override_settings(None)


def test_startup_refuses_unmigrated_db(settings):
    """Lifespan startup fails fast naming the repair command."""
    with pytest.raises(AppError, match=r"db upgrade"):
        _startup(settings)


def test_startup_accepts_migrated_db(seeded_db, settings):
    """Lifespan startup passes once migrations are applied."""
    _startup(settings)
    assert database.current_version(seeded_db) == database.latest_version()


def test_health_degraded_when_migrations_pending(settings):
    """`/health` reports degraded while migrations are pending."""
    from app.main import create_app
    from tests.asgi_harness import ASGIClient

    override_settings(settings)
    try:
        body = ASGIClient(create_app()).get("/api/v1/health").json()
    finally:
        override_settings(None)
    assert body["status"] == "degraded"
    assert body["database"] == "migrations_pending"
    assert body["schema_version"] == 0


def test_health_ok_when_schema_current(app_client):
    """`/health` still reports ok on a migrated database."""
    body = app_client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["schema_version"] == database.latest_version()


def test_rate_limits_table_ready_after_upgrade(db_conn):
    """Fresh upgrade creates `rate_limits`; a missing row is not an error."""
    from app.auth import rate_limit

    tables = {row[0] for row in db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "rate_limits" in tables
    assert db_conn.execute("SELECT COUNT(*) FROM rate_limits").fetchone()[0] == 0
    # First login attempt on a fresh database must be allowed, not crash.
    assert rate_limit.is_locked(db_conn, "login:owner", limit=5,
                               window_seconds=900) is False
    allowed, _ = rate_limit.check_and_hit(db_conn, "login:owner", limit=5,
                                          window_seconds=900)
    assert allowed is True
