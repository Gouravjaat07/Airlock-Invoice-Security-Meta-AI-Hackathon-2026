# Blind Reviewer Simulation

Date: 2026-11-04. Four independent passes over the finished submission.
Each finding carries severity (Critical/High/Medium/Low) and disposition:
FIXED (changed + verified this mission), ACCEPTED (judged correct as-is),
or OWNER (needs the owner: credentials, deployment, or legal decision).
No invented scores.

## Reviewer A — Product / Impact

- A1. Problem important, user identifiable? YES. Owner-operated AP
  fraud (bank substitution, duplicates, PO mismatch) is concrete and
  evidenced in `docs/PRODUCT_IMPACT.md`. No finding.
- A2. Genuine difference from OCR? YES. Evidence-grounded pipeline
  (untrusted extraction → deterministic policy → owner authority) is
  demonstrated in code, not claimed in prose. No finding.
- A3. Value measurable? PARTIAL (Medium, OWNER). Pilot metrics are
  proposed with assumptions, but no field measurement exists — and
  none honestly could at this stage. Not fixable in-repo; the docs
  refuse to invent numbers, which is the correct behavior.
- A4. Unsupported adoption/revenue claims? NONE FOUND (verified by
  reading README + PRODUCT_IMPACT: zero customer/revenue/savings
  claims). No finding.

Disposition: no fixable findings. A3 stays open as future pilot work.

## Reviewer B — Meta AI specialist

- B1. Models genuinely used? YES. Spark extraction drives facts;
  voice transcripts drive R7 comparison; SAM counts drive R7
  comparison. Each output is consumed downstream (traced in
  `process.py` → `corroborate.py` → `policy.py`). No finding.
- B2. Each model necessary? YES with one caveat (Low, ACCEPTED):
  voice/SAM are optional lanes by design; invoice-only cases still
  verify. Optionality is explicit, never hidden.
- B3. Provenance visible? YES. Adapter/model/prompt/request/usage in
  facts + audit + UI (`evidence.ts`). No finding.
- B4. Failures handled safely? YES. EMPTY/FAILED/NOT_EVALUATED lanes,
  R7 explicit reason codes, no silent fallback (registry tests).
  No finding.
- B5. More than an API wrapper? YES. Schema-constrained prompts v5,
  extraction finalizer (allowlist/alias/evidence rules), deterministic
  comparison layer, breaker/resilience envelope. No finding.
- B6. Live model quality proven? NO (High, OWNER). All live layers
  are NOT_TESTED — contract tests against mocks only. Fixing requires
  billable calls the mission forbids; metric code + opt-in commands
  are ready (`phase5_eval.py --live`, `media_metrics.py`).

Disposition: B6 is the one High; it is owner-actionable only and is
documented in the benchmark report, release readiness, and runbook.

## Reviewer C — Senior engineer / security

- C1. Correctness of R1–R10? YES. Read in full; R7 voice-without-SAM
  path traced safe (`sam` outcome always present). No finding.
- C2. Trust boundaries enforced? YES. T0/T2, no model write path to
  registries, mock-only payments (verified + tested). No finding.
- C3. Determinism where required? YES. Policy, corroboration,
  currency, dup keys, hashes all deterministic; eval replays 19/19.
  No finding.
- C4. Fails safely? YES, with fixes made: nosniff middleware added
  (Medium, FIXED + 3 tests); WAV magic validation added (Low, FIXED);
  SQL guard test added (Low, FIXED); glimmer READY wording fixed
  (Low, FIXED); verify-script exit-code bug fixed (High, FIXED —
  it reported ALL GATES PASSED while a gate failed).
- C5. Concurrency/DB/audit understood? YES. Semaphore(2), busy
  timeout, optimistic versioning, race guards, append-only triggers
  + hash chain; admin-rewrite limitation documented. Migrations
  001–003 read in full this pass (FKs, UNIQUEs, AUTOINCREMENT audit
  ids, fail-closed challenge migration). No finding.
- C6. Maintainable? YES. Typed boundaries, versioned prompts/schemas,
  additive audit vocabulary, AGENTS.md. CI now gates app + web
  (Medium, FIXED — was Phase-1-only with unpinned actions; SHA
  pinning left as OWNER procedure, TLS unavailable here).
- C7. Dependency risk? PARTIAL (Medium, ACCEPTED + OWNER). npm prod
  0 vulns; dev-only vitest/tinypool criticals accepted with rationale;
  `pip-audit` blocked by sandbox network (OWNER re-run documented).

Disposition: all fixable Critical/High items fixed (C4 verify-script
bug was the only High). C6-SHA and C7-pip-audit need owner network.

## Reviewer D — Demo / independent evaluator

- D1. Runnable from clean clone? YES. Evaluator guide commands all
  executed from this tree during the mission (suite, ruff, evals,
  frontend gates). Fixture basetemp naming trap documented. No finding.
- D2. Instructions precise? YES, with fixes made: README rewritten
  (was stale Phase-1 text; High, FIXED); demo artifact filenames +
  per-scenario rules verified against eval output (Medium, FIXED —
  two multi-rule cascades corrected in the table).
- D3. Tests pass without live credentials? YES. 950 passed, 1
  skipped, 2 sandbox-blocked (socket denial, unrelated to code).
  No finding.
- D4. Clean scenario works / rejection rejects? YES at HTTP level:
  W01 clean→ALLOW→mock→audit-ok; W02 R2 DENY; W03–W16 cover the
  matrix (all green). No finding.
- D5. Screenshots/metrics backed by evidence? YES for metrics
  (dated snapshot JSON, regenerable commands); no screenshots
  included, none fabricated (Low, ACCEPTED — UI shots are
  owner-taken during the live demo).
- D6. Value clear in one minute? YES. README answers what/problem/
  innovation/models/run-first in the first screen. No finding.
- D7. Release hygiene? YES with owner steps: LICENSE missing
  (High, OWNER — legal choice), no remote yet (OWNER), e2e/pip-audit
  need outside-sandbox runs (OWNER). Nothing pushed without approval.

Disposition: D2 fixes applied. D7 items are owner decisions, all
listed in `docs/RELEASE_READINESS.md` with exact commands.

## Remediation summary

Fixed this pass: verify-script exit-code detection (High), README
staleness (High), CI coverage (Medium), demo-table accuracy (Medium),
nosniff (Medium), WAV magic + SQL guard + glimmer wording (Low).
Closed verification gaps: migrations 001–003 bodies, W01–W16 HTTP
proofs. Remaining Highs (live model quality, LICENSE, SHA pins,
outside-sandbox confirmations) all require owner action and are
tracked with commands, not just words.
