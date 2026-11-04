# Integration status (Phase 1)

Legend: `USER_REPORTED_TESTED` = user says prior API-key testing completed;
`NOT_REPRODUCED_IN_THIS_WORKSPACE` = no local log evidence;
`NOT_TESTED` = no test conducted here. Prior testing is NOT repeated in
Phase 1 and is never auto-upgraded to verified.

## Muse Code (development tool only)

- Role: coding assistant for building Airlock. Not the runtime API.
- Session: user reports `muse-spark-1.3-contributor` in the CLI session.
- Status: `PASS` (presence verified) — `muse --version` reports
  Muse Code 1.4.14 via `...\AppData\Local\Programs\muse\muse.CMD`
  (the audit retries `.cmd` shims through the shell). Note: a second
  `muse` on PATH is a bash script (`#!/usr/bin/env bash`) unrunnable
  from PowerShell — that entry needs WSL/Git Bash.
- Evidence: `check_environment.py` muse_cli PASS, 2026-10-30.
- Next: none. Dev-tool presence confirmed; runtime API is separate (B-02).

## Muse Spark 1.3 (advisory planner, benchmark baseline)

- Role: explain policy decisions; Kill Test 1 hosted reference. No tools,
  no payment access, no override power.
- Model/base defaults: `muse-spark-1.3`, `https://api.meta.ai/v1`
  (OpenAI-compatible shape assumed; official doc not yet opened).
- Status: `USER_REPORTED_TESTED` + `NOT_REPRODUCED_IN_THIS_WORKSPACE`.
  `MODEL_API_KEY` is unset in this session; no status codes, model ids, or
  response logs exist locally.
- Next: set key → preflight → explicit opt-in live text test → (only then)
  structured-output test. Verify the 2M tok/min claim in the account.

## Muse Glimmer 30B (conditional local invoice reader)

- Role: on-device invoice reader if hardware-verified.
- Artifact: `meta-models/Muse-Glimmer-30B` (HF repo confirmed via
  Transformers docs); Apache 2.0 reported, primary licence unverified;
  NO official GGUF filename verified; NO weights staged.
- Status: `NOT_INTEGRATED`, hardware `LOCAL_GLIMMER_UNAVAILABLE` on this
  machine (no GPU detected by any probe, no runtime installed).
- Next: fallback is the plan (hosted/mock reader). Revisit only with new
  hardware + verified artifact identity + user-approved download.

## SAM 3.1 (conditional visual corroboration)

- Role: LIMITED count evidence ("N visible instances of <label>").
  Never authenticity, quality, account, or approval judgments.
- Route: hosted via Meta Model API (tutorial-reported; official
  `dev.meta.ai/docs/sam/*` pages not yet opened). One phrase per request.
- Status: `NOT_TESTED` — schema unverified; `smoke_sam.py` refuses live.
- Next: open official SAM docs → implement verified payload builder →
  synthetic image fixture → opt-in live test. Needs `meta-sam-parser`
  (reported) for mask decoding.

## Muse Voice Transcribe (optional transcription)

- Role: transcribe optional supplier voice notes. Untrusted data; never
  authentication or identity.
- Status: `NOT_TESTED` — endpoint/format unknown, no source located;
  `smoke_voice.py` refuses live. No fixtures exist.
- Next: locate official doc → synthetic fixture in exact format → opt-in
  test. Omit from demo if unresolved.

## Muse Spark Open via Baseten (optional hosted comparison)

- Role: optional hosted comparison/experiment, e.g. Kill Test 1 reference.
- Defaults: `https://inference.baseten.co/v1`,
  `meta-models/muse-spark-open` (dossier values; deployment unverified).
  $100 credit + 2M tok/min are user-reported, not account-verified.
- Status: `USER_REPORTED_TESTED` (prior key testing) +
  `NOT_REPRODUCED_IN_THIS_WORKSPACE`. No load tests in Phase 1.
- Next: confirm deployment id/readiness/limits in account → single minimal
  opt-in request. Never spend significant credit on exploration.

## Muse Image (optional synthetic fixture generation)

- Role: generate synthetic invoice/delivery fixtures if needed.
- Status: `NOT_TESTED`; necessity undecided. Fixtures can be built
  programmatically instead.
- Next: decide in Phase 2 fixture design; verify access only if chosen.

## Muse Wonder (not required)

- Role: none in the initial runtime.
- Status: `NOT_INTEGRATED`; no evaluation use identified.
- Next: revisit only with a concrete, costed evaluation reason.
