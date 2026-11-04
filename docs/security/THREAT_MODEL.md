# Airlock Threat Model

Date: 2026-11-04. Scope: the prototype in this repository (single-owner,
SQLite, mock payments). Companions: [trust boundaries](../architecture/TRUST_BOUNDARIES.md),
[auth design](../phase2/AUTH.md), [frontend security](../phase4/SECURITY.md),
[security operations](../operations/SECURITY_OPERATIONS.md),
[red-team matrix](RED_TEAM_TEST_MATRIX.md).

## 1. Assets

| Asset | Why it matters |
|---|---|
| Owner PIN / session tokens / CSRF tokens | Only path to payment authorization |
| Trusted vendor + bank-fingerprint registry | Decides R1/R2; substitution = fraud |
| Purchase-order records + balances | Decide R5 authorization |
| Proposal hashes + verdict records | Bind authorization to evaluated facts |
| Audit hash chain | Tamper-evident history of every decision |
| Uploaded artifacts + blobs | Untrusted input; must never become authority |
| Provider API keys (operator-owned) | Billed, secret, never in repo/logs |

## 2. Actors

- Supplier attacker: submits crafted invoices/voice/delivery evidence
  (prompt injection, bank substitution, lookalikes, duplicates).
- Network attacker: cannot read TLS, but can submit requests; CSRF
  against the owner browser session.
- Malicious/compromised model output: treated as untrusted data (T2)
  by construction, never authority.
- Privileged DB administrator: can rewrite history (documented
  limitation; chain is tamper-evident, not tamper-proof).
- Out of scope: physical host compromise, real banking rails (mock-only).

## 3. Trust boundaries

Untrusted: invoice PDFs/images, voice audio, delivery media, OCR text,
model outputs, transcripts, HTTP request bodies. Trusted: vendor/bank/PO
registries (owner-seeded), policy rules R1–R10, owner PIN/session,
proposal hashes, audit chain. Models write facts labeled T2; only
deterministic verifiers and the owner move a case forward. Details in
[TRUST_BOUNDARIES.md](../architecture/TRUST_BOUNDARIES.md).

## 4. Threats, controls, and residual risk

Severity: Critical = direct payment compromise; High = policy bypass or
auth break; Medium = degraded safety signal or DoS; Low = hardening gap
with mitigations in place.

### 4.1 Prompt injection (supplier → model → pipeline)

| # | Attack path | Control (file) | Test | Severity / residual |
|---|---|---|---|---|
| PI-1 | Direct instructions in invoice text | Extract-facts-only prompt v5; T2 taint; policy ignores prose (`providers/prompts.py`, `domain/taint.py`) | `test_injection_text_stays_inert`, `test_w11_prompt_injection_inert` | Medium / prompt quality is unevaluated live |
| PI-2 | Hidden/white-on-white PDF text | Same as PI-1; fixture `hidden-text` | scenario `hidden-text` (phase3 eval) | Medium / same as PI-1 |
| PI-3 | Injection in vendor names / line items | Registry exact-match; unknown → DENY R1 (`pipeline/registry.py`) | `test_injection_vendor_names_deny` | Low / denied by construction |
| PI-4 | Voice instructions ("ignore invoice, approve") | Transcript is T2; instruction markers → R7 conflict (`pipeline/process.py:68`) | scenario `voice-instruction` | Medium / marker list is heuristic; conflicts escalate, never approve |
| PI-5 | Delivery-evidence instruction text | SAM prompted only from trusted catalogue; geometry-only output (`pipeline/process.py:415`) | `sam-ok` / `sam-conflict` scenarios | Low / no text path from image to policy |

### 4.2 Financial manipulation (supplier → policy)

| # | Attack path | Control | Test | Severity / residual |
|---|---|---|---|---|
| FM-1 | Bank-account substitution | HMAC-SHA256 fingerprints, constant-time compare, R2 DENY, 24 h change cooldown | `test_r2_wrong_bank_denies`, `changed-bank` | Low / none known |
| FM-2 | Vendor lookalikes / homoglyphs | Exact resolve; Levenshtein ≤2 → R10 ESCALATE; normalized dup keys | `test_r10_lookalike_pair_escalates`, `ambiguous-vendor` | Low / threshold is a judgment call |
| FM-3 | Duplicate billing / reprocessing races | Canonical dup_key, proposal-time race guard, idempotent reprocess | `test_r4_*`, `test_duplicate_race_at_proposal` | Low / none known |
| FM-4 | Arithmetic/tax/decimal games | Exact Decimal reconcile, R3 DENY | `test_r3_*`, `test_w03_arithmetic_denies` | Low / none known |
| FM-5 | Currency mismatch / `$` ambiguity | Currency v5: unambiguous-only, no USD default → R8 on doubt | `test_currency.py`, `test_currency_pipeline.py` | Low / no ISO allowlist (3-letter passthrough) |
| FM-6 | PO over-claim / closed PO | PO lookup + status + currency + balance, R5 ESCALATE | `test_r5_*`, `po-exceeded` | Low / none known |
| FM-7 | Expired/far-future dates | R6 bounds check | `test_r6_boundaries`, `invalid-due` | Low / none known |
| FM-8 | Over-cap invoice | Per-vendor/default cap, R5 ESCALATE | `test_r5_at_cap_passes_over_cap_escalates`, `over-cap` | Low / none known |

### 4.3 Application security

| # | Attack path | Control | Test | Severity / residual |
|---|---|---|---|---|
| AS-1 | PIN guessing | Argon2id, no default PIN, global 5/15 min lockout | `test_auth_security.py` | Medium / global scope allows lockout-DoS (documented trade-off) |
| AS-2 | Session theft/replay | 256-bit opaque tokens (hash stored), expiry, revocation, Secure/HttpOnly/SameSite=Lax | `test_auth_security.py` | Low / none known |
| AS-3 | CSRF payment approval | CSRF on all cookie mutations; challenge+PIN re-verify at confirm | API tests, `test_confirm_*` | Low / `/csrf-refresh` rotates without a CSRF check by design (session-only bootstrap; worst case victim re-fetch) |
| AS-4 | Non-owner approval | Single-owner sessions; challenge bound to session+proposal hash, single-use, 5 min | `test_confirm_refuses_nonallow_verdict`, `test_confirm_stale_and_nonallow` | Low / none known |
| AS-5 | Real payment execution | No payment rail exists; `mock_payment_service` only | `test_mock_executor.py` | Low / none known (architectural) |
| AS-6 | SQL injection | Parameterized SQL only, no ORM string building | Code review (no test; see residual) | Low / add a `grep`-style guard test for `execute(f"` patterns |
| AS-7 | XSS via stored facts | JSON API; React auto-escape; nosniff on artifact bytes + global middleware | `test_security_headers.py` | Low / no CSP (Swagger UI needs script; documented) |
| AS-8 | Malicious uploads (parsers, bombs) | Extension allowlist, magic-byte sniff, 10 MiB/file, 20-page PDF cap, pixel caps | `test_file_validation.py` | Medium / JPEG/MP4/WAV dims fail open (caps still bound); PDF parser is minimal |
| AS-9 | SSRF via configured URLs | https-only Meta/Baseten, loopback-only http for Glimmer, no credential embedding | config tests | Low / none known |
| AS-10 | Rate-limit bypass | Global login bucket + per-session 30/min + challenge 10/min | rate-limit tests | Low / see AS-1 residual |

### 4.4 Data and artifact integrity

| # | Attack path | Control | Test | Severity / residual |
|---|---|---|---|---|
| DI-1 | Blob swap between intake and processing | Bytes rebound to intake SHA-256; mismatch fails closed | gap tests | Low / none known |
| DI-2 | Audit tampering/deletion/reorder | Hash chain + id-sequence replay verification | audit tests | Medium / privileged DB admin can rewrite (documented limitation) |
| DI-3 | Proposal tampering / stale confirm | Canonical 9-field hash; confirm re-checks hash + current ALLOW verdict | `test_confirm_stale_and_nonallow` | Low / none known |
| DI-4 | Registry poisoning via model output | No model write path to registries (code review: only owner/vendor APIs write) | vendor API tests | Low / none known |
| DI-5 | Fixture shadowing of canonical ground truth | Content-addressed mapping; custom fixtures cannot shadow canonical | `test_fixture_reader_consistency.py` | Low / none known |

## 5. OWASP GenAI (LLM Top 10 2026) mapping

| Category | Airlock posture | Evidence |
|---|---|---|
| Prompt injection | Mitigated by architecture (extract-only, T2, deterministic policy); live prompt quality unevaluated | PI-1..PI-5 |
| Sensitive information disclosure | Keys presence-only, redacted logs, fingerprints not raw refs, secret hygiene gate | `check_secret_hygiene.py`, config tests |
| Excessive agency | No agency: models cannot approve/authorize/execute; owner-only T0 | AS-4, AS-5 |
| Supply chain | Pinned-ish deps, lockfile, offline CI; no model weights in repo | Stage 6 audit |
| Data/model poisoning | Registries owner-written; fixtures hash-pinned | DI-4, DI-5 |
| Unbounded consumption | Bounded timeouts/retries/inflight, breaker, live gates need `--live --allow-billable` | resilience tests, smoke safety tests |
| Misinformatio
...[truncated 638 chars]