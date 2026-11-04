# Evaluation (Phase 2)

Scenarios live in `fixtures/scenarios/*.json`, generated deterministically
by `scripts/make_fixtures.py` (`--check` detects drift). Scenario files
reuse the Phase 1 manifest v2 vocabulary — `attack_type` (A01–A16,
canonical; v1 `attack_id` is rejected) and `expected_verdict`
(`ALLOW_PROPOSAL`/`ESCALATE`/`DENY`) — without a competing schema.

## Scenario → attack coverage

| Scenario | attack_type | Expected | Rules |
|---|---|---|---|
| clean | — | ALLOW_PROPOSAL | — |
| changed-bank | A08 | DENY | R2 |
| arithmetic-mismatch | — | DENY | R3 |
| over-cap | A09 | ESCALATE | R5 |
| invalid-due | — | ESCALATE | R6 |
| ambiguous-vendor | A14 | ESCALATE | R10 |
| lookalike-vendor | A10 | DENY | R1 |
| sam-conflict | A12 | ESCALATE | R7 |
| sam-ok | — | ALLOW_PROPOSAL | — |
| missing-field | — | DENY | R8 |
| malformed-reader | — | DENY | R8 |
| injection-visible | A01 | ALLOW_PROPOSAL | (inert) |
| hidden-text | A03 | ALLOW_PROPOSAL | (repr.) |
| voice-instruction | A06 | ESCALATE | R7 |
| planner-injection | A15 | ALLOW_PROPOSAL | (boundary) |
| verifier-timeout | — | DENY | R9 |
| po-exceeded | — | ESCALATE | R5 |
| duplicate | A11 | DENY | R4 (after clean) |
| reader-timeout | — | ERROR | (no verdict) |

A02/A04/A05/A07/A13/A16 have no dedicated binary fixture: A02/A04/A05
share the hidden-instruction class with A03 (same handling: untrusted
data, no authority); A07 shares the limited-evidence class with A12;
A13 is the voice-conflict path exercised by `voice-instruction`;
A16 (adaptive) is out of scope for deterministic fixtures by definition.
This mapping is asserted by `tests/adversarial/test_injection.py`.

Run: `POST /api/v1/evaluation/run` (dev-only flag) or the eval tests.
Order matters for `duplicate` (it must run after `clean` in one DB).
