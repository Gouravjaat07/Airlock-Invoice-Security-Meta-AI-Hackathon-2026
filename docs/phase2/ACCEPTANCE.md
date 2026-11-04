# Phase 2 final acceptance (Airlock)

Verified against the implementation in `app/` on 2026-11-01: full suite
436 passed / 1 skipped (see §13), strict gate READY, and a live-uvicorn
acceptance run of 26/26 checks (§12). Companion references: `API.md`, `AUTH.md`,
`DATABASE.md`, `POLICY.md`, `AUDIT.md`, `ADAPTERS.md`, `MIGRATION.md`,
`EVALUATION.md`, `LIMITATIONS.md`.

Three readiness claims are different and stay separate:

| Claim | Meaning | Status |
|---|---|---|
| Phase 2 automated gate | `phase2_check.py --strict` passes | READY (21/21) |
| Phase 2 operational acceptance | live-server synthetic workflow (§12) passes | 26/26 PASS |
| Production deployment readiness | hardened, reviewed, operable in production | NOT READY (see §16) |

## 1. Architecture summary

Modular monolith (FastAPI + SQLite + local blobs, synchronous
processing). Layers: `app/api` (routes, envelope errors) →
`app/services` (transactions, authz) → `app/pipeline` (ingest, reader,
corroborate, policy, propose, state machine) → `app/storage`
(repositories, migrations, blob store). Cross-cutting: `app/auth`
(PIN/sessions/challenges/rate limits), `app/domain` (enums, taint,
canonical hashes), `app/adapters` (fixture reader, mock SAM/ASR,
template explainer, mock-only payments), `app/evaluation` (flag-gated
scenario runs), `app/config` (validated settings).

## 2. Trust boundaries

```
T3 raw artifacts (PDF/image/audio/video bytes) ── untrusted, hashed
T2 model/adapter output (extraction, counts, transcripts) ── untrusted,
    schema-validated, never authoritative
T1 trusted config/registry (policy TOML, vendors, POs) ── owner/admin only
T0 owner input (PIN auth, fact edits, approvals) ── authenticated session
```

Rules: T2/T3 never authorize actions; the explainer receives only
verdict + rule results (never raw documents); invoice content cannot
write the registry; prompts embedded in documents/transcripts stay
data (adversarial tests in `tests/adversarial/`).

## 3. Data flow

Upload (`POST /cases`, multipart) → sniff + bound-check → content hash
→ atomic blob write → case row (UPLOADED) → `POST .../process`: reader
→ schema validate → vendor resolve → SAM/voice evidence → corroborate
→ R1–R10 → verdict → proposal iff ALLOW (duplicate key reserved) →
owner login → challenge → confirm (PIN + challenge + rechecks) → mock
payment. Every step appends hash-chained audit events in the same
transaction as the business write.

## 4. R1–R10 policy semantics

See `POLICY.md` (authoritative: `app/pipeline/policy.py`). Precedence:
R9 failure → DENY; any R1/R2/R3/R4/R8 failure → DENY; any
R5/R6/R7/R10 failure → ESCALATE; else ALLOW_PROPOSAL. Fixed
interpretations (policy v2.0.0): exact normalized vendor match (R1);
HMAC bank fingerprint, missing reference fails R8 (R2); exact Decimal
arithmetic (R3); composite duplicate key
`vendor|number|total|issue_date` (R4); cap + PO authorization (R5,
administrative `remaining_amount`, never auto-decremented); due-date
window (R6); SAM/voice conflicts (R7); schema/required fields (R8);
required-verifier errors incl. missing bank key and SAM errors (R9);
>1 plausible vendor within 2 edits escalates (R10).
ALLOW_PROPOSAL permits proposal creation only — never payment.

## 5. Proposal state transitions

Case machine (`app/pipeline/state_machine.py`, enforced in services
with optimistic versioning): UPLOADED → READING → CORROBORATING →
VERDICT → PROPOSED | REJECTED | NEEDS_REVIEW; PROPOSED →
CONFIRMED → EXECUTED (atomic with payment); NEEDS_REVIEW/PROPOSED →
REJECTED (owner); ERROR/REJECTED/NEEDS_REVIEW/EXPIRED → READING
(explicit re-run after a trusted event). Proposals: PENDING →
CONFIRMED | EXPIRED | REJECTED (superseded); the canonical hash covers
exactly the owner-authorized values and is re-verified on every read.

## 6. Authentication and approval lifecycle

See `AUTH.md`. Argon2id owner PIN (no default; fails closed) → opaque
256-bit session (hash at rest, 30-min absolute expiry, revocation,
HttpOnly + Secure + SameSite=Lax cookie, optional Bearer [REDACTED] →
per-proposal challenge (random bearer, hash at rest per migration 003,
bound to proposal hash + session, 5-min expiry, single-use consumed
transactionally) → confirm re-verifies session, challenge, PIN,
proposal hash/expiry, and the still-current ALLOW verdict, then
executes. Login lockout is global (`login:owner`, 5 failures → 15-min
429); cookie mutations require the CSRF token.

## 7. Database and migration instructions

SQLite (WAL, FK on, 5 s busy timeout, one connection per unit of
work, parameterized SQL). Migrations are versioned
`app/storage/migrations/*.sql`, tracked in `schema_migrations`, each
applied atomically:

```powershell
$env:AIRLOCK_DB_PATH='./data/airlock.db'; $env:AIRLOCK_BLOB_DIR='./data/blobs'
.\.venv\Scripts\python.exe -m app.cli db upgrade   # {applied, current_version}
.\.venv\Scripts\python.exe scripts\seed_demo.py     # synthetic registry (idempotent)
.\.venv\Scripts\python.exe -m app.cli health        # ok/degraded + versions
```

Current schema version: 3 (001 init, 002 proposal policy_version,
003 challenge-hash rebuild; 003 invalidates pending ≤5-min
challenges, fail-closed). Re-running upgrade is safe (idempotent).
Never run `--force` seed or destructive SQL against a database you
need; acceptance uses an isolated copy (§12).

## 8. Artifact-storage security

Content sniffing by magic bytes (extension/MIME never trusted);
per-file size cap, PDF page cap, PNG/JPEG pixel caps, WAV/MP4 duration
caps (header-level; unparseable headers accepted fail-open with the
size cap as bound); encrypted PDFs rejected; empty/truncated/unknown
content rejected; server-generated content-addressed keys only
(`<sha-prefix>/<artifact-id><ext>`); atomic temp-file + rename writes
with fsync; SHA-256 recorded per artifact; path-escape and symlink
defenses; orphan sweeps (`storage sweep`). No malware scanning and no
PDF active-content sandbox (see §16).

## 9. Mock payment limitations

MOCK ONLY by construction: `mock_payments` rows, `MOCK_COMPLETED`
status, every view labelled `MOCK PAYMENT — NO MONEY TRANSFERRED`.
No banking/UPI/gateway code, credentials, or network calls exist.
Idempotency is server-derived (`idempotency_key = proposal_hash`,
UNIQUE + transactional double-check): retries and concurrent
confirmations yield exactly one payment. No PCI/fraud/treasury
controls exist.

## 10. Audit-chain verification procedure

Append-only `audit_events` (SQL triggers + `GENESIS`-rooted SHA-256
chain over canonical JSON; business writes and their events share one
transaction). Verify:

```powershell
.\.venv\Scripts\python.exe scripts\verify_audit_chain.py
# Audit chain: OK (N events), exit 0; or BROKEN + break point, exit 1
```

or `POST /api/v1/audit/verify` (owner). Tamper-evident, NOT
tamper-proof against a privileged database rewriter (see `AUDIT.md`).
No PINs, tokens, keys, or raw bank references are recorded (tested).

## 11. Local development instructions

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env   # then run setup (never commit .env)
.\.venv\Scripts\python.exe scripts\setup_airlock.py
$env:AIRLOCK_FIXTURE_READER='1'   # dev/test/demo only, per-command
.\.venv\Scripts\python.exe -m app.cli db upgrade
.\.venv\Scripts\python.exe scripts\seed_demo.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The app never auto-loads `.env`; every `AIRLOCK_*` value must be
present in the process environment. Phase 1 stays untouched:
`results/phase1/phase1_report.json` remains `PARTIAL`.

## 12. Synthetic acceptance workflow (executed 2026-11-01)

Live `uvicorn app.main:app` on 127.0.0.1:8001 against an isolated
temp DB (migrations 1–3, 4 synthetic vendors, 3 POs), real HTTP via
httpx, ephemeral credentials destroyed after the run. 26/26 PASS:

- A (3): health `ok`, schema 3, policy 2.0.0; 22 OpenAPI paths incl.
  all required routes.
- auth (1+1): owner login, fresh session after restart.
- B (7): clean.pdf → ALLOW_PROPOSAL → challenge → confirm → exactly
  one `MOCK_COMPLETED` payment (1240.00); payment persisted; audit
  chain valid (14 events).
- C (3): arithmetic-mismatch.pdf → DENY/R3, no proposal, challenge
  impossible (404), audit valid (24 events).
- D (3): over-cap.pdf → ESCALATE, no proposal, owner reject →
  REJECTED, zero payments.
- E (4): re-uploaded clean.pdf → DENY/R4; consumed-challenge replay
  → 409; new challenge on CONFIRMED → 409; still one payment.
- F (5): after server restart — health ok, payment persisted,
  used challenge still dead (409), confirmed proposal unpayable
  (409), audit valid (45 events); `verify_audit_chain.py` OK
  (46 events).
- DB evidence: 4 cases / 4 verdicts / 1 CONFIRMED proposal /
  1 payment with `idempotency_key == proposal_hash`; challenge
  stored as 64-char hash, never the bearer.

## 13. Test execution commands

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider   # full suite
.\.venv\Scripts\python.exe scripts\phase2_check.py --strict # gate (21 checks)
.\.venv\Scripts\python.exe -m ruff check scripts tests app  # lint (pyflakes)
.\.venv\Scripts\python.exe scripts\check_secret_hygiene.py  # hygiene
.\.venv\Scripts\python.exe scripts\make_fixtures.py --check # fixture determinism
```

Coverage config exists (`coverage run -m pytest`); no mypy
configuration is present in this repo (type checking N/A).

## 14. Environment variable reference

No values are stored here; presence-only. Secrets: `AIRLOCK_PIN_HASH`
(Argon2id), `AIRLOCK_SESSION_SECRET` (reserved, see `AUTH.md`),
`AIRLOCK_BANK_HASH_KEY` (HMAC key). Storage: `AIRLOCK_DB_PATH`,
`AIRLOCK_BLOB_DIR`, `AIRLOCK_FIXTURES_DIR`. Modes/flags:
`AIRLOCK_ENV` (development|test|production), `AIRLOCK_FIXTURE_READER`
(1 only in dev/test/demo), `AIRLOCK_ENABLE_EVAL_API` (never
production), `AIRLOCK_ALLOW_INSECURE_COOKIES` (loopback dev only,
never production). Tuning: `AIRLOCK_MAX_UPLOAD_BYTES`,
`AIRLOCK_MAX_FILES_PER_CASE`, `AIRLOCK_MAX_PDF_PAGES`,
`AIRLOCK_MAX_IMAGE_PIXELS`, `AIRLOCK_MAX_AUDIO_SECONDS`,
`AIRLOCK_MAX_VIDEO_SECONDS`, `AIRLOCK_PROCESSING_TIMEOUT_S`,
`AIRLOCK_MAX_CONCURRENT`, `AIRLOCK_SESSION_MINUTES`,
`AIRLOCK_CHALLENGE_MINUTES`, `AIRLOCK_PROPOSAL_TTL_MINUTES`,
`AIRLOCK_LOGIN_MAX_ATTEMPTS`, `AIRLOCK_LOCKOUT_MINUTES`,
`AIRLOCK_RATE_PER_MINUTE`, `AIRLOCK_LOG_LEVEL`,
`AIRLOCK_AUDIT_RETENTION_DAYS`. Policy thresholds live in
`policy/rules.toml`, not in env.

## 15. Known limitations

`LIMITATIONS.md` is the full list: no live models (deterministic
doubles), mock payments only, single owner/PIN, local secrets without
KMS/rotation, single-writer SQLite, no malware scanning, no TLS/WAF/
backups/metrics, public loopback-only intake endpoints, no PO ledger,
global lockout, single currency precision, header-level media parsing.

## 16. Residual security risks

1. Privileged DB/file attacker can rewrite history and recompute
   hashes (tamper-evident only); no append-only store or signing.
2. Any network exposure of the intake/read endpoints leaks case and
   vendor data (auth required first).
3. PIN entropy is the owner's job; no MFA/recovery; global lockout is
   locally triggerable.
4. Secrets live in `.env` + OS permissions; bank-key rotation
   invalidates stored fingerprints (no dual-key period).
5. Uploaded bytes are never malware-scanned; PDF parsing is bounded
   but unsandboxed.
6. Single-process rate-limit races can undercount concurrent bursts
   (fail-open direction); per-session buckets only.
7. PO balances are not consumed, so exposure control across repeated
   invoices is administrative, not systemic.
8. No production review (threat model, red team on real documents,
   compliance, incident response) has been performed.

## 17. Phase 3 dependencies

Live reader/SAM/ASR integration behind the existing factories with
real threat modeling; PO reserve/release/consume ledger; per-currency
precision table; multi-user identity (OIDC/WebAuthn) with per-account
rate limits and trusted-proxy config; KMS-backed secrets with
rotation; Postgres/object-store/durable-queue migration paths (see
`MIGRATION.md`); malware scanning and parser sandboxing; TLS,
backups/PITR, metrics/alerting, retention enforcement; red-team
evaluation on non-synthetic documents.
