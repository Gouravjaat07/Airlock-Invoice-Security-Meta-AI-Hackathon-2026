# Local development

Windows PowerShell, Python 3.11+, Node 18+. All offline work needs
no API keys.

## Backend

```powershell
cd D:\Downloads\Meta_Hackathon_2026
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
```

First run also needs app secrets + seed (dev only):

```powershell
.\.venv\Scripts\python.exe scripts\setup_airlock.py
```

(see that script's `--help`; it prints the required env exports —
never commit them). Fixture mode for local intake:

```powershell
$env:AIRLOCK_FIXTURE_READER = "1"
$env:AIRLOCK_ENV = "development"
```

Run the API: `.\.venv\Scripts\python.exe -m uvicorn app.main:app`
(entry per `app/main.py`; bind loopback for dev).

## Frontend

```powershell
cd web
npm install
npm run typecheck
npm run lint
npm test
npm run build
```

Dev server proxies `/api` to `127.0.0.1:8000` (see
`web/vite.config.ts`). E2E needs the backend + PIN; see
`web/e2e/smoke.mjs` header for the isolated-env recipe
(temp DB/BLOB paths, seeded vendors, `AIRLOCK_E2E_PIN`).

## Gates (offline, no keys)

```powershell
.\.venv\Scripts\python.exe scripts\phase2_check.py --strict
.\.venv\Scripts\python.exe scripts\phase3_check.py --strict
.\.venv\Scripts\python.exe scripts\phase5_check.py --strict
.\.venv\Scripts\python.exe scripts\phase5_eval.py
.\.venv\Scripts\python.exe scripts\phase5_benchmark.py --cases 5
.\.venv\Scripts\python.exe -m ruff check scripts tests app
```

Live checks are separate and always explicit:
`phase5_live_smoke.py --live --allow-billable`.

## Conventions

- `scripts/` are run from the repo root; smoke scripts default to
  preflight (no network) and cap live calls.
- Tests are offline: stub transports at the HTTP boundary, fake
  keys (`tk`-style, inert), temp DBs. Never add a test that
  requires a real key or the network to pass.
- `.env` is never auto-loaded; export secrets into the process.
- Never run payment E2E against the real database; never commit
  `results/`, `data/`, `.env`, or build output.
