# Phase 3 — Architecture discovery (2026-11-01)

Forensic map of the existing repository before Phase 3 implementation.
Baseline re-verified this date: full suite **436 passed / 1 skipped**,
`phase2_check.py --strict` READY 21/21 (prior session), Ruff clean.
Git: no commits yet (everything untracked; no diff available).
Phase 1 report `results/phase1/phase1_report.json` is PARTIAL and stays so.

## 1. Current architecture

FastAPI modular monolith (`app/`), SQLite + local blobs, synchronous
service-layer pipeline, socket-free ASGI test harness (app code must
stay free of loop-bound `asyncio` primitives — coroutines are driven
with a bare `send(None)`).

| Layer | Location | Notes |
|---|---|---|
| API | `app/api/` (router, auth, cases, vendors, proposals, payments, audit, evaluation) | Uniform `{"error": ...}` envelope, no tracebacks |
| Services | `app/services/` (case, approval, mock_payment, proposal, vendor, audit) | Transactions live here; audit written in same txn |
| Pipeline | `app/pipeline/` (ingest, reader, validate, registry, corroborate, policy, propose, process, state_machine) | Deterministic; R1–R10 in `policy.py` |
| Adapters (doubles) | `app/adapters/` (readers, transcription, vision, explanations, payments) | Fixture/Mock only; no network code |
| Auth/storage/domain | `app/auth/`, `app/storage/` (repos, migrations 001–003), `app/domain/` (taint T0–T3, enums, canonical hashes) | Unchanged by Phase 3 except additive audit events |
| Config | `app/config.py` (`Settings`, `load_settings`, `apply_policy`) | **Loads `AIRLOCK_*` + `policy/rules.toml` only — no provider vars (see §4)** |
| Schemas | `app/schemas/` (invoice, vendor, proposal, requests, responses, common) | `InvoiceExtraction` is the validated extraction contract |
| Evaluation | `app/evaluation/` (fixtures, policy_eval) | Manifest v2, canonical `attack_type`, no `attack_id` |
| Scripts | `scripts/` (stdlib-only by convention) | phase1/phase2 gates, smoke preflights, hygiene, fixtures |

## 2. Existing adapter contracts (verbatim interfaces)

- `Reader` protocol (`app/adapters/readers.py`): `read(artifact_bytes) -> ReaderResult{ payload, artifact_sha256, scenario }`; `adapter_id/adapter_version` attrs. Only impl: `FixtureReader` (SHA-gated to `fixtures/scenarios`, requires `fixture_reader_enabled`).
- `MockAsr.transcribe(voice_bytes) -> Transcript{ text, artifact_sha256 }` (scenario lookup).
- `MockSam.count(delivery_bytes, catalogue_item_id, catalogue_label) -> SamEvidence{ count, catalogue_item_id, catalogue_label, artifact_sha256 }` (scenario lookup).
- `Explainer` protocol: `explain(verdict, rules) -> str`; only impl `TemplateExplainer` (receives verdict+rules only, never raw docs).
- `PaymentExecutor` protocol is mock-only by design (`MOCK_LABEL`).

No adapter performs network I/O. No raw HTTP calls exist under `app/`.
`TODO/FIXME/NotImplementedError` search: only `smoke_sam.py:108`
("placeholder for the verified implementation", Phase 1 live path
deliberately refused) and manifest template-placeholder handling.

## 3. Pipeline insertion points

- Reader: `app/pipeline/reader.py::get_reader(settings) -> Reader`
  (currently always `FixtureReader`). Process path:
  `process._read_and_validate` → `reader.read(data)` → AppError or
  payload → `validate.validate_extraction` → `InvoiceExtraction`.
- Voice: `process._gather_voice` → `MockAsr(settings).transcribe` →
  `detect_voice_conflict(transcript, extraction)` → R7 voice outcome
  (optional, never fatal).
- Vision: `process._gather_sam` → `MockSam(settings).count` →
  R7 SAM count-vs-invoiced tolerance comparison. Catalogue label comes
  from the trusted registry, never invoice text.
- Required-verifier funnel: `corroborate.verifier_errors` + SAM errors
  → R9 DENY. Any provider failure surfaces as `AppError` with an
  `E_*` code and lands in ERROR state or R9 — fail-closed already.
- Provenance: `Producer{adapter, adapter_version, model_id,
  prompt_version, extracted_at}` + `Source{artifact_id, ...}` per fact;
  taint stays T2 for model output. Provider request IDs have no field
  yet (additive `request_id` optional — backward compatible).
- Audit vocabulary (`app/services/audit_service.py`) is additive-only;
  new `model.*` events are allowed additions.

## 4. Configuration map

`app/config.py` today: `AIRLOCK_PIN_HASH/SESSION_SECRET/BANK_HASH_KEY`,
`AIRLOCK_DB_PATH/BLOB_DIR`, `AIRLOCK_ENV`, `AIRLOCK_FIXTURE_READER`,
`AIRLOCK_FIXTURES_DIR`, `AIRLOCK_ENABLE_EVAL_API`,
`AIRLOCK_ALLOW_INSECURE_COOKIES`, upload/processing/auth/policy defaults.
Provider variables (`MODEL_API_KEY`, `META_API_BASE`, `SPARK_MODEL`,
`BASETEN_*`, `GLIMMER_BASE_URL`) exist ONLY in Phase 1
`scripts/validate_config.py` + `.env.example` — the application cannot
see them yet. **Phase 3 must add typed provider settings to `Settings`;
meanings/defaults are pinned by `.env.example`** (`META_API_BASE=
https://api.meta.ai/v1`, `SPARK_MODEL=muse-spark-1.3`,
`BASETEN_BASE_URL=https://inference.baseten.co/v1`,
`BASETEN_SPARK_OPEN_MODEL=meta-models/muse-spark-open`,
`GLIMMER_BASE_URL=http://127.0.0.1:8081/v1`).

## 5. Provider capabilities (current state)

All inference is deterministic doubles; nothing is live-verified.
`tests/adversarial/test_network_isolation.py` guards offline behavior.
Phase 1 smoke scripts (`smoke_meta/baseten/sam/voice`) are preflight
scaffolds: `smoke_meta` still shows a chat-completions shape with
`temperature: 0` (stale vs current docs — Responses API recommended,
Spark tuned at defaults); `smoke_sam` refuses live until schema
verification. Phase 3 supersedes these for live verification without
rewriting Phase 1 files.

## 6. Test commands (current)

`python -m pytest -p no:cacheprovider` (full),
`python scripts/phase2_check.py --strict` (gate),
`python -m ruff check scripts tests app`, `check_secret_hygiene.py`,
`make_fixtures.py --check`, `verify_audit_chain.py`.
`httpx` is a **dev-only** dependency; `scripts/` must stay stdlib-only.

## 7. Integration limitations (pre-existing)

Harness forbids loop-bound awaits → provider I/O must be synchronous
(sync httpx + existing semaphore pattern, no new async framework).
No PDF text/OCR layer, no audio conversion tooling, no video frame
handling. `max_*` media caps are header-level. Single-process SQLite.

## 8. Proposed Phase 3 boundaries

New `app/providers/` package (task contracts, registry/router,
per-provider adapters, shared sync HTTP core, resilience, versioned
prompts, SAM grammar parser) reusing `Reader`/`Transcript`/
`SamEvidence` shapes and `Producer` provenance. Router selects ONE
explicit provider per task from config (fixture/mock only in
dev/test; production never silently mocked). No policy-engine,
approval, payment, registry, or audit-chain changes beyond additive
events. No new migrations planned (synchronous inference, no job
table). New dependency: promote `httpx` to runtime (already vendored
in `.wheels/`, installed in `.venv`; pooling + timeouts + sync client;
no new HTTP stack). No other new dependencies (offline environment).

## 9. Compatibility constraints

Keep `Reader`/`transcribe`/`count` signatures; keep `E_*` taxonomy
(additive codes only); keep `Settings` override hook for tests;
keep scripts stdlib-only; never auto-load `.env`; never print secrets;
preserve Phase 1 PARTIAL and Phase 2 behavior (full regression gates).
