# Phase 5 results

Status: **MEASURED 2026-11-03** (offline evidence complete; live
evidence BLOCKED as recorded below). All commands ran from the repo
root with `.\.venv\Scripts\python.exe` (backend) and `npm` in `web/`
(frontend). Machine-local `results/phase5/` artifacts accompany this
file (git-ignored).

## Offline results (executed)

| Suite | Command | Result |
|---|---|---|
| Backend pytest (840) | `pytest -p no:cacheprovider -q` | 837 passed, 1 skipped, 2 failed* |
| Phase 5 suites (18) | `pytest tests/phase5` | 18 passed |
| Ruff | `ruff check scripts tests app` | clean |
| Phase 2 strict | `phase2_check.py --strict` | 20/21 (P2-08*) |
| Phase 3 eval | `phase3_eval.py` | 19/19, false-ALLOW=0 |
| Phase 3 strict | `phase3_check.py --strict` | 13/14 (P3-09 cascaded*) |
| Phase 5 strict | `phase5_check.py --strict` | 13/14 (P5-14 cascaded*); all 13 native P5 checks PASS |
| Phase 5 eval | `phase5_eval.py` | 19/19 verdicts, false-ALLOW=0, schema 15/15 |
| Benchmark (5 cases) | `phase5_benchmark.py --cases 5` | min 43.2 / p50 53.3 / p95 132.5 / max 152.1 / mean 69.3 ms |
| Frontend typecheck | `npm run typecheck` | pass |
| Frontend lint | `npm run lint` | pass |
| Frontend tests (53) | `npm test` | 53 passed (47 baseline + 6 new) |
| Frontend build | `npm run build` | pass (116 modules, 4.03 s) |
| Audit chain | read-only `verify_chain` on `data/airlock.db` | OK, 118 events |
| Playwright E2E | `npm run e2e` (isolated) | BLOCKED* (see below) |
| Live smoke preflight | `phase5_live_smoke.py` | exit 0, no network, sanitized record |

\* The 2 pytest failures (`test_startup_readiness.py`), P2-08, P3-09,
P5-14, and Playwright share one root cause: this sandbox forbids all
socket use (`WinError 10013` on `bind`/`listen`/`connect`, proven by
direct probe). The 2 failures reproduce identically with the Phase 5
code edit reverted, and the traceback fails inside stdlib
`asyncio`/`socket` before any app code runs — pre-existing and
environmental, not a regression. Frontend tests needed `TEMP`
redirected to gitignored `node_modules/.tmp` (system temp is
read-only here); what was tested did not change.

Benchmark detail: verdicts {ESCALATE 1, DENY 3, ALLOW_PROPOSAL 1},
46 audit events, 14.42 cases/s. Eval detail: schema part excludes
the 4 failure-variant fixtures (covered by the verdict part);
`malformed-reader` DENY-via-R8 matched as specified.

## Live results (BLOCKED — two independent causes)

| Provider | Status | Cause |
|---|---|---|
| Meta Spark smoke | BLOCKED | `MODEL_API_KEY` UNSET + outbound connect forbidden |
| Meta Voice smoke | BLOCKED | `MODEL_API_KEY` UNSET + outbound connect forbidden |
| Meta SAM smoke | BLOCKED | `MODEL_API_KEY` UNSET + outbound connect forbidden |
| Baseten smoke | BLOCKED | `BASETEN_API_KEY` UNSET + outbound connect forbidden |
| Glimmer probe | NOT AVAILABLE | no local runtime + loopback connect forbidden |
| Live reader scoring | NOT_TESTED | requires the above |

Credential check was presence-only (names + set/unset; no values
read or printed). No live call was attempted: there are no
credentials to call with, and the sandbox forbids the connection.
Preflight for all providers exits 0 and records NOT_TESTED.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q
.\.venv\Scripts\python.exe scripts\phase5_check.py --strict
.\.venv\Scripts\python.exe scripts\phase5_eval.py
.\.venv\Scripts\python.exe scripts\phase5_benchmark.py --cases 5
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --live --allow-billable --max-calls 5  # needs keys + network
```

Methodology: `PHASE5_BENCHMARK_METHODOLOGY.md`.

---

## Multimodal hardening run (MEASURED 2026-11-04)

Offline re-verification after the multimodal live-integration
hardening (extraction contract v4, voice/SAM lane outcomes, R7
not-evaluated messaging, evidence UI, dev launcher). Historical
2026-11-03 results above are unchanged.

| Suite | Command | Result |
|---|---|---|
| Backend pytest (918) | `pytest -p no:cacheprovider` | 915 passed, 1 skipped, 2 failed* |
| Providers + phase5 (329) | `pytest tests/providers tests/phase5` | 329 passed |
| Ruff | `ruff check scripts tests app` | clean |
| Phase 2 strict | `phase2_check.py --strict` | 20/21 (P2-08*) |
| Phase 3 eval | `phase3_eval.py` | 19/19, false-ALLOW=0 |
| Phase 3 strict | `phase3_check.py --strict` | 13/14 (P3-09 cascaded*) |
| Phase 5 strict | `phase5_check.py --strict` | 13/14 (P5-14 cascaded*); all 13 native P5 checks PASS |
| Phase 5 eval | `phase5_eval.py` | 19/19 verdicts, false-ALLOW=0, schema 15/15 |
| Benchmark (5 cases) | `phase5_benchmark.py --cases 5` | p50 37.4 / p95 145.7 / max 172.3 ms |
| Frontend typecheck | `npm run typecheck` | pass |
| Frontend lint | `npm run lint` | pass |
| Frontend tests (61) | `npm test` | 61 passed (53 baseline + 8 new) |
| Frontend build | `npm run build` | pass |
| Secret hygiene | `check_secret_hygiene.py` | clean |
| Audit chain | `verify_audit_chain.py` on `data/airlock.db` | OK, 118 events |
| Playwright E2E | `npm run e2e`, `e2e:multimodal` (new, unexecuted) | BLOCKED* (see below) |
| Live smoke preflight | `phase5_live_smoke.py` | exit 0, no network, sanitized record |
| Live providers | billable calls | NOT_TESTED (not authorized this session) |

\* Same single root cause as 2026-11-03: this sandbox forbids all
socket use (`WinError 10013` on `bind`/`listen`/`connect`). The 2
pytest failures (`test_startup_readiness.py`), P2-08, P3-09, P5-14,
and Playwright are blocked identically with and without the
hardening edits (traceback fails in stdlib `asyncio`/`socket`
before any app code). Frontend tests needed `TEMP` redirected to
the writable sandbox temp dir; what was tested did not change.
78 backend tests are new since 2026-11-03 (routing, extraction
contract, evidence lanes, adapter errors, multimodal pipeline);
all pass. No live call was made: billable requests were not
authorized, so live frontend behavior is verified to the extent
offline evidence allows (stubbed transports, contract tests) and
awaits the user's live run per
`docs/operations/MULTIMODAL_DEV_STARTUP.md`.
