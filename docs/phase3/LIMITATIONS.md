# Phase 3 — Limitations and status ledger

Honest classification per area (see `CAPABILITY_MATRIX.md` for the
per-model table; verification date 2026-11-01 throughout).

## Implemented + offline-tested (PASS)

- Provider layer: Meta Responses client, Spark/voice/SAM adapters,
  Baseten + Glimmer chat adapters, registry/router, resilience,
  prompts, numbers, WAV gate, SAM grammar parser + mask decoder
  (official codec port, 3.1 verification pass).
- Pipeline wiring: reader/voice/vision selection, provenance
  (model/request ids), audit enrichment, `/providers` endpoint.
- Contract, grammar, injection, pipeline, recovery, and API suites.
- `phase3_check.py` gate, `phase3_eval.py` offline eval,
  `smoke_phase3.py` bounded live smoke (preflight path).

## Live API verified

None. No live request was made during implementation.

## Preflight only / not tested (NOT TESTED)

- Meta Spark / Voice / SAM round-trips: code + contracts done,
  `MODEL_API_KEY` unset here.
- Baseten Spark Open: BLOCKED by policy — the historic
  `BASETEN_API_KEY` in `.env` is assumed revoked per spec §18.2 and
  was never used; live needs a fresh out-of-band key.
- Glimmer: NOT AVAILABLE — no local runtime in this environment
  (adapter + preflight implemented; multimodal behavior
  runtime-dependent and unverified).

## Not implemented (by decision, NOT APPLICABLE / deferred)

- Muse Image: deliberately outside the verification path (§13.1 —
  generative output must never be evidence). No product requirement.
- Muse Wonder: no justified use case (§13.2).
- Realtime voice WebSocket: no realtime requirement.
- Files API uploads: inline-only design (better privacy).
- Audio conversion: strict WAV required, never converted.
- Thread-hop path: `offload_sync` runs inline under the loop-free
  test harness; the worker-thread branch only engages on a real
  server (uvicorn) and needs operational verification.
- Automatic provider fallback: none (explicit selection only).
- Cost estimates: never (no verified pricing source at runtime).
- New migrations: none needed (synchronous inference, no job table).

## Carried Phase 2 limitations (unchanged)

Mock-only payments, single owner/PIN, local secrets, single-writer
SQLite, no malware scan, loopback-only public intake, no PO ledger,
global lockout single precision, header-level media parsing —
see `docs/phase2/LIMITATIONS.md`. Production deployment is NOT READY.
