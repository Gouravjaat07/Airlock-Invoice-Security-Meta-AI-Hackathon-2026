# Airlock Operations

## Run (development, offline-capable)

```powershell
cd D:\Downloads\Meta_Hackathon_2026
.\.venv\Scripts\python.exe scripts\setup_airlock.py   # first run: secrets + seed help
$env:AIRLOCK_FIXTURE_READER = "1"
$env:AIRLOCK_ENV = "development"
.\.venv\Scripts\python.exe -m app.cli db upgrade     # owner-operated migrations
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd web; npm install; npm run dev                       # proxies /api to :8000
```

Startup refuses to serve on a stale schema (`require_schema_current`)
and `/health` reports `degraded` with `migrations_pending`. Never run
`reset_demo.py --yes` against data you want to keep.

## Configuration

Process environment is the only credential source; `.env` is never
auto-loaded (copy `.env.example`, keep it gitignored). Safety rails:
fixture/mock providers rejected in production, HTTPS-only Meta/Baseten
URLs, loopback-only plain HTTP for Glimmer, contributor models
rejected, `MODEL_API_KEY` ≠ `BASETEN_API_KEY`. Full reference:
[LOCAL_DEVELOPMENT](operations/LOCAL_DEVELOPMENT.md),
[LIVE_PROVIDER_CONFIGURATION](operations/LIVE_PROVIDER_CONFIGURATION.md),
[PROVIDER_FAILURE_RUNBOOK](operations/PROVIDER_FAILURE_RUNBOOK.md).

## Measured performance (local, offline, 2026-11-04)

- `scripts/phase5_benchmark.py --cases 5`: p50=39.6 ms, p95=164.0 ms,
  max=193.9 ms per case (fixture reader, temp DB). Live=NOT_TESTED.
- `scripts/phase3_eval.py`: 19 scenarios in 1165 ms (~61 ms/scenario).
- Full backend suite (941 tests): ~2 min on this machine.
- Provider calls are the unmeasured tail: bounded by per-task timeouts
  (connect 10 s; extraction 180 s; voice/SAM 300 s), ≤2 retries,
  ≤2 inflight per provider, breaker 5-fail/60 s.

## Concurrency and limits

Single Node, single owner. SQLite WAL + 5 s busy timeout; ≤2
concurrent cases (`BoundedSemaphore`, HTTP 429 beyond); optimistic
versioning on state transitions; duplicate-key race guarded at
proposal time. Uploads: ≤5 files, ≤10 MiB each, PDF ≤20 pages,
images ≤40 MP, audio/video ≤300 s. These are prototype ceilings, not
enterprise SLAs.

## PostgreSQL boundary (future, not a rewrite)

If multi-user or multi-node is ever needed, migrate at the
repository boundary (`app/storage/repositories.py` + `database.py`):
parameterized SQL ports directly; replace WAL/busy-timeout handling
with connection pooling, add row-level owner scoping, and move blobs
to object storage. No application module imports `sqlite3` except
through `app/storage/`.

## Day-2 checklist

- `POST /audit/verify` after risky operations (note: it appends an
  event); investigate `ok:false` immediately.
- Watch breaker-open provider statuses; keys rotate outside the repo.
- Back up `data/airlock.db*` + `data/blobs/` together (hash-bound).
- Keep `results/` local; it may contain host-specific paths.
