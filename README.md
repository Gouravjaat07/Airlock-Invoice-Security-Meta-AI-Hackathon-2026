# Airlock — Secure Invoice Intelligence and Payment Control

**Airlock is an evidence-grounded invoice verification and payment-control
pipeline.** Untrusted multimodal AI extracts facts from invoices, delivery
evidence, and voice notes; deterministic policy (R1–R10) evaluates them
against owner-seeded vendor, bank, and purchase-order records; and only
the authenticated owner can authorize a payment — which stays mock-only
in this prototype.

## Why it exists

Small finance teams pay supplier invoices by eyeballing PDFs. That misses
bank-detail substitution, duplicate billing, PO mismatches, bad
arithmetic, and lookalike vendors — and AI summarizers add a new failure
mode: the document can instruct the model. Airlock separates
interpretation (untrusted AI) from decision (deterministic policy) from
authority (owner-only confirmation).

## How it works

```
upload → typed extraction (T2) → vendor/bank/PO resolution
→ SAM + voice lanes → corroboration → R1–R10 verdict
→ proposal → owner challenge+PIN confirm → MOCK execution + audit chain
```

- **Meta Muse Spark** (`muse-spark-1.3`, + Baseten open + local Glimmer
  alternates): schema-constrained invoice extraction with provenance.
- **Meta Voice Transcribe** (`muse-voice-transcribe-1.0`): voice
  evidence compared deterministically against invoice facts.
- **Meta SAM** (`sam-3.1`): delivery segmentation as geometry + counts
  only — never a quantity verdict by itself.
- Fail-closed everywhere: explicit provider selection, no silent
  fallback, typed lane states (`evaluated` / `not_evaluated` /
  `failed` / `empty`), hash-chained audit.

Details: [architecture](docs/ARCHITECTURE.md),
[Meta integration](docs/META_AI_INTEGRATION.md),
[policy engine](docs/POLICY_ENGINE.md),
[product impact](docs/PRODUCT_IMPACT.md).

## Quickstart (offline, no keys)

```powershell
cd D:\Downloads\Meta_Hackathon_2026
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=pytest-of-Dell
```

```powershell
cd web; npm install; npm run typecheck; npm run lint; npm test; npm run build
```

One command for all offline gates: `powershell -File scripts\verify_repo.ps1`.

Evaluator start here: [docs/EVALUATOR_GUIDE.md](docs/EVALUATOR_GUIDE.md).
Demo script: [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md).

## Evidence (measured 2026-11-04, offline)

- Backend: 941 tests collected — 938 passed, 1 skipped, 2
  environment-blocked (sandbox socket denial; unrelated to product code).
- Frontend: 61/61 vitest, typecheck, lint, and production build green.
- Offline eval: 19/19 synthetic verdicts matched, false-ALLOW 0/10
  adversarial, schema 15/15. Live model quality: NOT_TESTED (opt-in only).
- Perf: p50 ≈ 40 ms/case offline (fixture reader).

Full numbers: [benchmark report](docs/evaluation/MODEL_BENCHMARK_REPORT.md).
Security: [threat model](docs/security/THREAT_MODEL.md),
[red-team matrix](docs/security/RED_TEAM_TEST_MATRIX.md),
[SECURITY.md](SECURITY.md).

## Repository layout

```text
app/       FastAPI backend: api, pipeline, providers, domain, services, storage, auth
web/       React 19 owner console (vitest + Playwright e2e)
fixtures/  Canonical synthetic data (23 binaries, 19 scenarios; drift-guarded)
tests/     Backend suite (unit/integration/api/providers/security/adversarial/e2e)
scripts/   Offline gates, evals, benchmarks, live smokes (explicit opt-in only)
eval/      Benchmark manifest schema + preregistration
policy/    Policy thresholds (rules are fixed in code)
registry/  Synthetic vendor/PO seed data
docs/      Audit, architecture, evaluation, security, runbooks
```

## Safety constraints (fixed)

Synthetic data only. Mock payments only. No model authorizes anything.
Live provider calls require explicit `--live --allow-billable`, never
run from pytest or CI. See [SECURITY.md](SECURITY.md).

## Limitations and roadmap

Single-owner SQLite prototype; live model quality unevaluated;
19-scenario benchmark is preliminary; no ERP/bank integration by
design. Roadmap: pilot history replay → capped live eval → roles →
documented PostgreSQL boundary. See
[product impact](docs/PRODUCT_IMPACT.md) and [operations](docs/OPERATIONS.md).

License: MIT (see `pyproject.toml`; no LICENSE file yet — see release notes).
