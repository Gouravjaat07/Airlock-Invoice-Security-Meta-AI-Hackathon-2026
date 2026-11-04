"""SQLite lifecycle: connections, pragmas, versioned migrations.

One connection per unit of work (never a shared global). All SQL is
parameterized. Migrations are plain versioned `.sql` files applied once,
tracked in `schema_migrations`.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger("airlock.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BUSY_TIMEOUT_MS = 5000


def connect(settings: Settings) -> sqlite3.Connection:
    """Open a configured connection (WAL, FK on, busy timeout)."""
    db_file = Path(settings.db_path)
    if str(db_file.parent) not in (".", ""):
        try:
            db_file.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Driver/OS detail stays server-side (may carry paths or SQL).
            logger.error("database directory setup failed: %r", exc)
            raise AppError(ErrorCode.DATABASE,
                           "Cannot create database directory") from exc
    try:
        conn = sqlite3.connect(str(db_file), timeout=BUSY_TIMEOUT_MS / 1000,
                               check_same_thread=False, isolation_level=None)
    except sqlite3.Error as exc:
        logger.error("database open failed: %r", exc)
        raise AppError(ErrorCode.DATABASE, "Cannot open database") from exc
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    except sqlite3.Error as exc:
        conn.close()
        logger.error("database configure failed: %r", exc)
        raise AppError(ErrorCode.DATABASE, "Cannot configure database") from exc
    return conn


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row[0]) for row in rows}


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def current_version(conn: sqlite3.Connection) -> int:
    applied = _applied_versions(conn)
    return max(applied) if applied else 0


def require_schema_current(settings: Settings) -> int:
    """Startup/readiness gate: refuse to run on a stale schema.

    Returns the current version when every migration is applied. Raises
    AppError(E_DATABASE) naming the exact repair command otherwise.
    Never applies migrations itself: schema changes stay owner-operated
    (`python -m app.cli db upgrade`).
    """
    conn = connect(settings)
    try:
        try:
            current = current_version(conn)
        except sqlite3.Error as exc:
            logger.error("schema version check failed: %r", exc)
            raise AppError(ErrorCode.DATABASE,
                           "Cannot verify database schema") from exc
    finally:
        conn.close()
    latest = latest_version()
    if current < latest:
        raise AppError(
            ErrorCode.DATABASE,
            f"Database schema is not current (version {current}, latest "
            f"{latest}). Run: python -m app.cli db upgrade")
    return current


def latest_version() -> int:
    versions = []
    for path in _migration_files():
        try:
            versions.append(int(path.stem.split("_")[0]))
        except ValueError:
            continue
    return max(versions) if versions else 0


def upgrade(settings: Settings) -> dict:
    """Apply pending migrations. Returns {applied, current_version}."""
    conn = connect(settings)
    try:
        applied_before = _applied_versions(conn)
        applied: list[int] = []
        for path in _migration_files():
            try:
                version = int(path.stem.split("_")[0])
            except ValueError:
                raise AppError(ErrorCode.DATABASE,
                               f"Bad migration filename: {path.name}")
            if version in applied_before:
                continue
            sql = path.read_text(encoding="utf-8")
            # executescript() runs in autocommit and implicitly commits, so
            # the migration + version row are wrapped in explicit SQL.
            script = (
                "BEGIN;\n" + sql
                + f"\nINSERT INTO schema_migrations (version, applied_at) VALUES ("
                f"{version}, '{SYSTEM_CLOCK.now().isoformat()}');\nCOMMIT;"
            )
            try:
                conn.executescript(script)
            except sqlite3.Error as exc:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                logger.error("migration %s failed: %r", path.name, exc)
                raise AppError(ErrorCode.DATABASE,
                               f"Migration {path.name} failed") from exc
            applied.append(version)
        return {"applied": applied, "current_version": current_version(conn)}
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE transaction with commit/rollback.

    Raises AppError(E_DATABASE) on sqlite errors so callers fail closed.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.Error as exc:
        logger.error("transaction begin failed: %r", exc)
        raise AppError(ErrorCode.DATABASE, "Cannot begin transaction") from exc
    try:
        yield conn
    except AppError:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    except sqlite3.Error as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        logger.error("transaction body failed: %r", exc)
        raise AppError(ErrorCode.DATABASE, "Database error") from exc
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    else:
        try:
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            logger.error("transaction commit failed: %r", exc)
            raise AppError(ErrorCode.DATABASE, "Cannot commit") from exc


def is_integrity_ok(settings: Settings) -> tuple[bool, str]:
    try:
        conn = connect(settings)
    except AppError as exc:
        return False, exc.message
    try:
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            return False, str(exc)
        ok = row is not None and str(row[0]).lower() == "ok"
        return ok, str(row[0]) if row else "no result"
    finally:
        conn.close()
