# R1–R10 policy reference

Authoritative implementation: `app/pipeline/policy.py`. Thresholds:
`policy/rules.toml` (version recorded on every verdict).

| Rule | Check | Failure |
|---|---|---|
| R1 | Vendor resolves by exact normalized name (active) | DENY |
| R2 | Bank fingerprint matches active vendor fingerprint | DENY |
| R3 | Exact Decimal arithmetic reconciles | DENY |
| R4 | Duplicate key unseen | DENY |
| R5 | Within cap and PO authorization | ESCALATE |
| R6 | Due date on/after issue, within max days | ESCALATE |
| R7 | Optional-evidence conflicts (SAM count, voice) | ESCALATE |
| R8 | Required fields present and schema-valid | DENY |
| R9 | Required verifiers executed without error | DENY |
| R10 | No vendor ambiguity (>1 plausible vendor) | ESCALATE |

Precedence: R9 failure → DENY; any R1/R2/R3/R4/R8 failure → DENY;
any R5/R6/R7/R10 failure → ESCALATE; else ALLOW_PROPOSAL.

## Interpretations (fixed for policy v2.0.0)

1. **R1 vs R10.** R1 passes only on an exact normalized match. R10 fires
   when more than one registry vendor is within 2 edits of the extracted
   name — including the branch-steering case where the invoice names one
   of two lookalikes exactly. A single fuzzy candidate never resolves
   (R1 DENY): fuzzy matching is not approval.
2. **R2 requires a reference.** A missing bank reference fails R8, not R2.
   Raw references are transient; only HMAC fingerprints are compared and
   stored.
3. **R5 covers PO problems.** Unknown, closed, currency-mismatched, or
   exceeded POs escalate (reviewable), they do not deny.
   `remaining_amount` is administrative registry state: Phase 2 checks
   each invoice against it but never auto-decrements it on proposal or
   payment, so N invoices each under the remaining balance all pass R5
   and concurrent submissions against one PO are not serialized. A
   reserve/release/consume PO ledger is a Phase 3 dependency (see
   LIMITATIONS.md).
4. **R7 covers optional-evidence conflicts.** SAM count mismatch is the
   primary check; a voice-vs-invoice conflict also escalates here.
   Absent optional evidence passes (NOT_PROVIDED, honest).
5. **R9 scope.** Required = bank verifier (always) + SAM when a delivery
   artifact is present with a resolvable catalogue label. Voice/ASR
   failure is recorded but never fatal (optional corroboration).
6. **ALLOW_PROPOSAL authorizes nothing.** It permits proposal creation;
   owner approval + challenge + PIN are still required for mock execution.
7. **Currency precision is single and global.** `currency_precision`
   (default 2) is enforced uniformly: money is exact `Decimal`
   throughout, line sums and subtotal+tax must reconcile exactly after
   quantization, and amounts that cannot quantize (e.g. 3-decimal minor
   units under precision 2) fail R3 rather than rounding. There is no
   per-currency minor-unit table in Phase 2; multi-currency deployments
   must add one (Phase 3). Discounts, surcharges, and other
   non-(subtotal, tax, total) adjustments are not modeled: the
   extraction schema rejects unknown fields instead of silently
   ignoring them.
