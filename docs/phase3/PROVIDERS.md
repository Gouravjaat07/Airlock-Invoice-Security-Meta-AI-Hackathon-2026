# Phase 3 — Provider architecture

How model inference plugs into Airlock without touching the
deterministic core. Contract details: `CAPABILITY_MATRIX.md`
(verified 2026-11-01). Discovery: `ARCHITECTURE_DISCOVERY.md`.

## Layers (`app/providers/`)

- Task entry points: `spark.py` (SparkReader), `baseten.py`
  (BasetenSparkReader), `glimmer.py` (GlimmerReader + preflight),
  `voice.py` (MetaVoiceTranscriber), `sam.py` (MetaSamSegmenter).
  Each implements an existing narrow shape (`Reader.read`,
  `transcribe`, `count`) — no universal `generate()`.
- Protocol cores: `meta.py` (Responses API: request/response/SSE/error
  mapping), `chat.py` (OpenAI-compatible chat for Baseten/Glimmer,
  incl. the shared chat extraction call), `http.py` (one pooled sync
  httpx client per provider, TLS always on, bodies read through the
  cap while streaming, SSE caps, `Retry-After` parsing).
- `registry.py`: capability declarations + explicit router. One
  provider per task from config; failures raise, never reroute.
- `resilience.py`: bounded retries (transient categories only),
  backoff+jitter, `Retry-After` honor, consecutive-failure breaker
  (provider-side failures only), per-provider inflight semaphores.
  All sync/thread-safe (the ASGI harness forbids loop-bound awaits).
- `prompts.py`: versioned instructions + extraction JSON schema.
- `extraction.py`: shared finalizer (strict JSON → field allowlist →
  decimal normalization → evidence grounding → `ReaderResult`).
- `numbers.py`: locale-aware amount normalization; ambiguous →
  dropped (R8), never guessed. `audio.py`: strict WAV gate.
- `sam_parse.py`: pure SAM lane-grammar parser (boxes + mask
  headers/payloads validated). `sam_mask.py`: mask raster decoder
  (official codec port + decode budgets).
- `types.py`: `ProviderName`, `TaskKind`, `Usage`, `ProviderError`
  categories, `to_app_error` mapping.

## Request lifecycle (extraction example)

1. `process._read_and_validate` → `get_reader` → registry resolves
   ONE reader or raises `E_API_UNAVAILABLE` (explicit reason).
2. Adapter builds the documented request (inline base64 media,
   `store:false`, structured output, no tools, no temperature).
3. `call_guarded`: breaker check → semaphore → bounded retries.
4. Response parsed by protocol core; transport failures →
   `E_API_UNAVAILABLE`/`E_RATE_LIMIT` (case ERROR,
   operator-retryable). Reader *selection* failures (disabled,
   unconfigured, missing credential, breaker open) surface as
   `E_READER_UNAVAILABLE` instead, keeping "cannot build the
   reader" distinct from "built reader's call failed".
   Deterministic content refusals → `E_SCHEMA` (R8 DENY), never a
   retry loop. HTTP mapping keys on status, then the stable
   envelope `type`, then `code`; unknown statuses fail closed
   without retries; 504/gateway-timeout is never auto-retried (per
   provider guidance); 402 billing needs an operator, not a retry.
5. Content finalized: unknown fields stripped (warned), ambiguous
   amounts dropped, evidence anchors checked; unusable content →
   `E_SCHEMA` (R8 DENY). Values stay T2 regardless.
6. Existing `validate_extraction` → registry/arithmetic/duplicate →
   R1–R10 → proposal/approval/audit unchanged.

Voice is optional corroboration (failure recorded, never fatal); SAM
failures feed R9 (DENY) exactly like the mock path. No provider can
reach policy, registry, approval, payment, or audit internals.

## Selection and availability

`AIRLOCK_READER_PROVIDER` (fixture|spark|spark-open|glimmer),
`AIRLOCK_VOICE_PROVIDER` (mock|meta), `AIRLOCK_VISION_PROVIDER`
(mock|sam). Fixture/mock require `AIRLOCK_FIXTURE_READER=1` and are
rejected in production at config load. `GET /api/v1/providers`
(owner-only) reports per-task availability (`ready`,
`missing_credential`, `misconfigured`, `breaker_open`,
`not_applicable`) with reasons, never secrets. No fallback chains;
an explicit alternate would need its own config + audit trail
(not implemented — documented extension point).

## Timeouts and bounds

Shared connect timeout + per-task read profiles
(`extraction/voice/sam_timeout_s`), 8 MB response cap, 500k-char
output cap, SSE event/byte caps, `max_output_tokens` floor 16,
inflight cap (default 2), retries 0–5 (default 2, transient only).
POSTs are never assumed idempotent: connect/pool timeouts (nothing
accepted) may retry, but read/write timeouts (possibly accepted and
billed) surface as INCOMPLETE for operator reconciliation, never
auto-retried.

## Dependencies

`httpx` promoted to a runtime dependency (already vendored in
`.wheels/`, already installed; pooling + timeouts + sync client —
no new HTTP stack). No other new dependencies. `scripts/` stays
stdlib-only (smoke uses urllib).
