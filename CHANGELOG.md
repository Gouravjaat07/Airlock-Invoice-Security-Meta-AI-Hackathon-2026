# Changelog

## 2026-11-04 — Engineering excellence mission (offline; no live calls)

Added product behavior:

- Global `X-Content-Type-Options: nosniff` middleware (`app/main.py`;
  no global CSP by design — Swagger UI needs script).
- Media-quality metric library (`app/evaluation/media_metrics.py`):
  WER/CER, count error/MAE, discrepancy rule — defined and
  unit-tested; live voice/vision scoring stays NOT_TESTED.

Hardening and honesty fixes:

- Glimmer READY reason no longer claims a checked endpoint
  (`app/providers/registry.py`).
- WAV duration parser requires RIFF/WAVE magic (was: any 44+ bytes
  parsed); static guards pin parameterized SQL + fail-open dims
  (`tests/unit/test_static_guards.py`).
- New offline CI (`ci.yml`): ruff over `app`, full pytest, fixture
  drift, hygiene, evals, plus frontend typecheck/lint/test/build.
  (Action SHA pinning documented; needs network to resolve.)
- One-command offline verification: `scripts/verify_repo.ps1`.

Docs and evaluation:

- Rewrote README (was stale Phase-1 text); added AGENTS.md,
  evaluator guide, architecture/data-flow/policy docs, product
  impact, Meta AI integration, operations, dependencies, demo
  runbook + scenarios, threat model, red-team matrix, SECURITY.md,
  benchmark report + dated JSON snapshot, CHANGELOG.
- Benchmark: offline 19/19 verdicts, false-ALLOW 0/10, schema 15/15;
  live layers NOT_TESTED. Perf: p50 ≈ 40 ms/case offline.

Verification: backend 941 collected (938 passed, 1 skipped,
2 sandbox-blocked); frontend 61/61 + typecheck + lint + build;
ruff clean; e2e blocked (sandbox denies loopback bind).
