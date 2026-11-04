# Reviewer guide (Airlock)

Understand, install, run, and verify Airlock from a clean checkout.
Windows PowerShell throughout.

## 1. Architecture in 60 seconds

Modular monolith: FastAPI + SQLite + local blobs (`app/`), React
console (`web/`). Upload → reader (T2 extraction) → vendor resolve
→ SAM/voice evidence → corroboration → R1–R10 policy → verdict →
proposal (iff ALLOW) → owner approval (PIN + single-use challenge)
→ mock payment. Every step appends hash-chained audit events in the
same transaction. Details: `docs/phase2/ACCEPTANCE.md`,
`docs/architecture/PROVIDER_ARCHITECTURE.md`.

## 2. Backend

- Entrypoint: `app/main.py` (`create_app()`); routes `app/api/`,
  transactions `app/services/`, pipeline `app/pipeline/`,
  storage `app/storage/` (migrations 001–003), auth `app/auth/`.
- Config: `app/config.py` (`load_settings()` from process env +
  `policy/rules.toml`). `.env` is never auto-loaded.
- Policy: `app/pipeline/policy.py` (R1–R10; TOML carries
  thresholds only). Trust classes T0–T3: `TRUST_BOUNDARIES.md`.

## 3. Frontend

`web/` (React 19 + TS + Vite). Typed client `src/api/` (1:1 with
backend), pages `src/pages/` (dashboard, cases, proposals, audit,
providers, settings), Playwright smoke `e2e/smoke.mjs`. Dev proxy
`/api` → `127.0.0.1:8000`; no CORS.

## 4. Provider adapters

Live: `app/providers/spark.py`, `voice.py`, `sam.py`,
`baseten.py`, `glimmer.py` (+ `meta.py`/`chat.py`/`http.py`
cores, `registry.py` router, `resilience.py` guards).
Doubles: `app/adapters/` (fixture reader, mock ASR/SAM).
Selection: `AIRLOCK_READER/VOICE/VISION_PROVIDER`, one per task,
no fallback. Health: owner-only `GET /api/v1/providers`
(config-only, no network I/O).

## 5. Trust boundaries + policy

T0 owner auth → T1 registry/policy/config → T2 model output →
T3 raw bytes. Models supply evidence; R1–R10 decide; only the
owner approves; executor is mock-only. Full statement:
`docs/architecture/TRUST_BOUNDARIES.md`.

## 6. Fresh setup

```powershell
cd <checkout>
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe scripts\setup_airlock.py  # follow its output
cd web; npm install; cd ..
```

## 7. Offline verification (no keys, no network)

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
.\.venv\Scripts\python.exe -m ruff check scripts tests app
.\.venv\Scripts\python.exe scripts\phase2_check.py --strict
.\.venv\Scripts\python.exe scripts\phase3_check.py --strict
.\.venv\Scripts\python.exe scripts\phase5_check.py --strict
.\.venv\Scripts\python.exe scripts\phase5_eval.py
.\.venv\Scripts\python.exe scripts\phase5_benchmark.py --cases 5
cd web
npm run typecheck; npm run lint; npm test; npm run build
```

E2E (isolated env only — see `web/e2e/smoke.mjs` header):
`npm run e2e`; multimodal 3-file runs: `npm run e2e:multimodal`
(see `web/e2e/multimodal.mjs` header). Audit:
`POST /api/v1/audit/verify` or
`scripts\verify_audit_chain.py` (read-only on live DBs).

## 8. Live providers (explicit, billed, tiny)

```powershell
$env:MODEL_API_KEY = "<key>"; $env:BASETEN_API_KEY = "<key>"
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py              # preflight
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --live --allow-billable --max-calls 5
.\.venv\Scripts\python.exe scripts\phase5_eval.py --live --allow-billable --max-calls 3
```

Per-provider: `--provider meta-spark|meta-voice|meta-sam|baseten|
glimmer`. Setup per provider: `docs/integrations/*_SETUP.md`;
contracts: `META_API_CONTRACTS.md`. Missing credential = BLOCKED,
never PASS. Standard mode only (`-contributor` refused).
All-three-live backend startup:
`scripts\run_airlock_multimodal_dev.ps1` (see
`docs/operations/MULTIMODAL_DEV_STARTUP.md`).

## 9. Reading outputs

- Gates: `results/<phase>/phaseN_report.{json,md}` — verdict +
  per-check status; READY means all mandatory PASS.
- Eval: `results/phase5/eval/` — verdict match, false-ALLOW
  (must be 0), schema validity, opt-in live scores.
- Benchmark: `results/phase5/benchmark_*` — latency stats,
  verdicts, audit volume, opt-in live latency.
- Smoke: `results/phase5/smoke-*.json` — per-provider
  PASS/FAIL/NOT_TESTED, sanitized (no keys).

## 10. Known limitations

Phase 2/3 LIMITATIONS still apply (mock payments, single owner,
local secrets, SQLite, no PO ledger, loopback intake, no
malware scan/TLS/backups/metrics). Phase 5: no realtime Voice
WS, no Baseten/Glimmer PDF input, in-memory breaker, pool pins
endpoint config until restart, Glimmer quality unevaluated.
Live status at handoff: `docs/phase5/PHASE5_ACCEPTANCE_REPORT.md`
(PARTIAL — implementation delivered, execution outstanding).

## 11. Reproduce the final results

Run §7 then §8; compare `results/phase5/` against
`docs/phase5/PHASE5_RESULTS.md` (template until the first green
run fills it). Methodology:
`docs/phase5/PHASE5_BENCHMARK_METHODOLOGY.md`.
