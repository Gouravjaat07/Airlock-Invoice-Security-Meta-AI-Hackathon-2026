# Airlock — Final Engineering Audit

Date: 2026-11-04. Auditor: principal-engineer mission session.
Method: five-track subagent reconnaissance (269 tool calls) plus firsthand
verification of all security-critical modules. Every finding below was
confirmed by reading the cited file. Unverified items are marked Missing
evidence, never assumed.

Baseline: `pytest` collects 941 tests. Result in this sandbox: 938 passed,
2 failed (environmental: `asyncio` socket creation denied, WinError 10013),
1 skipped (symlink creation not permitted). See §6.

Security invariants (mission §0.3): all hold in the inspected code. T0
owner-only authorization, untrusted-model-output (T2) handling, mock-only
payments, deterministic R1–R10, explicit fail-closed provider selection,
hash-chained audit. No change in this mission may weaken them.

## 1. Actual architecture

```
Browser (web/, React 19 + Router 7 + TanStack Query, Vite proxy /api)
  |  cookie session + X-CSRF-Token, or Bearer session token
  v
FastAPI (app/main.py create_app, /api/v1, error envelope, lifespan gate)
  +-- auth: Argon2id PIN, opaque sessions, global lockout, CSRF (app/auth)
  +-- cases: intake (64 MiB form / 10 MiB x5 files), idempotency, dedup (ingest.py)
  +-- pipeline (process.py, sync, BoundedSemaphore(2), idempotent reprocess)
  |     reader (registry-selected: fixture|spark|spark-open|glimmer)
  |     -> validate (InvoiceExtraction, extra=forbid, Decimal, currency v5)
  |     -> resolve_vendor (exact active; Levenshtein<=2 ambiguity -> R10)
  |     -> SAM lane + voice lane (independent, typed LaneOutcome)
  |     -> corroborate (field statuses + validators that actually ran)
  |     -> policy R1-R10 (deterministic precedence -> verdict)
  |     -> proposal (canonical hash) | NEEDS_REVIEW | REJECTED
  +-- approval: challenge + PIN re-verify + stale-verdict check (approval_service.py)
  +-- payments: MOCK ONLY (mock_payment_service.py)
  +-- audit: append-only SHA-256 hash chain (audit_service.py)
  v
SQLite (WAL, FK, 5 s busy timeout, versioned .sql, owner-run upgrades)
  + content-addressed blob store (artifacts.py, intake-hash rebinding)
```

Providers (app/providers): Spark Responses API (`muse-spark-1.3`),
Baseten chat (`meta-models/muse-spark-open-1026`), Glimmer chat
(`muse-glimmer`, loopback), Voice (`muse-voice-transcribe-1.0`), SAM SSE
(`sam-3.1`). Pooled httpx client, bounded timeouts, retry only
rate_limit/timeout/server with backoff, breaker 5-fail/60 s, usage +
request-id capture, secret redaction. No fallback chains anywhere.

## 2. Implementation status

Done and verified: intake, extraction + validation, currency v5, vendor/PO
resolution, arithmetic, duplicates, dates, caps, voice + SAM lanes,
corroboration, R1–R10, proposals, owner confirm, mock execution, audit
chain, sessions/CSRF/rate limits, blob integrity, migrations 001–003,
60 docs, 941-test suite, console UI with 9-state evidence display,
vitest + 3 Playwright e2e scripts, offline CI (Phase 1 only).

## 3. Confirmed strengths

- S1. Deterministic policy engine (`app/pipeline/policy.py`): all rules
  evaluated, explicit precedence (R9 > DENY rules > ESCALATE rules),
  structured reason codes. R7 never claims consistency for unevaluated
  bytes (`evidence-not-evaluated` is explicit).
- S2. Corroboration (`corroborate.py`) records only validators that ran;
  `sam` outcome always present so a voice conflict can never be skipped
  (traced `outcomes["sam"]` unconditional + policy line 182).
- S3. Currency v5 (`providers/currency.py`): unambiguous-only, `$`/`¥`
  rejected, no USD default, Decimal precision preserved.
- S4. Provider selection (`providers/registry.py` + `config.py`): one
  provider per task, fail-closed, READY honestly documented as
  static-config (not a live probe); production guards reject
  fixture/mock; keys never shared/logged; contributor models rejected.
- S5. Auth (`auth/sessions.py`, `api/auth.py`): Argon2id, hashed opaque
  tokens, HttpOnly SameSite=Lax cookies, CSRF on all cookie mutations
  (cases/evaluation/proposals/vendors), challenge-bound PIN confirm,
  stale-verdict rejection.
- S6. Audit (`services/audit_service.py`): canonical-JSON hash chain with
  replay verification detecting modification/deletion/reorder; admin
  rewrite limitation documented in the docstring.
- S7. Pipeline (`pipeline/process.py`): blob bytes rebound to intake
  hash, independent lanes, voice always transcribed when present with
  explicit EMPTY/FAILED/NOT_EVALUATED states, instruction-like voice
  markers treated as conflicts (inert), SAM prompted only from the
  trusted catalogue, duplicate-key race guarded at proposal time.
- S8. Frontend (`web/src/utils/evidence.ts`): 9 display states; `failed`,
  `not_evaluated`, `empty` never shown as green verified.
- S9. Prompt hygiene (`providers/prompts.py` v5): versioned constants,
  exact-copy rules, empty-string-on-uncertain, no alias fields.

## 4. Findings (classified)

### Critical defects — none found.

### High-severity defects — none found.

### Confirmed defects

- D1. CI is Phase-1-only (`.github/workflows/phase1.yml`, 50 lines):
  `ruff check scripts tests` never lints `app/`; no frontend
  typecheck/lint/test/build jobs; no eval gates; third-party actions
  unpinned (`actions/checkout@v4`, `setup-python@v5`,
  `upload-artifact@v4`). The repo's own gates do not cover the shipped app.
- D2. README is stale Phase-1 text ("application is *not* built yet")
  while `app/` + `web/` exist with 941 tests. An evaluator reading it
  first is misled about what to run.

### Confirmed risks

- R1. Git: branch `main` with zero commits, no remote, everything
  untracked — including scratch dirs (`tmp*/`, `probe_*/`, `pip-*/`,
  `pytest-of-Dell/`, `inspect_db_tmp.py`, `data/`, `results/`).
  `.env` is correctly ignored and unlisted (`git ls-files .env` empty).
  Risk: accidental commit of scratch/DB/blob data; no reviewable history.
- R2. No global security-headers middleware (`app/main.py`): no CSP,
  no global nosniff. Mitigations: JSON-only API, React auto-escape,
  artifact bytes served with `nosniff` (`api/cases.py:114`). Low.
- R3. Global login lockout (`login:owner`, 5/15 min) enables lockout-DoS
  by any remote caller. Deliberate, documented trade-off (code comment +
  `docs/phase2/AUTH.md`): IP/XFF keying is bypassable with no trusted
  proxy. Accept-or-tune decision needed; single-owner prototype.
- R4. `POST /audit/verify` appends `AUDIT_VERIFIED`, so verifying
  mutates the chain it verifies (`app/api/audit.py`). Documented
  pattern; keep the UI caveat or make verify read-only.

### Missing evidence

- M1. 2 baseline tests blocked by this sandbox (socket denial) and
  1 skipped (symlink denial) — must pass outside the sandbox:
  `tests/integration/test_startup_readiness.py::test_startup_refuses_unmigrated_db`,
  `::test_startup_accepts_migrated_db`, `tests/test_secret_hygiene.py`
  symlink test.
- M2. Frontend gates not yet run here: `npm test` (vitest),
  `npm run typecheck`, `npm run lint`, `npm run build`, Playwright e2e.
- M3. Live provider behavior unverified by design (zero billable calls
  in this mission): Spark/Voice/SAM adapters are contract-tested
  against mocks only. Live smokes remain an explicit owner opt-in.
- M4. Evaluation metrics beyond existing phase gates: manifest schema +
  preregistration exist (`eval/`, `prereg/`); per-model benchmark
  datasets and reports are Stage 4 work.

### Improvement opportunities

- I1. JPEG/MP4/WAV dimension/duration parsers fail open on corrupt dims
  (`app/storage/artifacts.py:224,288,323`, documented "Fail-open";
  PNG is strict). Size/duration caps still bound. Low.
- I2. Glimmer `READY` reason claims "local runtime endpoint configured"
  without checking (`providers/registry.py:100-102`). Reword or probe.
- I3. Currency accepts any 3-letter code as already-canonical
  (`currency.py:150`); no ISO-4217 allowlist. Downstream PO-currency
  check catches mismatches. Low.
- I4. Scratch files in repo root (`tmp*/`, `probe_*/`, `pip-*/`,
  `pytest-of-Dell/`, `inspect_db_tmp.py`, `.coverage`) predate this
  mission; leave untouched per operating rules, decide at commit time.
- I5. `web/dist/` and `web/node_modules/` exist locally (build output +
  installs; `dist/` is gitignored). Confirm excluded at commit.

### Not applicable

- N1. Vector/embedding threats: no embeddings in the codebase.
- N2. Enterprise multi-tenancy: single-owner SQLite prototype by design;
  PostgreSQL migration is roadmap, not a defect.

## 5. Unsupported claims — none found in code

Docstrings and UI labels checked during recon are honest: READY is
defined as static-config, mock-only payments are labeled, SAM output is
geometry-only ("never a quantity verdict"), empty/failed lanes are
labeled. The stale README (D2) is the one misleading surface.

## 6. Baseline test record

Command: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
--basetemp=pytest-of-Dell` (name matters: the hygiene scanner skips
`pytest-of-*`; any other in-repo basetemp self-incriminates).
Collected 941. Passed 938. Failed 2 (M1, sandbox socket denial).
Skipped 1 (M1, symlink denial). Deselected 0. Duration ~2 min.
Python 3.13.5, Node 22.18.0, Windows.

## 7. What this mission changes

Stages 1–9: fix D1/D2; re-verify R1–R10 + currency + lanes with focused
runs; build the reproducible per-model evaluation harness and benchmark
report; write threat model + red-team matrix + SECURITY.md; harden
headers/CSP (R2) only if tests stay green; add offline `ci.yml` gates +
`scripts/verify_repo.ps1`; rewrite README + AGENTS.md + evaluator/dem
...[truncated 265 chars]