# Airlock Dependency and Supply-Chain Report

Date: 2026-11-04. Policy: no mass upgrades; fix only with a reason,
then re-run affected gates.

## Backend (Python, `pyproject.toml`)

Runtime (all used by `app/` imports, verified 2026-11-04):
fastapi 0.154.0, pydantic 2.14.2, uvicorn 0.35.0,
python-multipart 0.0.33, argon2-cffi 25.1.0, httpx 0.28.1.
Dev: pytest 8.4.2 (pinned), coverage 7.17.0. Lint: ruff 0.17.3
(`ruff check app scripts tests` → all pass).

- `pypdf` 6.21.4 is installed in `.venv` but imported nowhere
  (`app/`, `scripts/`, `tests/` all searched): orphan package, no
  code depends on it. Recommendation: fresh environments simply do
  not install it; no code change needed.
- `pip-audit`: not installed; install attempted during this mission
  (network-restricted sandbox). No Python advisory scan completed —
  recorded as a gap, not a pass. Re-run outside the sandbox:
  `pip install pip-audit && pip-audit`.
- No lockfile for Python (`pip install -e ".[dev]"` resolves ranges
  at install time). Ranges are narrow (e.g. `fastapi>=0.115,<0.155`);
  consider `pip freeze` capture in CI evidence for reproducibility.

## Frontend (`web/package-lock.json`, 160 KB, committed)

Prod deps: react 19, react-dom 19, react-router-dom 7,
@tanstack/react-query 5 — `npm audit --omit=dev` → **0 vulnerabilities**.

Dev-only findings (`npm audit`, 2026-11-04): 15 vulnerabilities
(13 moderate, 2 critical), all in the eslint/vitest toolchain:
@vitest/mocker path-traversal + mock-registration advisories
(GHSA-82fw, GHSA-qxg6), tinypool RCE gadgets (GHSA-5gmw, GHSA-85c8),
minimatch glob DoS (GHSA-g3hv), plus eslint-utils chain. `npm audit
fix` changed nothing (fixes are pinned behind the vitest 3.2.7 range;
latest vitest is 5.1.0, a breaking major).

Decision: accept as residual. Rationale: dev-only (never shipped in
`dist/`), exploitable only by running untrusted test code, and all
tests are first-party. Revisit on the next scheduled vitest major
upgrade, with the full frontend gates re-run.

## CI supply chain

`.github/workflows/phase1.yml` pins nothing (`actions/checkout@v4`,
`setup-python@v5`, `upload-artifact@v4`). The new `ci.yml` (Stage 7)
pins actions to full commit SHAs. No model weights, binaries, or
vendored deps in the repo.
