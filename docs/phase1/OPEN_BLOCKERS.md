# Open blockers (Phase 1 → Phase 2)

Severity: `gate` (blocks stated next step) / `major` / `minor`.
Owner: `user` (needs account/access/decision) or `dev` (build work).

| ID | Description | Evidence | Severity | Blocks Phase 2 start? | Next action | Owner | Status |
|---|---|---|---|---|---|---|---|
| B-01 | Python 3.11 not installed (3.13 present) | `py -0p` → 3.13 only | minor | No — Phase 1 tooling runs on ≥3.11 | Install 3.11 or formally re-target before app deps | dev | Open |
| B-02 | `MODEL_API_KEY` unset; Spark 1.3 unverified locally | validate_config INFO; no smoke logs | major | No — mocked clients unblock core | User sets key; run opt-in live text test | user | Open |
| B-03 | `BASETEN_API_KEY` unset; deployment unverified | Same as B-02 | major | No — optional path | Confirm deployment id/limits; 1 minimal call | user | Open |
| B-04 | No GPU on this machine; Glimmer unavailable | check_hardware UNAVAILABLE | gate (for local reader) | No — fallback documented | Use hosted/mock reader; revisit w/ hardware | dev | Open, fallback active |
| B-05 | Glimmer licence + exact GGUF filenames unverified | SOURCES.md uncertainty log | major (for local reader) | No — fallback active | Open HF card; record licence + filenames | dev | Open |
| B-06 | SAM request schema unverified | smoke_sam refuses live | major (for visual check) | No — condition F conditional | Open dev.meta.ai/docs/sam/*; build payload | dev | Open |
| B-07 | Voice endpoint/format unknown | smoke_voice refuses live | minor | No — voice optional | Locate official doc or drop voice path | dev | Open |
| B-08 | Rate limit (2M tok/min) + $100 credit unverified | User-reported only | minor | No | Confirm in account dashboards | user | Open |
| B-10 | Live integrations unverified locally (keys unset, no opt-in run) | api_evidence PARTIAL; 0 local records | gate (for READY) | No — PARTIAL expected | Set keys; run `phase1_check.py --live --allow-billable` explicitly | user | Open |
| B-11 | No remote CI execution yet (config added, never run by a runner) | `.github/workflows/phase1.yml` present, no runs | minor | No | Push to a remote; record first green run | dev | Open |

Resolved this phase: scaffold, config contract, audit scripts, smoke
utilities, manifest schema v2 + validator + hash verification,
preregistration, hygiene checks, repaired orchestrator (Step-J flags,
aggregation, atomic writes, provenance), provider live plumbing, CI
configuration, test suite (153 tests: 152 passing, 1 genuine platform
skip), docs (this set).

Closed by the forensic audit (were open/stale before):

- B-09 (closed): git repo initialized; nothing committed (not requested).
  Still true; tracked as hygiene, not a blocker. Commit only on explicit
  request.
- Orchestrator `--strict`/`--output-dir`/`--live` failure (Step-J):
  flags implemented, misuse exits 2, regression tests added.
- Manifest `attack_id` vs `attack_type` mismatch: migrated to v2,
  old name rejected, migration documented.
- Stale report snapshots (99 vs 101 counts, scaffold FAIL, split units):
  evidence regenerated from single runs; GiB unified; counts current.
