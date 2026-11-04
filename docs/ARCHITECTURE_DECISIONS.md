# Architecture decisions

Decisions are numbered (AD-##). Status: `accepted` (Phase 1) or `proposed`
(needs Phase 2 confirmation). Revisit a decision by appending, not rewriting.

## AD-01 — Phase 1 tooling is standard-library only (accepted)

No runtime dependencies: audits, validators, and smoke utilities run on any
Python ≥ 3.11 with zero installs and zero network. Rationale: bootstrap must
work before any environment exists; fewer supply-chain and version risks.
Consequence: manifest validation mirrors the JSON Schema by hand
(`validate_manifest.py`); both must be updated together.

## AD-02 — Intended application runtime is Python 3.11 (accepted)

The machine currently provides Python 3.13 (see ENVIRONMENT_REPORT.md).
Phase 1 tooling supports ≥ 3.11, but the Phase 2 app targets 3.11 for
ecosystem stability (inference runtimes, FastAPI). If 3.11 cannot be
installed, record the exception and re-target explicitly.

## AD-03 — Live model calls are double-gated and never default (accepted)

Every smoke utility is preflight-only unless passed BOTH `--live` and
`--confirm-external-call`. Pytest and `phase1_check.py` can never trigger
live mode (no flag path exists). Rationale: no accidental spend, no data
egress from routine checks.

## AD-04 — Process environment is the only credential source (accepted)

Keys come from environment variables (`MODEL_API_KEY`, `BASETEN_API_KEY`).
Scripts never load `.env` automatically, never print values, and validate
redacted configs. `.env` is git-ignored; `.env.example` stays trackable.

## AD-05 — Contributor model is dev-tooling only (accepted)

`muse-spark-1.3-contributor` must never be the runtime model: Contributor
content may be used for product improvement. `validate_config.py` errors on
it and `smoke_meta.py` refuses live calls with it.

## AD-06 — Evidence statuses distinguish report from proof (accepted)

`USER_REPORTED_TESTED` ≠ `PASS`. Only a local log-backed record
(`PASS`/`VERIFIED_FROM_LOG` via `record_smoke_result.py`) counts as
verification. One record per component/test; no combined success claims.

## AD-07 — SAM and Voice stay preflight-only until schemas verify (accepted)

`smoke_sam.py` / `smoke_voice.py` refuse to transmit while
`SCHEMA_VERIFIED = False`. Unblocking requires: official doc citation in
SOURCES.md, a payload builder for the verified contract, synthetic
fixtures, then an explicit live run.

## AD-08 — Local Glimmer decision is multi-factor (accepted)

`check_hardware.py` decides FEASIBLE / REQUIRES_EXPERIMENT / UNAVAILABLE
from GPU identity + known VRAM + runtime + disk + weights, never one number.
`AdapterRAM` 0/missing means unknown, not zero. `nvidia-smi` absence alone
proves nothing. Current verdict on this machine: UNAVAILABLE (see
HARDWARE_REPORT.md) → hosted/mock reader fallback per FALLBACK_DECISIONS.md.

## AD-09 — Benchmark manifests carry design, never results (accepted)

`eval/manifest.schema.json` (Draft 2020-12) + hand-mirrored validator;
template is a shape example with a placeholder hash. Results live in
git-ignored `results/` with manifest hash + seed + model ids.

## AD-10 — Future app shape: FastAPI core, React dashboard (proposed)

Deterministic core (registry, arithmetic, duplicates, proposal builder,
executor) in `app/`; dashboard in `web/`; SQLite + blob dir storage.
Trust classes T0–T3 and the evidence/authorization split are fixed now
(see DATA_FLOW_AND_PRIVACY.md); framework versions pin in Phase 2.

## AD-11 — Secrets are scanned heuristically, not proven absent (accepted)

`check_secret_hygiene.py` covers tracked + untracked project files and
pending diffs, plus `.env` ignore-rule checks. Pattern scanning catches
accidents; absence of findings is not proof of absence.

## AD-12 — No downloads without verified artifact identity (accepted)

Model weights download only after: exact repo, exact filenames, licence,
size vs free disk, hardware feasibility, and explicit user approval of the
estimated size. No unreviewed install scripts from model repos.

## AD-13 — Live gate flag is `--allow-billable`; orchestrator live is explicit (accepted)

Supersedes the flag name in AD-03 (double-gating itself is unchanged).
`--allow-billable` is the canonical confirmation flag;
`--confirm-external-call` remains as a deprecated alias. `phase1_check.py`
accepts `--live --allow-billable` and then runs the provider smokes as
subprocesses after printing a cost warning; partial flags exit 2, and
default mode never transmits. HTTPS is enforced except loopback test
endpoints. Rationale: one flag vocabulary across every tool, and a single
audited live entry point instead of per-script invocations.

## AD-14 — Manifest contract v2: `attack_type` is canonical (accepted)

Supersedes the v1 field name. Schema, template, validator, and tests use
`attack_type` (A01–A16 catalogue unchanged); v1 `attack_id` manifests are
rejected with unknown-property errors, never shimmed. The validator also
verifies `sha256` against the canonical hash. See
`docs/phase1/MANIFEST_MIGRATION_v2.md`.

## AD-15 — Evidence writes are atomic and carry provenance (accepted)

Every `--json` writer uses temp-file + fsync + replace (a crash never
leaves truncated JSON), and every report embeds a provenance envelope
(tool, version, argv, UTC timestamp, git commit, exit code). Reports from
different runs are therefore distinguishable instead of silently mixed.

## AD-16 — Phase 2 is a modular monolith (accepted)

One FastAPI service with strict module boundaries (api/services/pipeline/
domain/storage/adapters/auth). No queues, caches, or microservices: the
prototype's scale does not justify them, and every boundary documents its
future extraction path (see docs/phase2/MIGRATION.md).

## AD-17 — SQLite via stdlib sqlite3, versioned SQL migrations (accepted)

No ORM: explicit repositories, parameterized SQL, `BEGIN IMMEDIATE`
transactions, `schema_migrations` table. Rationale: fewer dependencies,
deterministic behavior, portable DDL for the later PostgreSQL move.
Single-writer limits are documented, not hidden.

## AD-18 — Deterministic doubles are the Phase 2 default (accepted)

Fixture reader, mock SAM/ASR, template explainer, mock executor. No live
provider calls exist; the suite proves it by blocking sockets. Live
adapters are a Phase 3 project behind the same interfaces, only after
opt-in smoke verification.

## AD-19 — The planner explains; it never decides (accepted)

Explainer input is verdict + rule results only. No raw documents, OCR
text, transcripts, credentials, or tools. Planner text cannot construct,
modify, or approve proposals, registry data, or policy.

## AD-20 — Voice is evidence, never identity (accepted)

Transcripts are tainted T2, length-bounded, and excluded from the
planner. Speech cannot authenticate, approve, or override registry,
arithmetic, or proposals. Conflicts escalate (R7).

## AD-21 — Mock-only execution with no provider abstraction (accepted)

Exactly one executor writes local MOCK records. No payment-provider
interface exists to misconfigure toward real rails, and none will be
added without a dedicated ADR plus treasury controls.

## AD-22 — Manifest v2 preserved; scenarios reuse its vocabulary (accepted)

`attack_type` (A01–A16) and `expected_verdict` remain canonical. Phase 2
scenario files reuse them; v1 `attack_id` is rejected, not shimmed. No
second benchmark schema was introduced.

## AD-23 — Unknown vendors deny; lookalike pairs escalate (accepted)

R1 passes only on exact normalized matches (fuzzy never approves).
R10 escalates when >1 vendor is within 2 edits of the extracted name,
including exact-to-one-of-two branch steering. Unknown/lookalike with
no exact match fails closed (R1 DENY).

## AD-24 — Async declarations, loop-free tests (accepted)

Route handlers and dependencies are `async def` with sync bodies so the
app runs identically under uvicorn and under a loop-free in-process
ASGI harness (this sandbox forbids `listen()`, which asyncio loop
creation needs on Windows). No `asyncio` primitives in app code; the
harness fails loudly if any appear. Socket-level serving must be
verified on an unsandboxed host before release claims.

## AD-25 — Phase 3 providers: explicit selection, sync I/O, no fallback (accepted)

Model inference joins via `app/providers/` behind the existing narrow
shapes (`Reader.read`, `transcribe`, `count`): one provider per task
from validated config, sync httpx clients (per AD-24), bounded
retries/breakers/semaphores, versioned prompts, and local revalidation
of every byte. Failures raise explicit errors — never silent reroutes
to fixtures or other models. Production rejects fixture/mock
providers at config load. Masks stay opaque (grammar-validated);
generative models stay out of the evidence path. Live verification is
double-gated per AD-03/AD-13 via `smoke_phase3.py` only.

## AD-26 — Blocking pipeline work offloads only when a loop runs (accepted)

Phase 3 added minutes-long synchronous model calls to the previously
local-only pipeline. The `process`/`edit` routes now run `run_case`
via `offload_sync`: under uvicorn (running loop) the work moves to a
worker thread so one slow provider cannot freeze unrelated requests;
under the loop-free ASGI harness (no running loop) the identical code
runs inline and no `asyncio` awaitable is touched, preserving AD-24.
Rationale: keeps sandbox tests socket/thread-free while fixing the
production event-loop block. Consequence: the thread hop itself is
only exercised on a real server; per-request sqlite connections use
`check_same_thread=False` sequentially, which the hop relies on.

## AD-27 — SAM masks decode with the official codec port (accepted)

Supersedes the "masks stay opaque" clause of AD-25. Mask rasters
decode with a line-by-line port of `@meta-sam/parser` 0.1.0
`mask-codec.js` (`app/providers/sam_mask.py`), chosen over adding the
alpha PyPI package to keep the security-critical path dependency-free
and reviewable. Rationale: a grammar check alone cannot distinguish a
real mask from well-formed garbage; undecodable masks are invalid
evidence. Consequence: per-mask (4M px) and per-lane (16M px) decode
budgets fail closed; only box geometry plus decoded pixel counts
persist — rasters never touch the database or audit log.

## AD-28 — Schema-constrained output without the strict subset (accepted)

Extraction requests send `strict: false` on both `text.format`
(Responses) and `response_format` (chat). Rationale: the documented
strict subset requires every property in `required` and no free-form
maps, which the dynamic evidence block cannot satisfy — `strict: true`
would make the provider reject every request with HTTP 400 — while
`strict: false` still constrains decoding to the schema. Consequence:
provider-side structure is a convenience only; local Pydantic
validation remains the authoritative enforcement.

## AD-29 — Integrity failures route by artifact role (accepted)

Phase 3.2 remediation. Every processing read rebinds blob bytes to
the recorded intake SHA-256. A mismatch on the invoice source
artifact fails the case (ERROR, retryable after re-intake) and the
bytes never reach any reader. A mismatch on delivery evidence
records a failed required-verifier result so R9 denies; corrupted
optional voice evidence is recorded and skipped. Rationale: storage
keys are artifact-addressed (replaceable), so the hash — not the
key — is the binding; routing follows the existing required /
optional verifier semantics instead of inventing a new verdict.
Reader selection failures (disabled, unconfigured, missing
credential, breaker open) surface as the pre-existing
E_READER_UNAVAILABLE, distinct from call-time transport failures
(E_API_UNAVAILABLE).

