# AGENTS.md — Airlock contributor notes (humans and AI agents)

## What this repo is

Airlock: evidence-grounded invoice verification + payment control.
FastAPI + SQLite backend (`app/`), React 19 console (`web/`),
synthetic fixtures (`fixtures/`), offline evals (`scripts/phase*_*.py`).
Security invariants in `docs/EVALUATOR_GUIDE.md` are mandatory; any
change weakening them is a blocker.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=pytest-of-Dell
.\.venv\Scripts\python.exe -m ruff check app scripts tests
.\.venv\Scripts\python.exe scripts\phase5_eval.py
cd web; npm run typecheck; npm run lint; npm test; npm run build
powershell -File scripts\verify_repo.ps1   # all offline gates at once
```

pytest basetemp MUST be named `pytest-of-*` (hygiene scanner skips
that prefix; anything else trips `test_repo_tree_has_no_findings`).
Keep C: writes small; test temp belongs on D: outside sandboxes.

## Rules

- No live/billable provider calls without explicit owner instruction.
  Live flags (`--live --allow-billable`) never appear in tests or CI.
- Never print, commit, or request API keys. `.env` stays gitignored.
- Never reset/seed the live dev database (`data/`) as part of a task;
  use temp DBs (tests) or `.demo/` (manual runs).
- Preserve working behavior; minimal diffs; no unrelated refactors.
- Failing test = requirement. Never delete/skip/weaken tests or change
  expected results to fit implementation.
- Docs: link, don't duplicate. Phase records live in `docs/phase*/`;
  top-level docs (`ARCHITECTURE.md`, `POLICY_ENGINE.md`, …) summarize.
- New behavior needs a focused test in the existing layout first
  (see `tests/unit/test_media_metrics.py` for a small example).

## Layout

`app/api` routes · `app/pipeline` ingest→verdict→proposal ·
`app/providers` Meta/Baseten/Glimmer clients · `app/domain` taint,
facts, vendors, POs · `app/services` cases/approval/audit ·
`app/storage` SQLite + blobs · `app/auth` PIN/sessions/challenges ·
`app/evaluation` scenario eval + media metrics · `scripts` offline
gates/evals (stdlib-only) · `fixtures` canonical synthetic data
(`make_fixtures.py --check` guards drift) · `fixtures-custom` owner
extras (never in eval gates) · `policy/rules.toml` thresholds only ·
`registry/synthetic_vendors.json` seed data.
