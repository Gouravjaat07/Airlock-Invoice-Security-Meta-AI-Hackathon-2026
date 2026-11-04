# Audit log (Phase 2)

Append-only `audit_events` table (`app/services/audit_service.py`).
Each event stores a canonical SHA-256 over (sequence-adjacent fields,
timestamp, type, case, actor, sanitized payload, previous hash), so any
modification, deletion, or reorder breaks verification
(`python scripts/verify_audit_chain.py`, `POST /api/v1/audit/verify`).
SQLite triggers reject casual `UPDATE`/`DELETE`.

## Honest limitation

The chain is **tamper-evident, not tamper-proof**: a privileged actor
with database write access can rewrite history and recompute every
hash. It catches accidents, application bugs, and unprivileged
tampering — not a malicious administrator. Production needs external
anchoring (WORM log shipping, signed checkpoints, or transparency-log
witnessing) plus restricted DB access. This is recorded, not solved,
in Phase 2.

Business operations write their audit event in the same transaction;
if the audit write fails, the operation (including mock payment)
rolls back. No PINs, tokens, raw bank references, or document bodies
are ever logged.
