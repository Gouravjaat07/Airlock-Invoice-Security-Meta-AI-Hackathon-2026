# Database (Phase 2)

SQLite via stdlib `sqlite3` (`app/storage/database.py`): WAL mode,
foreign keys on, 5 s busy timeout, one connection per request/unit of
work, parameterized SQL only. Migrations are versioned
`app/storage/migrations/*.sql`, tracked in `schema_migrations`;
`python -m app.cli db upgrade` applies pending ones (each atomic).

## Startup readiness

Migrations are owner-operated: run `db upgrade` before starting the
server (see `ACCEPTANCE.md` §11). The server refuses to boot when
migrations are pending — startup fails fast with `Database schema is
not current ... Run: python -m app.cli db upgrade` instead of crashing
later with `no such table` on the first query. `/health` likewise
reports `degraded` + `database: "migrations_pending"` until the schema
is current.

## Tables

`cases` (optimistic `version`), `artifacts` (sha256, storage keys),
`facts` (field-level value + provenance + taint + status), `vendors`
(unique `name_norm`), `vendor_bank_changes` (pending/active workflow),
`purchase_orders` (unique vendor+reference), `invoice_index` (duplicate
composite primary key), `purchase_orders.remaining_amount` is checked
but never auto-decremented (administrative state, see POLICY.md),
`verdicts` (immutable), `proposals` (unique
proposal hash), `auth_sessions` (token hash only), `auth_challenges`
(bearer hash only, single-use), `mock_payments` (unique idempotency key),
`audit_events`
(append-only triggers + hash chain), `rate_limits` (DB-backed windows),
`eval_runs`, `schema_migrations`.

## Transactions

Multi-record mutations share one `BEGIN IMMEDIATE` transaction:
proposal + duplicate reservation, challenge consumption + payment,
fact edit + audit, vendor change + audit. Audit write failures roll
back the business operation (a mock payment never commits without its
audit events).

## Limits (prototype)

Single-writer SQLite: concurrent writers serialize (busy timeout, then
a structured error). No read replicas, no online backup wiring
(`VACUUM INTO` works for manual copies). See [MIGRATION.md](MIGRATION.md)
for the PostgreSQL path; repositories isolate SQL for that move.
