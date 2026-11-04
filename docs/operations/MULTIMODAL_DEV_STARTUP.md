# Multimodal dev startup (live Spark + Voice + SAM)

Reproducible startup for the live three-provider frontend workflow.
Synthetic assets only; the payment executor stays mock-only.

## 0. One-time: isolated test environment

Never use `./data/airlock.db` for live multimodal tests.

```powershell
cd <checkout>
# Pick isolated paths, e.g. ./data-test/airlock-multimodal.db
Copy-Item .env.example .env   # if no .env yet; never commit .env
```

Edit `.env` (values stay in the file; never paste keys into chat):

| Variable | Value |
|---|---|
| `AIRLOCK_DB_PATH` | `./data-test/airlock-multimodal.db` |
| `AIRLOCK_BLOB_DIR` | `./data-test/blobs` |
| `AIRLOCK_ENV` | `development` |
| `MODEL_API_KEY` | Meta Model API key (Standard mode) |
| `BASETEN_API_KEY` | Baseten key, **different** from Meta |
| `SPARK_MODEL` | `muse-spark-1.3` |
| `VOICE_MODEL` | `muse-voice-transcribe-1.0` |
| `SAM_MODEL` | `sam-3.1` |
| `BASETEN_SPARK_OPEN_MODEL` | `meta-models/muse-spark-open-1026` |

Generate the app secrets (PIN hash, session secret, bank key) once:

```powershell
.\.venv\Scripts\python.exe scripts\setup_airlock.py   # follow its output
```

Then initialize and seed the isolated database:

```powershell
$env:AIRLOCK_DB_PATH='./data-test/airlock-multimodal.db'
$env:AIRLOCK_BLOB_DIR='./data-test/blobs'
.\.venv\Scripts\python.exe -m app.cli db upgrade
.\.venv\Scripts\python.exe scripts\seed_demo.py
```

## 1. Validate, then start the backend

```powershell
.\scripts\run_airlock_multimodal_dev.ps1 -CheckOnly   # validate only
.\scripts\run_airlock_multimodal_dev.ps1              # start (foreground)
```

The launcher loads an allowlist of variables from `.env` into its own
process only, prints secrets presence-only, forces
`reader=spark voice=meta vision=sam` (+ fixture flag for dev/test
support), refuses the production DB and `AIRLOCK_ENV=production`,
requires the exact model IDs above, and starts uvicorn with visible
logs. Restart the backend after any provider/env change (the client
pool pins endpoint config per process).

## 2. Verify provider status

Log in, then open **Providers** (or `GET /api/v1/providers`):

| Task | Provider | Model |
|---|---|---|
| Invoice extraction | meta | muse-spark-1.3 |
| Voice transcription | meta | muse-voice-transcribe-1.0 |
| Visual segmentation | meta | sam-3.1 |

READY = configured and selectable, not live-tested. Press Refresh
after any backend restart.

## 3. Start the frontend

```powershell
cd web
npm run dev -- --host 127.0.0.1
```

## 4. Fresh three-artifact test

1. Cases → New: upload invoice PDF + delivery photo + voice WAV.
2. Process case; wait for "Processing finished".
3. Overview: extracted fields carry `meta-spark` provenance.
4. Evidence: each artifact shows its own status badge
   (Validated/Processed/Conflict/Not evaluated/Failed — never a
   single collapsed PASS) plus adapter, model, request, error code.
5. Policy: R1–R10 with reasons; conflicts → ESCALATE (manual review),
   invalid extraction → DENY with no proposal.
6. Audit tab (or `scripts\verify_audit_chain.py`): chain verifies.

## 5. Failure reference

| Symptom | Meaning | Action |
|---|---|---|
| Launcher refuses prod DB | `.env` points at `data/airlock.db` | Point at isolated DB (§0) |
| `missing_credential` | Key unset | Fix `.env`, restart backend |
| `breaker_open` | 5 recent provider failures | See `PROVIDER_FAILURE_RUNBOOK.md` |
| `extraction.rejected` | Model output failed schema | Inspect `errors[]`; never auto-retry into validity |
| Lane `not_evaluated` | Uploaded but comparison skipped | See R7 message; upstream failure |
| Lane `failed` + code | Provider error | `error_code` category; no fallback |
| SAM count 0 | Empty stream completed | Compared (usually R7 conflict), never proof of match |

Live smoke (tiny, billed) stays available via
`scripts\phase5_live_smoke.py --live --allow-billable`.
