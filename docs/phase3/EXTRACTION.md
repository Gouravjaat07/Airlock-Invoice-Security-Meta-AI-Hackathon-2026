# Phase 3 — Invoice extraction guide

Model extraction (`muse-spark-1.3` primary; Spark Open / Glimmer
alternates for images) produces T2 candidates for the existing
pipeline. It never approves, computes, or overrides.

## Flow

1. Existing intake validates the artifact (size, type, page/pixel
   caps); the SHA-256 is recorded.
2. The reader sends the bytes inline (PDF → `input_file` file_data;
   image → `input_image` data URL) with versioned instructions
   (`airlock-extraction/5`) and a schema-constrained JSON shape
   (`airlock-extraction-schema/1`, `text.format` on Responses with
   `strict: false`, `response_format` on chat endpoints also
   non-strict). `strict: true` would require the strict subset
   (every key in `required`, no free-form maps), which the dynamic
   `evidence.pages` map cannot satisfy — the provider would 400
   every request — while `strict: false` still constrains decoding
   to the schema. `store:false` everywhere. Local Pydantic
   validation is authoritative either way.
3. The finalizer parses strict JSON, allowlists to the
   `InvoiceExtraction` field set (extras dropped + warned), normalizes
   unambiguous amount notations and currency values (`usd` → `USD`,
   unambiguous names/symbols only; `$` alone stays ambiguous), and
   grounds `evidence.pages` against the real page count (bad anchors
   dropped, values kept as candidates). Unusable output → `E_SCHEMA`
   → R8 DENY.
4. Local `validate_extraction` re-parses everything (Decimal via
   `parse_money`, ISO dates, currency codes via the same deterministic
   rule with actionable errors, enums, lengths); then R1–R10 decide.
   Discounts/surcharges/credits/multi-tax are NOT modeled: unknown
   fields are stripped, so affected invoices fail arithmetic (R3) or
   schema (R8) and route to DENY/ESCALATE per existing semantics.

## Numbers

The model copies printed characters (`"1.240,00"`, `"Rs. 5,000"`).
`numbers.py` converts unambiguous notations (both-separator,
validated grouping incl. Indian 3-2-2, parenthesized negatives,
currency marks) to canonical decimals. Single-separator 3-digit
fractions (`"1,234"`) and malformed groupings are AMBIGUOUS: the
field is dropped → R8 DENY. Never rounded, never guessed; R3 still
requires exact reconciliation. No per-currency minor-unit table
(same limitation as Phase 2).

## Evidence

Per-field page anchors are verified (1..page_count; images cite
page 1); unverifiable anchors are dropped with warnings. A model
quotation is not proof — values still pass registry (R1/R2),
arithmetic (R3), and duplicate (R4) checks. Provenance per fact:
adapter, adapter_version, model_id, prompt_version, request_id,
extracted_at. Audit `reader.completed` carries model, request id,
usage (tokens where returned, duration, attempts), and warnings.

## Multi-source conflicts

No deterministic parser exists yet to conflict with; when one is
added, both candidates must be preserved and escalated per
`POLICY.md` (never averaged, never auto-preferring the model).
Conflicting required fields today surface through R8/R3 DENY.
