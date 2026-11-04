# Phase 1 report — evidence-backed status

Date: 2026-10-30 (forensic audit rerun). Workspace:
`D:\Downloads\Meta_Hackathon_2026`.
Method: every claim below traces to a script run, test result, or inspected
file. Structured evidence: `results/phase1/*.json` (regenerate with the
commands in "Reproduce"). Pre-repair snapshots are preserved under
`results/phase1/audit/pre_repair/`; the audit baseline inventory is
`results/phase1/audit/baseline_inventory.json`.

## Gate verdict: `PARTIAL` — Phase 2 can start with documented fallbacks

Release gates (A–H) per the Phase 1 audit brief:

| Gate | Verdict | Evidence |
|---|---|---|
| A — Workspace and environment | PARTIAL | Root verified; scaffold 44/44; Python 3.13 tested (WARNING, intended 3.11); 3.11 untested locally and covered only by un-run CI (B-01, B-11); Windows shims verified; sandbox git/CIM limits recorded, not hidden |
| B — Core Phase 1 tooling | PASS | Every diagnostic, validator, and offline smoke runs; exit codes correct; atomic JSON writes; provenance envelopes; default mode provably request-free |
| C — Model/API readiness | PARTIAL | Preflights verified offline; HTTPS/userinfo/error-category hardening tested; live auth and inference `NOT_TESTED` (keys unset, no opt-in run — B-10); user-reported tests never upgraded |
| D — Research reproducibility | PASS | Manifest contract v2 (`attack_type`) reconciled across schema, template, validator, tests, prereg; hash verification enforced; artifact paths hardened; prereg honest (zero results invented) |
| E — Security | PASS | Hygiene clean (42 files, 0 findings); `.env` ignored (textual; behavioral git checks unavailable in sandbox); redaction verified; symlink/encoding/skip hardening tested; offline default enforced by a structural guard test |
| F — Tests and quality | PARTIAL | 153 tests: 152 pass, 1 genuine platform skip; ruff configured but unavailable locally (unverified); coverage unmeasured locally (tool unavailable); dependency audit not run |
| G — Orchestrator and evidence | PASS | Step-J root-caused (missing CLI flags → argparse exit 2) and repaired; `--strict/--output-dir/--live/--allow-billable/--verbose/--version` all work; strict exits 1 on PARTIAL; FAIL records block; JSON valid with provenance; sections↔overall consistent |
| H — Documentation and CI | PARTIAL | README/commands verified; AD-13…AD-15 appended; CI configured (Windows+Linux × 3.11–3.13, offline only) but never executed by a runner (B-11) |

PARTIAL, not READY, because live integrations are unverified (B-10),
Python 3.11 is untested anywhere (B-01/B-11), and lint/coverage are
configured but locally unverified — all expected Phase 1 outcomes with
explicit blockers. No gate FAILED or BLOCKED; nothing blocks starting the
deterministic core in Phase 2.

## What was built

- `pyproject.toml` (stdlib-only runtime; pinned pytest, coverage config,
  ruff F-gate), `.gitignore`, `.env.example`, `Makefile`, `README.md`,
  `.github/workflows/phase1.yml`.
- `scripts/` (13): `_common`, `phase1_check`, `check_environment`,
  `check_hardware`, `validate_config`, `validate_manifest`,
  `check_secret_hygiene`, `record_smoke_result`, `smoke_meta`,
  `smoke_baseten`, `smoke_sam`, `smoke_voice`, `_smoke_common`.
- `tests/`: conftest + 7 test files, 153 tests.
- `docs/`: SOURCES, ARCHITECTURE_DECISIONS (AD-01…AD-15), 10 phase-1
  reports (incl. MANIFEST_MIGRATION_v2).
- `eval/`: schema v2 + dev template + README. `prereg/`: preregistration.
- Placeholders: `app/.gitkeep`, `web/.gitkeep`, `results/phase1/.gitkeep`.
- No application code was built (out of scope); no fakes.

## Key observed facts

- Windows 11 (10.0.26200, AMD64), Python 3.13.5 (intended app runtime
  3.11 — B-01), pip 25.3, git 2.50.1, node 22.18.0, npm 10.9.3,
  pytest 8.4.2. `muse` CLI not runnable in this sandbox (NOT_AVAILABLE).
- 90.5 GiB free of 138.5 GiB on D:; 7.82 GiB RAM; no GPU by any probe
  (CIM denial captured live); no runtimes; no weights.
- 0/11 config vars set; no `.env`; no secrets introduced or printed.
- Hardware decision: `LOCAL_GLIMMER_UNAVAILABLE` → fallback active.
- Orchestrator: `PARTIAL`, strict exit 1; research/security/docs PASS.
- Bugs found and fixed by the forensic audit: Step-J unknown-flag exit 2,
  NOT_TESTED→PASS fold, unreachable api PASS, truncate-in-place writes,
  http-override acceptance, URL-userinfo echo, 403/408 misclassification,
  non-UTF8 `.env` crash, manifest v1/v2 name split, unverified hashes,
  trailing-newline regex parity, UNC dead code, symlink-escape read,
  silent skips, `/.env` miss, git-unreadable mislabel, GB/GiB split,
  tautology guard test, unpinned deps, missing CI.

## What remains unverified (honest list)

- Spark 1.3 / Baseten access: user-reported tested, not reproduced here.
- SAM / Voice schemas: unverified; live paths refuse by design.
- Glimmer licence + exact weight filenames: reported, primary unopened.
- 2M tok/min + $100 credit: user-reported, account unconfirmed.
- Python 3.11 runtime: no local interpreter; CI matrix un-run.
- Ruff/coverage results: configured, tools unavailable in this sandbox.
- No live or billable call was made in this phase.

## Reproduce

```powershell
cd D:\Downloads\Meta_Hackathon_2026
python -m pytest -q
python scripts\phase1_check.py --strict --json results\phase1\phase1_report.json
python scripts\check_environment.py --json results\phase1\environment.json
python scripts\check_hardware.py --json results\phase1\hardware.json
python scripts\check_secret_hygiene.py --json results\phase1\secret_hygiene.json
python scripts\validate_config.py --json results\phase1\configuration.json
python scripts\validate_manifest.py eval\manifest.dev.template.json
```

Strict orchestrator exits 1 while PARTIAL (correct: live work remains).
Plain `phase1_check.py` exits 0 unless BLOCKED. The strict command also
passes from any working directory with an absolute script path.

(Sandbox sessions: git needs a per-command `-c safe.directory=...`
workaround for the ownership mismatch; the tools report the limitation
honestly and the owner account runs git normally.)
