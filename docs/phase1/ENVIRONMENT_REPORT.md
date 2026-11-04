# Environment report (Phase 1)

Generated from `python scripts/check_environment.py --json
results/phase1/environment.json` on 2026-10-30 (forensic audit rerun).
Machine values below are observed, not assumed. Structured evidence:
`results/phase1/environment.json` (git-ignored; regenerate on demand).

## Observed environment

| Check | Status | Observed value |
|---|---|---|
| Operating system | PASS | Windows 11 (10.0.26200), AMD64 |
| Python runtime | WARNING | 3.13.5 at `C:\Users\Dell\AppData\Local\Programs\Python\Python313\python.exe`; intended app runtime is 3.11 |
| venv support | PASS | stdlib `venv` available; not in a venv |
| pip | PASS | pip 25.3 (python 3.13) |
| Git | WARNING | git 2.50.1.windows.1; repository status unavailable in this sandbox (directory-ownership mismatch — see notes) |
| Node.js | PASS | v22.18.0 (future dashboard only) |
| npm | PASS | 10.9.3 (via .cmd shim; shell-execution fallback verified) |
| Muse Code CLI | NOT_AVAILABLE | `muse.CMD` present but `--version` fails in this sandbox (profile-write access denied); owner account previously reported 1.4.14 |
| Developer packages | PASS | pytest 8.4.2 available |
| Working directory | PASS | `D:\Downloads\Meta_Hackathon_2026` = project root |
| Repository scaffold | PASS | all 44 required Phase 1 paths exist |
| Disk | PASS | 90.5 GiB free of 138.5 GiB on D: |
| Config vars | PASS | 0/11 known variables set (names only; expected — no keys in session) |
| Local weights | PASS | none in project (expected) |
| Uncommitted files | NOT_AVAILABLE | `git status` unreadable in this sandbox (same ownership mismatch) |

Summary: PASS=11, WARNING=2, NOT_AVAILABLE=2. Exit code 0 (no FAIL).

## Notes and caveats

- **Python 3.11 vs 3.13:** `py -0p` lists only 3.13. Phase 1 tooling is
  stdlib-only and runs on ≥3.11, so nothing is blocked; the app re-target
  decision lands before Phase 2 dependencies (B-01). CI covers 3.11–3.13
  but has no remote run yet (B-11).
- **Muse CLI:** the sandbox cannot execute the real `muse.CMD`
  (`--version` dies writing to the owner profile). The audit reports
  NOT_AVAILABLE here rather than borrowing the owner account's 1.4.14
  observation. INTEGRATION_STATUS keeps the two sessions distinct.
- **Git in this session:** the repo has no commits yet (branch `main`,
  everything untracked — no commit without an explicit request), and
  sandbox commands run as a different user than the directory owner, so
  git reports dubious ownership. The audit distinguishes "repo unreadable"
  from "not a repo" instead of conflating them. Per-command
  `-c safe.directory=...` reads status without persisting config; the
  owner account runs git normally.
- **CIM restriction:** `Get-CimInstance Win32_VideoController` is access-
  denied for the sandbox user (stderr captured live in `hardware.json`);
  GPU-name evidence comes from other probes (see HARDWARE_REPORT.md).
- **No `.env` file** exists; no secrets were introduced. Hygiene scan:
  42 files, 0 findings, ignore rules OK (textual; behavioral git checks
  unavailable in this sandbox).
