# Phase 5 — Implementation plan (Airlock)

Date: 2026-11-03. Baseline: Phase 2 gate READY 21/21 (prior session),
Phase 3 offline contracts implemented, full suite 436 passed / 1 skipped
(prior session, re-verify). Git state could not be inspected from this
session (shell unavailable); the operator must confirm `git status`
before review.

## 1. Existing implementation (do not rebuild)

- `app/providers/spark.py` — live Muse Spark 1.3 extraction over
  Responses API (`POST {META_API_BASE}/responses`, json_schema,
  `store:false`, inline PDF/image). Stub-transport tested.
- `app/providers/voice.py` — live batch transcription
  (`POST {META_API_BASE}/asr/transcribe?sessionId=`, multipart,
  `PUSH_TO_TALK`, WAV mono 16-bit PCM @16/24 kHz). No realtime WS
  (no realtime product requirement).
- `app/providers/sam.py` + `sam_parse.py` + `sam_mask.py` — live SAM 3.1
  over Responses SSE, official lane grammar + base85 codec port.
- `app/providers/baseten.py` + `chat.py` — Baseten Muse Spark Open over
  OpenAI-compatible chat completions (images only, PDFs refused).
- `app/providers/glimmer.py` — optional local chat-completions reader
  + `/models` preflight. No auto-download, no mandatory dependency.
- Cross-cutting: `http.py` (pooled sync httpx, TLS, 8 MB cap),
  `resilience.py` (backoff+jitter, breaker, per-provider semaphore),
  `types.py` (error taxonomy), `registry.py` (one provider per task,
  no fallback, static READY = configured, not a live probe),
  `extraction.py`/`numbers.py`/`prompts.py` (shared finalize path).
- Pipeline seam: `app/pipeline/reader.py::get_reader`,
  `resolve_voice`/`resolve_vision`; R1–R10 in `app/pipeline/policy.py`
  unchanged and authoritative; executor mock-only.
- `scripts/smoke_phase3.py` — bounded opt-in live smoke (preflight
  default, `--live --allow-billable`, `--max-calls`, synthetic inputs).
- Frontend: `web/src/pages/ProvidersPage.tsx` (config-only status,
  honest copy), `web/src/api/*` typed client, Playwright smoke.
- Docs: `docs/phase3/CAPABILITY_MATRIX.md` (contracts verified
  2026-11-01), `PROVIDERS.md`, `LIMITATIONS.md`, `docs/phase2/*`.

## 2. Missing for Phase 5

1. Re-verified API contracts against current official docs
   (`docs/integrations/META_API_CONTRACTS.md`).
2. `scripts/phase5_check.py` (offline gate), `scripts/phase5_eval.py`
   (accuracy + false-ALLOW), `scripts/phase5_benchmark.py` (offline
   latency/reliability), `scripts/phase5_live_smoke.py` (per-provider
   live smoke; thin wrapper/extender of `smoke_phase3.py` semantics).
3. Stale copy fix: `app/adapters/readers.py` says live readers are
   "intentionally absent in Phase 2" — true for Phase 2, misleading
   now; clarify without changing behavior.
4. Frontend: `ProvidersPage` has no test; `availability` is an
   untyped string; no provider fixtures; no failure-state coverage.
5. Docs: provider architecture, trust boundaries, per-provider setup,
   operations runbooks, benchmark methodology, results, acceptance,
   reviewer guide.
6. Live evidence: no credential in this session, no network execution
   from tests; live runs are operator-executed via the smoke script.
7. Benchmark outputs: `results/phase5/*` must be produced by running
   the scripts, never hand-written.

## 3. Provider adapter status

| Adapter | Live code | Offline tests | Live proof |
|---|---|---|---|
| Spark 1.3 | yes | yes (stub) | NOT TESTED (needs key) |
| Voice batch | yes | yes (stub) | NOT TESTED (needs key) |
| Voice realtime | no (no product need) | n/a | documented non-goal |
| SAM 3.1 | yes | yes (stub) | NOT TESTED (needs key) |
| Baseten Spark Open | yes | yes (stub) | BLOCKED (key untrusted) |
| Glimmer local | yes | yes (stub) | NOT AVAILABLE (no runtime) |

## 4. Configuration status

`app/config.py` already carries all provider settings with validated
ranges, https-only Meta/Baseten, loopback-only Glimmer http,
contributor-model refusal, and production fail-closed rules.
`.env.example` matches. No new secret vars needed. Phase 5 adds only
operational live-test flags if justified (`AIRLOCK_LIVE_PROVIDER_TESTS`,
`AIRLOCK_LIVE_TEST_MAX_CALLS`); otherwise reuse
`--live --allow-billable --max-calls` script convention.

## 5. Test gaps

- No Phase 5 gate script test; no live-flag misuse test for new
  scripts; no benchmark determinism test.
- No frontend Providers page test or availability-union parity test.
- No credential-leak test covering new scripts/outputs (extend
  `check_secret_hygiene.py` patterns).
- Live tests must skip explicitly without opt-in + key, and never run
  from default pytest.

## 6. Risks

1. Shell unavailable in this session: no test/benchmark execution
   possible here; all gates must be re-run by the operator.
2. No credentials: live integrations cannot be verified in-session;
   report BLOCKED/NOT TESTED honestly, never PASS.
3. Contract drift since 2026-11-01: re-check the Responses, Voice,
   SAM, and error-handling pages; follow docs on any difference.
4. Paid-call accidents: keep preflight defaults, max-calls caps, and
   synthetic-only inputs in every live path.
5. Scope creep: do not add fallback chains, realtime WS, brokers, or
   a second database; preserve the modular monolith.

## 7. Implementation sequence

1. Plan (this file) + contract re-verification doc.
2. Stale-copy fix + any config addition (with tests).
3. `phase5_check.py`, `phase5_eval.py`, `phase5_benchmark.py`,
   `phase5_live_smoke.py` (stdlib-only, `--help`, exit codes).
4. Backend Phase 5 tests (offline, deterministic).
5. Frontend: availability union + fixtures + ProvidersPage test.
6. Architecture/integration/operations docs.
7. Methodology + acceptance report (honest status).
8. Reviewer guide + final hygiene review.

## 8. Files to change

- Edit: `app/adapters/readers.py` (copy only).
- Add: `scripts/phase5_*.py`, `tests/phase5/*.py` (or extend
  `tests/providers/`), `web/src/pages/ProvidersPage.test.tsx`,
  `web/src/api/types.ts` (union), `web/src/test/fixtures.ts`.
- Add docs under `docs/phase5/`, `docs/architecture/`,
  `docs/integrations/`, `docs/operations/`, `docs/REVIEWER_GUIDE.md`.
- Do not touch: policy engine, approval, payments, migrations,
  fixtures, Phase 1–3 gates.

## 9. Dependencies

None expected. `httpx` already covers provider HTTP; scripts stay
stdlib-only; no new frontend packages.

## 10. Compatibility

- `Reader.read` / `transcribe` / `count` signatures unchanged.
- `Availability` values unchanged (`ready|missing_credential|
  misconfigured|disabled|breaker_open|not_applicable`).
- `GET /api/v1/providers` shape unchanged; no network I/O.
- Phase 1 PARTIAL, Phase 2/3 gates keep passing unmodified.
