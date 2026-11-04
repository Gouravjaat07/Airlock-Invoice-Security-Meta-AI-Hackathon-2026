# Provider architecture (Phase 5 current state)

How model inference plugs into Airlock. Phase 3 design docs
(`docs/phase3/PROVIDERS.md`, `CAPABILITY_MATRIX.md`,
`ARCHITECTURE_DISCOVERY.md`) remain the deep reference; this file
records the architecture as it stands after Phase 5, including the
Phase 5 additions.

## Module map

| Area | Location | Role |
|---|---|---|
| Task adapters | `app/providers/spark.py`, `baseten.py`, `glimmer.py`, `voice.py`, `sam.py` | One narrow shape each (`read` / `transcribe` / `count`) |
| Doubles | `app/adapters/readers.py`, `transcription.py`, `vision.py` | Fixture reader + mock ASR/SAM (dev/test only) |
| Protocol cores | `app/providers/meta.py`, `chat.py`, `http.py` | Responses API, chat completions, pooled sync HTTP |
| Router | `app/providers/registry.py` | One provider per task, no fallback, static READY |
| Resilience | `app/providers/resilience.py`, `types.py` | Retries, breaker, semaphores, error taxonomy |
| Contracts | `app/providers/prompts.py`, `extraction.py`, `numbers.py`, `audio.py`, `sam_parse.py`, `sam_mask.py` | Prompts, finalizer, WAV gate, SAM grammar + codec |
| Pipeline seam | `app/pipeline/reader.py`, `process.py` | `get_reader` / `resolve_voice` / `resolve_vision` |
| Health API | `app/api/providers.py` | Owner-only `GET /api/v1/providers`, config-only |
| Phase 5 tooling | `scripts/phase5_*.py`, `tests/phase5/` | Gate, eval, benchmark, live smoke, offline tests |

## Request lifecycle (extraction example)

1. `process._read_and_validate` → `get_reader` → registry builds
   exactly one reader or raises `E_READER_UNAVAILABLE`.
2. Adapter builds the documented request (inline media,
   `store:false`, structured output, no tools).
3. `call_guarded`: breaker check → semaphore → bounded retries
   (transient categories only, backoff+jitter, `Retry-After`).
4. Transport failure → `E_API_UNAVAILABLE`/`E_RATE_LIMIT` (case
   ERROR, operator-retryable); content refusal → `E_SCHEMA`
   (R8 DENY). 504/gateway-timeout is never auto-retried.
5. Shared finalizer: strict JSON → allowlist → decimal
   normalization → evidence grounding → `ReaderResult` (T2).
6. Existing validation → R1–R10 → proposal/approval/audit,
   unchanged. The policy engine never sees provider internals.

## What Phase 5 added

- `phase5_check.py` (14-check offline gate, incl. Phase 3
  regression), `phase5_eval.py` (verdict + schema + opt-in live
  reader scoring), `phase5_benchmark.py` (offline latency +
  opt-in live latency via the shared smoke runner),
  `phase5_live_smoke.py` (per-provider live smoke; mechanics
  shared with `smoke_phase3.py`, evidence under `results/phase5/`).
- `tests/phase5/` (smoke safety, eval scoring, benchmark math).
- Frontend: `ProviderAvailability`/`ProviderTask` unions,
  provider fixtures, `ProvidersPage` coverage.
- This doc set: contracts, setup guides, runbooks, reviewer guide.

## Non-goals (confirmed, not deferred silently)

- No fallback chains: failures raise with explicit reasons
  (`E_READER_UNAVAILABLE` vs `E_API_UNAVAILABLE`).
- No realtime Voice WebSocket (no live-microphone workflow).
- No PDF input on Baseten/Glimmer (Spark handles PDFs).
- No generative-image evidence (`muse-image-1.0` excluded).
- No message broker, second database, or distributed runtime.
- Payments stay mock-only; the explainer stays templated.
