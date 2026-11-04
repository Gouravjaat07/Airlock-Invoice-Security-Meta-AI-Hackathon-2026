# Muse Spark 1.3 setup (invoice extraction)

Live document reader over the Meta Responses API. Standard mode only
(`muse-spark-1.3`); `-contributor` model IDs are refused by config
validation. Contract source: `docs/integrations/META_API_CONTRACTS.md`.

## Configure

```powershell
$env:MODEL_API_KEY = "<meta-model-api-key>"
$env:AIRLOCK_READER_PROVIDER = "spark"
# Optional overrides (defaults shown):
$env:META_API_BASE = "https://api.meta.ai/v1"
$env:SPARK_MODEL = "muse-spark-1.3"
$env:AIRLOCK_EXTRACTION_TIMEOUT_S = "180"
$env:AIRLOCK_SPARK_MAX_OUTPUT_TOKENS = "4096"
```

`.env` is never auto-loaded; export into the process environment.

## Select + verify (no network)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider meta-spark
```

Preflight reports configuration only. `ready` means "configured and
selectable", never "a live call succeeded".

## Live smoke (one synthetic micro-request)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider meta-spark --live --allow-billable
```

Sends `Reply with exactly: AIRLOCK_SMOKE_OK` (no invoice data).
Record: `results/phase5/smoke-*.json` (sanitized, no key).

## Live extraction scoring (synthetic fixtures)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_eval.py --live --allow-billable --reader-provider spark --max-calls 3
```

## Behavior notes

- Input: PDF (`input_file`) or PNG/JPEG (`input_image`), inline
  base64, `store:false`; app upload caps unchanged (10 MB).
- Output: `text.format` json_schema, shared finalizer
  (`extraction.py`), local `validate_extraction`, Decimal
  reconciliation. Model arithmetic is never trusted.
- Refusal/malformed content → `E_SCHEMA` (R8 DENY). Transport
  failure → `E_API_UNAVAILABLE` (case ERROR, retryable by the
  operator). Selection failure → `E_READER_UNAVAILABLE`.
- Never routes audio (Spark 1.3 audio is degraded per the docs);
  voice evidence uses Muse Voice Transcribe.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| `missing_credential` | key unset | set `MODEL_API_KEY` |
| 401 | bad/revoked key | rotate in dashboard, re-export |
| 402 | billing issue | operator: dashboard billing |
| 429 | per-team limit | backoff honors `Retry-After`; lower concurrency |
| `breaker_open` | 5 consecutive provider-side failures | wait 60 s cooldown, inspect cause |
| R8 DENY on valid invoices | refusal/schema drift | check prompt/schema versions, re-run eval |
