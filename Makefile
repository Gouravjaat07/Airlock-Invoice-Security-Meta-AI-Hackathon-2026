# Airlock Phase 1 + Phase 2 + Phase 3 + Phase 5 — Unix convenience targets.
# PowerShell equivalents are documented in README.md; every target below
# has a direct `python scripts/...` command that works on Windows.
.PHONY: env hardware config manifest hygiene phase1 test lint coverage \
	fixtures db seed phase2 phase3 eval3 smoke3 phase5 eval5 bench5 smoke5 \
	serve verify-audit

env:
	python scripts/check_environment.py

hardware:
	python scripts/check_hardware.py

config:
	python scripts/validate_config.py

manifest:
	python scripts/validate_manifest.py eval/manifest.dev.template.json

hygiene:
	python scripts/check_secret_hygiene.py

phase1:
	python scripts/phase1_check.py

test:
	python -m pytest -q

lint:
	python -m ruff check scripts tests app

coverage:
	python -m coverage run -m pytest -q
	python -m coverage report

fixtures:
	python scripts/make_fixtures.py --check

db:
	python -m app.cli db upgrade

seed:
	python scripts/seed_demo.py

phase2:
	python scripts/phase2_check.py --strict

phase3:
	python scripts/phase3_check.py --strict

eval3:
	python scripts/phase3_eval.py

smoke3:
	python scripts/smoke_phase3.py

phase5:
	python scripts/phase5_check.py --strict

eval5:
	python scripts/phase5_eval.py

bench5:
	python scripts/phase5_benchmark.py

smoke5:
	python scripts/phase5_live_smoke.py

serve:
	python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

verify-audit:
	python scripts/verify_audit_chain.py
