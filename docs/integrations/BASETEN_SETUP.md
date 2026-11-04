# Baseten Muse Spark Open setup (alternate extraction)

Alternate invoice reader over Baseten's OpenAI-compatible
`POST /chat/completions`. Distinct provider with its own key, base
URL, breaker, and provenance — never a silent fallback for Meta.

## Configure

```powershell
$env:BASETEN_API_KEY = "<baseten-key>"
$env:AIRLOCK_READER_PROVIDER = "spark-open"
# Optional overrides (defaults shown):
$env:BASETEN_BASE_URL = "https://inference.baseten.co/v1"
$env:BASETEN_SPARK_OPEN_MODEL = "meta-models/muse-spark-open-1026"
```

Model pinned 2026-11-03 per direct Baseten instruction; it is also
the code default, so the override above is only needed to be
explicit.

`BASETEN_API_KEY` must differ from `MODEL_API_KEY` (enforced).
Baseten requests must never route to `https://api.meta.ai/v1`
(separate client, separate base URL, pinned per pool key).

## Select + verify (no network)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider baseten
```

## Live smoke (synthetic chat round-trip)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider baseten --live --allow-billable
```

## Live extraction scoring (synthetic fixtures, images only)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_eval.py --live --allow-billable --reader-provider spark-open --max-calls 3
```

## Behavior notes

- Reuses the shared chat core (`app/providers/chat.py`):
  system instructions, text + `image_url` data-URL parts,
  `response_format` json_schema, same finalizer/validation as
  Spark. Provider-specific serialization stays in the adapter.
- Images only: PDF input is explicitly refused. Route PDF
  invoices to Spark, or render pages to images before sending.
- Same trust posture as Spark: T2 output, local validation,
  R1–R10 authoritative, identical audit vocabulary.
- No automatic Meta→Baseten failover exists. Any future
  fallback must be explicit, configured, and auditable.

## Data protection

Baseten retention/privacy terms differ from Meta's. Enable only
when explicitly authorized for the data class being processed,
and record that authorization with the deployment.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| `missing_credential` | key unset | set `BASETEN_API_KEY` |
| `E_UPLOAD` on PDF | images-only adapter | use Spark for PDFs |
| `length` finish reason | output cap hit | `INCOMPLETE`, never retried blindly |
| `content_filter` | provider refusal | `REFUSAL` → `E_SCHEMA` (R8 DENY) |
| `breaker_open` | repeated Baseten failures | isolated from Meta; inspect Baseten status |
