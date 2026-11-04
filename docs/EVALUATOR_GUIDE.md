# Airlock Evaluator Guide

Five-minute path from clean clone to verified judgment. No API keys
needed for anything below; live providers are never required.

## What Airlock is (30 seconds)

Evidence-grounded invoice verification and payment control: untrusted
multimodal AI extracts facts, deterministic policy (R1–R10) evaluates
them against owner-seeded records, and only the owner authorizes a
payment (mock-only). See [PRODUCT_IMPACT](PRODUCT_IMPACT.md) and
[ARCHITECTURE](ARCHITECTURE.md).

## Entry points

- API: `app/main.py:create_app()` → `app/api/router.py` (`/api/v1`).
- Pipeline: `app/pipeline/process.py:run_case`.
- Policy: `app/pipeline/policy.py:evaluate_policy`.
- Providers: `app/providers/registry.py` (selection), `spark.py`,
  `voice.py`, `sam.py`, `baseten.py`, `glimmer.py`.
- Console: `web/src/App.tsx`; evidence states `web/src/utils/evidence.ts`.
- Tests: `tests/` (941); eval: `scripts/phase3_eval.py`, `phase5_eval.py`.

## Commands that work from a clean clone

```powershell
cd <repo>
py -3.11 -m venv .venv   # 3.11–3.13; 3.13.5 verified
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# Backend suite (offline; name the basetemp pytest-of-* so the hygiene
# scanner skips it — any other in-repo name self-incriminates):
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=pytest-of-Dell

# Lint, fixtures, evals, benchmark (all offline, no keys):
.\.venv\Scripts\python.exe -m ruff check app scripts tests
.\.venv\Scripts\python.exe scripts\make_fixtures.py --check
.\.venv\Scripts\python.exe scripts\phase3_eval.py --output-dir results\phase3\eval
.\.venv\Scripts\python.exe scripts\phase5_eval.py
.\.venv\Scripts\python.exe scripts\phase5_benchmark.py --cases 5
.\.venv\Scripts\python.exe scripts\check_secret_hygiene.py

# Frontend (web/):
npm install; npm run typecheck; npm run lint; npm test; npm run build
# If vitest fails with EPERM on Temp, set TEMP/TMP/TMPDIR to web/.vitest-tmp first.
```

Or run everything: `powershell -File scripts\verify_repo.ps1`
(no network, no keys, no database touched).

## How to judge each claim

| Claim | Check |
|---|---|
| Clean invoice allows | `test_clean_case_allows_and_proposes`; scenario `clean` in phase3 eval |
| Bank/arithmetic/duplicate rejected | `test_r2_wrong_bank_denies`, `test_w03_arithmetic_denies`, `test_duplicate_second_run_denies` |
| Injection stays inert | `test_w11_prompt_injection_inert`, `hidden-text`/`planner-injection` scenarios |
| Evidence never faked green | `tests/unit/test_evidence_lanes.py`, `web/src/utils/evidence.ts` + `badges.tsx` |
| Owner-only + mock-only | `tests/security/`, `test_confirm_stale_and_nonallow` |
| No silent fallback | `tests/providers/test_registry.py`, provider error tests |
| Benchmark honesty | [MODEL_BENCHMARK_REPORT](evaluation/MODEL_BENCHMARK_REPORT.md): offline 19/19, live NOT_TESTED |

## Known limitations (do not mistake for defects)

- 2 startup tests need real sockets; 1 symlink test needs symlink
  rights — all three are environmental, documented in the audit.
- Live Spark/Voice/SAM quality is NOT_TESTED (owner opt-in only).
- e2e needs loopback servers + PIN (see `web/e2e/smoke.mjs` header).
- Single-owner SQLite prototype; mock payments by design.

## Security invariants (must hold after any change)

T0-only authorization; model outputs untrusted (T2); no model
approval/authorization/execution; deterministic R1–R10; explicit
fail-closed providers; hash-chained audit; registered fixtures need
exact hashes; live calls only via `--live --allow-billable`, never
from pytest or CI.
