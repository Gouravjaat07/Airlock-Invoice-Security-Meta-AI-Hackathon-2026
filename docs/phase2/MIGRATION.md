# Migration path (beyond Phase 2)

The prototype is a modular monolith on SQLite + local blobs + synchronous
processing. Boundaries are drawn for later moves without domain rewrites:

- **PostgreSQL**: `app/storage/repositories.py` owns every SQL statement
  and takes connections as parameters. Port by adding a `psycopg`
  connection factory (keeping the transaction helper's semantics),
  translating the DDL (`SERIAL`/`GENERATED` keys, `BYTEA` not needed —
  money stays `TEXT`), and re-running the repository + concurrency
  tests. Audit triggers and unique constraints port 1:1.
- **Object storage**: `LocalBlobStore` is the only filesystem coupling
  (server-generated keys, content hashes). A new class implementing
  `store_bytes/read_bytes/delete` against S3/GCS + signed-URL reads
  keeps intake, dedupe, and quarantine logic unchanged.
- **Background workers**: `app/pipeline/process.py::run_case` is already
  service-layer and request-agnostic; enqueue `(case_id, force)` on a
  durable queue (RQ/Celery/Arq), keep the state machine + optimistic
  versioning, and add a `CLAIMED_BY`/heartbeat column for crash recovery.
  The in-process semaphore is then replaced by queue concurrency.
- **Multi-tenancy/identity**: sessions are single-owner (`owner_id` is
  constant). Real identity (OIDC/WebAuthn), per-tenant keys, and KMS
  secret management are deployment projects, not refactors — see
  [LIMITATIONS.md](LIMITATIONS.md).
