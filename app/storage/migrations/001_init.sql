-- Airlock Phase 2 initial schema (version 1).
-- SQLite, applied by app/storage/database.py in filename order.
-- All timestamps are UTC ISO-8601 TEXT. Money is TEXT (canonical Decimal).

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id                    TEXT PRIMARY KEY,
    state                 TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    processing_started_at TEXT,
    completed_at          TEXT,
    error_code            TEXT,
    error_summary         TEXT,
    idempotency_key       TEXT UNIQUE,
    version               INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_cases_state ON cases(state);

CREATE TABLE IF NOT EXISTS artifacts (
    id          TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL REFERENCES cases(id),
    sha256      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    media_type  TEXT NOT NULL,
    extension   TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    storage_key TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_case ON artifacts(case_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha ON artifacts(sha256);
CREATE INDEX IF NOT EXISTS idx_artifacts_storage ON artifacts(storage_key);

CREATE TABLE IF NOT EXISTS facts (
    id                TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL REFERENCES cases(id),
    field             TEXT NOT NULL,
    value_json        TEXT NOT NULL,
    source_json       TEXT NOT NULL,
    producer_json     TEXT NOT NULL,
    taint_class       TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    validated_by      TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_case_field ON facts(case_id, field);

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id               TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    name_norm               TEXT NOT NULL UNIQUE,
    active_bank_fingerprint TEXT NOT NULL,
    catalogue_json          TEXT NOT NULL DEFAULT '[]',
    per_invoice_cap         TEXT,
    status                  TEXT NOT NULL DEFAULT 'active',
    version                 INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendor_bank_changes (
    id              TEXT PRIMARY KEY,
    vendor_id       TEXT NOT NULL REFERENCES vendors(vendor_id),
    new_fingerprint TEXT NOT NULL,
    initiated_by    TEXT NOT NULL,
    requested_at    TEXT NOT NULL,
    effective_at    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    audit_ref       TEXT
);
CREATE INDEX IF NOT EXISTS idx_bank_changes_vendor ON vendor_bank_changes(vendor_id, status);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id            TEXT PRIMARY KEY,
    vendor_id        TEXT NOT NULL REFERENCES vendors(vendor_id),
    po_reference     TEXT NOT NULL,
    currency         TEXT NOT NULL,
    original_amount  TEXT NOT NULL,
    remaining_amount TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'open',
    version          INTEGER NOT NULL DEFAULT 1,
    UNIQUE (vendor_id, po_reference)
);

CREATE TABLE IF NOT EXISTS invoice_index (
    dup_key             TEXT PRIMARY KEY,
    vendor_id           TEXT NOT NULL,
    case_id             TEXT NOT NULL REFERENCES cases(id),
    invoice_number_norm TEXT NOT NULL,
    total               TEXT NOT NULL,
    issue_date          TEXT NOT NULL,
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_invoice_index_case ON invoice_index(case_id);

CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id       TEXT PRIMARY KEY,
    case_id          TEXT NOT NULL REFERENCES cases(id),
    verdict          TEXT NOT NULL,
    reasons_json     TEXT NOT NULL,
    rule_ids_json    TEXT NOT NULL,
    rule_details_json TEXT NOT NULL DEFAULT '[]',
    policy_version   TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verdicts_case ON verdicts(case_id);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id        TEXT PRIMARY KEY,
    case_id            TEXT NOT NULL REFERENCES cases(id),
    vendor_id          TEXT NOT NULL,
    payee_display_name TEXT NOT NULL,
    amount             TEXT NOT NULL,
    currency           TEXT NOT NULL,
    due_date           TEXT NOT NULL,
    invoice_reference  TEXT NOT NULL,
    verdict_id         TEXT NOT NULL REFERENCES verdicts(verdict_id),
    proposal_hash      TEXT NOT NULL UNIQUE,
    expires_at         TEXT NOT NULL,
    status             TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proposals_case ON proposals(case_id);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id       TEXT PRIMARY KEY,
    token_hash       TEXT NOT NULL UNIQUE,
    csrf_hash        TEXT NOT NULL,
    owner_id         TEXT NOT NULL DEFAULT 'owner',
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    revoked_at       TEXT
);

CREATE TABLE IF NOT EXISTS auth_challenges (
    challenge_id    TEXT PRIMARY KEY,
    proposal_hash   TEXT NOT NULL,
    session_id      TEXT NOT NULL REFERENCES auth_sessions(session_id),
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    used_at         TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_challenges_proposal ON auth_challenges(proposal_hash);

CREATE TABLE IF NOT EXISTS mock_payments (
    payment_id      TEXT PRIMARY KEY,
    proposal_id     TEXT NOT NULL REFERENCES proposals(proposal_id),
    idempotency_key TEXT NOT NULL UNIQUE,
    proposal_hash   TEXT NOT NULL,
    case_id         TEXT NOT NULL,
    amount          TEXT NOT NULL,
    currency        TEXT NOT NULL,
    executed_at     TEXT NOT NULL,
    status          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    case_id      TEXT,
    event_type   TEXT NOT NULL,
    actor_type   TEXT NOT NULL,
    actor_id     TEXT,
    payload_json TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    event_hash   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_events(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events(event_type);

-- Append-only enforcement: casual UPDATE/DELETE aborts. (A privileged
-- attacker who rewrites the file can still recompute the chain; the chain
-- is tamper-evident, not tamper-proof. See docs/phase2/AUDIT.md.)
DROP TRIGGER IF EXISTS audit_no_update;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;
DROP TRIGGER IF EXISTS audit_no_delete;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit_events is append-only');
END;

CREATE TABLE IF NOT EXISTS rate_limits (
    scope_key    TEXT PRIMARY KEY,
    window_start TEXT NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id       TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    status       TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    results_json TEXT NOT NULL DEFAULT '[]'
);
