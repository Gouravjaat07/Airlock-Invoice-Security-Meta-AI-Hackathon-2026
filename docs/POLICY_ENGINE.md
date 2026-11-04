# Airlock Policy Engine (R1–R10)

Authoritative code: `app/pipeline/policy.py`, `app/pipeline/corroborate.py`.
Rule record: [phase2/POLICY.md](phase2/POLICY.md). Tests:
`tests/unit/test_policy_rules.py` (26), `test_r7_extraction_failed.py` (5),
phase3 eval (every rule fires ≥ once).

## Rules

| ID | Question | Fail → | Key reason codes |
|---|---|---|---|
| R1 | Vendor resolves (exact, active)? | DENY | vendor-resolved / vendor-unresolved |
| R2 | Bank fingerprint matches active record? | DENY | bank-match / bank-mismatch / bank-not-provided (→R8) / bank-unverifiable |
| R3 | Exact Decimal arithmetic (lines→subtotal, +tax→total)? | DENY | arithmetic-exact / arithmetic-mismatch |
| R4 | Duplicate composite key unseen? | DENY | not-duplicate / duplicate / duplicate-unverifiable |
| R5 | Within cap and PO authorized (found/open/currency/balance)? | ESCALATE | within-cap / over-cap / po-violation / cap-unverifiable |
| R6 | Due date plausible (≥ issue, ≤120 d)? | ESCALATE | dates-plausible / due-before-issue / due-too-far |
| R7 | Optional-evidence conflicts (SAM count, voice)? | ESCALATE | sam-count-conflict / voice-conflict / evidence-consistent / evidence-not-evaluated |
| R8 | Schema-valid with required fields (bank ref)? | DENY | fields-present / schema-invalid / missing-extraction / missing-bank-reference |
| R9 | Required verifiers ran without error? | DENY | verifiers-ok / verifier-error |
| R10 | Vendor unambiguous (no ≤2-edit lookalike)? | ESCALATE | vendor-unambiguous / vendor-ambiguous |

## Precedence (fixed, in `aggregate`)

Required-verifier (R9) failure → DENY. Then R1/R2/R3/R4/R8 → DENY.
Then R5/R6/R7/R10 → ESCALATE. Else ALLOW_PROPOSAL. All ten rules
always evaluate; every result carries rule version, reason code,
message, evidence, and timestamp.

## Semantics worth knowing

- R2 vs R8: no bank reference extracted → R2 passes
  (`bank-not-provided`) and R8 denies (`missing-bank-reference`).
- R4 keys `vendor_id | normalized_number | total | issue_date`;
  normalization folds homoglyph/case/spacing games.
- R7 passes with `evidence-not-evaluated` when optional bytes were
  uploaded but a comparison could not run — explicit, never silent.
  Voice conflicts escalate even without delivery evidence (the `sam`
  outcome always exists, so the voice check is never skipped).
- R9 denies on bank-key-missing and required SAM errors; optional
  voice failures are recorded, never fatal.
- R10 fires even when R1 resolved exactly: an exact match plus a
  lookalike must not auto-approve.
- Thresholds only live in `policy/rules.toml`; rule on/off switches
  do not exist by design.

## Reproducibility

Same extraction + same registries + same policy version → same
verdict, always. No model calls, no clock dependence except
`evaluated_at` stamps, no randomness. The phase3 eval replays all 19
scenarios deterministically (19/19 matched, 2026-11-04).
