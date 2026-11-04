# Airlock GitHub Release Readiness

Date: 2026-11-04. Status: READY TO COMMIT after owner review, with the
blockers in §5 resolved by the owner. No push performed (awaiting
explicit approval).

## 1. Git state

- Branch: `main`, zero commits, no remote configured.
- `git status --short` shows only intentional content: `.env.example`,
  `.github/`, `.gitignore`, `AGENTS.md`, `CHANGELOG.md`, `Makefile`,
  `README.md`, `SECURITY.md`, `app/`, `docs/`, `eval/`,
  `fixtures-custom/`, `fixtures/`, `policy/`, `prereg/`,
  `pyproject.toml`, `registry/`, `scripts/`, `tests/`, `web/`.
- Scratch excluded via `.gitignore` (2026-11-04): `tmp*/`, `probe_*/`,
  `pip-*/`, `.wheels/`, `.demo/`, `pytest-of-Dell/`, `*.bak`,
  `inspect_db_tmp.py`. Files left in place (owner property), hidden
  from commits.
- Already ignored and verified: `.env`, `.venv/`, `data/`, `results/`,
  `web/dist/`, `web/node_modules/`, `*.egg-info/`, `.coverage`.

## 2. Secret scan

- `scripts/check_secret_hygiene.py`: clean, exit 0 (2026-11-04).
- `git ls-files .env`: empty (never tracked). No git history exists,
  so no historical exposure is possible.
- `.env` present locally (3.2 KB, gitignored) — never commit it.
- Scanner limitation (documented): pattern-based; >1 MB, non-UTF8,
  and escaping-symlink files are listed as skipped, not scanned.

## 3. Test and gate results (offline)

- Backend: 941 collected; 938 passed; 1 skipped (symlink rights);
  2 failed — both `test_startup_readiness.py` lifespan tests, blocked
  only by sandbox socket denial (WinError 10013), unrelated to code.
- Frontend: vitest 61/61, `tsc --noEmit`, `eslint`, `vite build` green.
- Ruff (`app scripts tests`): clean. Fixtures: 23 binaries + 19
  scenarios drift-free. Evals: 19/19 verdicts, false-ALLOW 0,
  schema 15/15; live NOT_TESTED.
- e2e (Playwright): NOT RUN here — sandbox denies loopback bind.
  Browsers are installed; run outside the sandbox per `web/e2e/smoke.mjs`.
- Full gate script: `powershell -File scripts\verify_repo.ps1`.

## 4. CI and dependencies

- `.github/workflows/ci.yml` (new): backend matrix (win+linux ×
  py3.11–3.13) + frontend jobs, offline, least-privilege
  (`contents: read`). Legacy `phase1.yml` retained.
- Action SHAs not pinned (sandbox TLS broken): resolve + pin before
  release; procedure documented in `ci.yml` header.
- Python: no known-vuln scan (`pip-audit` install blocked by sandbox
  network); re-run outside. Orphan `pypdf` in `.venv` is unreferenced.
- npm prod deps: 0 vulnerabilities. Dev-only: 15 (13 moderate,
  2 critical, vitest/tinypool toolchain) — accepted residual, first-party
  tests only, documented in `docs/DEPENDENCIES.md`.

## 5. Owner blockers (need your decision)

1. **LICENSE**: `pyproject.toml` says MIT but no LICENSE file exists.
   Add your chosen license text before going public.
2. **Remote**: no GitHub remote configured. Create the repo, then
   `git remote add origin <url>` (private first, review, then public).
3. **Action SHAs**: pin per `ci.yml` header once network allows.
4. **Outside-sandbox confirmation**: 2 lifespan tests + e2e + pip-audit.
5. **Live providers** (optional, separate): owner-only `--live` smokes.

## 6. Commit recommendation (after §5.1)

Review the tree once more (`git status`, `git diff --stat` after add),
then:

```powershell
git add .env.example .github .gitignore AGENTS.md CHANGELOG.md Makefile README.md SECURITY.md app docs eval fixtures fixtures-custom policy prereg pyproject.toml registry scripts tests web/package.json web/package-lock.json web/vite.config.ts web/tsconfig*.json web/eslint.config.* web/e2e web/src web/index.html web/public
git status   # confirm: no .env, data/, results/, .venv, dist/, node_modules, scratch
git commit -m "Airlock submission: verified offline gates, evals, and docs"
```

(Explicit paths on purpose: never `git add -A` on this tree.)
Create the remote, push to a private repo, re-verify, then flip
visibility. No force-push, no history rewrite needed (no history yet).
