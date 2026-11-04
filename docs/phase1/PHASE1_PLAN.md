# Phase 1 plan — bootstrap, evidence, research preregistration

Scope: environment, project structure, model-access evidence, hardware
feasibility, config validation, safe test utilities, docs, benchmark schema,
preregistration. Explicitly NOT in scope: the React dashboard, invoice app,
business endpoints, proposal workflow, auth service, benchmark engine.

## Work items

1. Inspect workspace (done 2026-10-30: empty except harness dirs).
2. Scaffold repo: packaging, gitignore, env template, dirs (done).
3. `validate_config.py`: typed config, URL syntax, Contributor guard,
   key separation, future-phase vars (done).
4. `check_environment.py`: OS/Python/pip/git/node/muse/scaffold/disk/
   vars/weights/git-status, PASS/FAIL/WARNING/NOT_AVAILABLE/NOT_TESTED (done).
5. `check_hardware.py`: RAM/GPU/disk/runtime/weights + 3-state Glimmer
   decision (done).
6. Smoke utilities (`smoke_meta/baseten/sam/voice`) + `_smoke_common.py`:
   preflight default, double-gated live, sanitized records (done).
7. `record_smoke_result.py`: validated, credential-rejecting history (done).
8. `eval/manifest.schema.json` + dev template + README (done).
9. `validate_manifest.py`: stdlib mirror validator (done).
10. `prereg/PREREGISTRATION.md`: question, Kill Tests 1–2, final plan,
    stats, zero results (done).
11. `check_secret_hygiene.py`: patterns + ignore rules + diff scan (done).
12. `phase1_check.py`: 6-section orchestrator, no live calls (done).
13. Tests: 6 files covering env/config/secrets/safety/schema/reports (done).
14. Docs: README, SOURCES, ADRs, 9 phase-1 reports (this file + 8 more).
15. Run: pytest, phase1_check, env/hardware JSON reports (pending).
16. Git init (pending; no commit without explicit request).
17. PHASE1_REPORT with gate verdict (pending; needs step 15).

## Out-of-scope reminders

- No live API calls from any default/test/orchestrator path.
- No `muse-spark-1.3-contributor` runtime use.
- No model downloads; no invented filenames/licences/results.
- No real invoices, payments, bank data, or human voice recordings.
