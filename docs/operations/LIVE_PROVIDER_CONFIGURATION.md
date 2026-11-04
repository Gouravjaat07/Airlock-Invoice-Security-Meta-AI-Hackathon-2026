# Live provider configuration

How to move from fixture/mock (dev/test) to live inference. Every
step is explicit; nothing fails over silently.

## 1. Choose providers (one per task)

| Task | Env var | Live value | Dev/test value |
|---|---|---|---|
| Invoice extraction | `AIRLOCK_READER_PROVIDER` | `spark` / `spark-open` / `glimmer` | `fixture` |
| Transcription | `AIRLOCK_VOICE_PROVIDER` | `meta` | `mock` |
| Segmentation | `AIRLOCK_VISION_PROVIDER` | `sam` | `mock` |

Production refuses `fixture`/`mock` at config load
(`app/config.py::_validate_safety`).

## 2. Supply credentials (process env only)

- `MODEL_API_KEY` — Meta Model API (Spark, Voice, SAM).
- `BASETEN_API_KEY` — Baseten (must differ from `MODEL_API_KEY`).
- `GLIMMER_API_KEY` — only if the local runtime needs one.

Never put keys in files, frontend bundles, logs, audit events,
benchmark output, or screenshots. `.env.example` holds placeholders
only. Keys are presence-only in every report (`redacted_dict`).

## 3. Tune envelopes (optional)

`META_API_BASE`, `SPARK_MODEL`, `VOICE_MODEL`, `SAM_MODEL`,
`BASETEN_BASE_URL`, `BASETEN_SPARK_OPEN_MODEL`, `GLIMMER_BASE_URL`,
`GLIMMER_MODEL`, `AIRLOCK_PROVIDER_CONNECT_TIMEOUT_S` (1–120),
`AIRLOCK_EXTRACTION_TIMEOUT_S` / `AIRLOCK_VOICE_TIMEOUT_S` /
`AIRLOCK_SAM_TIMEOUT_S` (5–1800), `AIRLOCK_PROVIDER_MAX_INFLIGHT`
(1–16), `AIRLOCK_PROVIDER_MAX_RETRIES` (0–5),
`AIRLOCK_SPARK_MAX_OUTPUT_TOKENS` (≥16).

Constraints: Meta/Baseten https-only; Glimmer plain-http loopback
only; no `-contributor` model IDs; no embedded URL credentials.

## 4. Verify before serving traffic

```powershell
# Config-only (no network):
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py
# One synthetic micro-request per provider (billed, tiny):
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --live --allow-billable --max-calls 5
# Synthetic extraction scoring through the real adapter:
.\.venv\Scripts\python.exe scripts\phase5_eval.py --live --allow-billable --max-calls 3
```

Then `GET /api/v1/providers` (owner) should show `ready` with the
expected model IDs. `ready` = configured and selectable; live
reachability is learned from call outcomes (breaker), not polling.

For the all-three-live dev backend in one step, use
`scripts\run_airlock_multimodal_dev.ps1` (validates `.env`,
forces spark/meta/sam, refuses the production DB — see
`docs/operations/MULTIMODAL_DEV_STARTUP.md`).

## 5. Operate

- Standard mode only. Contributor mode (`-contributor` IDs) is
  refused by validation — never work around that.
- Invoice data goes only to the configured provider. There is no
  automatic Meta→Baseten (or any) failover.
- Restarts are required for base-URL/credential/timeout changes
  (the client pool pins endpoint config per process).
- Record the provider/model IDs, doc-check date
  (`META_API_CONTRACTS.md`), and smoke record with each deploy.
