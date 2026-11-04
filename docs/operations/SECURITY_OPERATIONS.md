# Security operations

Day-to-day security posture for an Airlock deployment. Architecture
reference: `docs/architecture/TRUST_BOUNDARIES.md`.

## Authentication & approval

- Single owner, Argon2id PIN, 5-fail/15-min lockout, 30-min
  sessions, CSRF on mutations, single-use approval challenges
  (5-min TTL), proposal-hash re-verification on every read.
- Approval requires session + challenge binding + PIN + still-
  current ALLOW verdict with matching `verdict_id`. Replay,
  tamper, and stale-verdict attempts fail closed (tested).

## Secrets

- Sources: process env only (`.env` never auto-loaded).
  `AIRLOCK_PIN_HASH`, `AIRLOCK_SESSION_SECRET`,
  `AIRLOCK_BANK_HASH_KEY`, `MODEL_API_KEY`, `BASETEN_API_KEY`,
  `GLIMMER_API_KEY`.
- Never logged, never in audit events, never in API responses,
  never in the frontend. `check_secret_hygiene.py` scans the tree
  (patterns, not proof — treat a clean scan as necessary, not
  sufficient).
- Rotation: PIN via setup flow; API keys in provider dashboards
  + process restart (pool pins credentials). Bank-key rotation
  invalidates stored fingerprints — a migration event, not a
  silent swap.

## Data handling

- Uploads: type sniffing (never extension-only), 10 MB / 5 files /
  20 PDF pages / 40M px / 300 s audio/video caps, atomic blob
  writes, SHA-256 identity, per-case isolation, temp cleanup.
- Providers receive only the configured task input, inline
  (`store:false`); no Files-API retention; no remote IDs exposed.
- Voice transcripts stay T2; audit stores metadata, never raw
  sensitive documents, audio, credentials, or full payloads.
- Standard mode only: invoice content is never submitted under
  Contributor terms.

## Payments

Mock-only by construction: `mock_payment_service` records
`MOCK_COMPLETED` rows labeled `MOCK PAYMENT — NO MONEY
TRANSFERRED`. No banking code exists. Idempotency key =
proposal hash (UNIQUE + transactional double-check).

## Audit

Append-only, hash-chained (`GENESIS`-rooted), written in the same
`BEGIN IMMEDIATE` transaction as each business write; SQL triggers
reject UPDATE/DELETE. Verify: `POST /api/v1/audit/verify` or
`scripts/verify_audit_chain.py` (read-only against live DBs).

## Adversarial posture

Prompt injection (visible/hidden/metadata/voice/delivery),
malformed media, provider failures, and auth bypasses are covered
in `tests/adversarial/`, `tests/failure_injection/`, and
`tests/security/`. False-ALLOW on the attack corpus must stay 0
(`phase5_eval.py` fails otherwise).

## Known operational limits

Single owner/PIN, local secrets (no KMS), single-writer SQLite,
no PO reserve ledger (`remaining_amount` never decremented —
R5 concurrency hole, see Phase 2 LIMITATIONS), loopback-only
public intake routes, no malware scan/TLS termination/backups/
metrics. Harden each before any production claim.
