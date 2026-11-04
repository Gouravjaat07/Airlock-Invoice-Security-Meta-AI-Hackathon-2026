# Airlock evaluation manifests

This directory holds the **benchmark manifest contract**. A manifest
describes a reproducible case set; it never contains measured results.

- `manifest.schema.json` — JSON Schema Draft 2020-12 contract (source of truth).
- `manifest.dev.template.json` — **template only**, showing the case shape.
  It is not an executed test set and contains no results.

## Validation

```powershell
python scripts\validate_manifest.py eval\manifest.dev.template.json
```

The validator (standard library only, no extra packages):

1. Parses the JSON file (malformed JSON fails).
2. Checks required top-level fields: `manifest_version`, `seed`, `split`,
   `generator_commit`, `cases`, `sha256`.
3. Checks enums: `split` ∈ {dev, test}, `variant` ∈
   {clean, attack, ambiguous, failure}, `expected_verdict` ∈
   {ALLOW_PROPOSAL, ESCALATE, DENY}.
4. Checks `attack_type` matches `A01`–`A16` or is null.
5. Rejects duplicate `case_id` values and duplicate artifact paths.
6. Rejects unsafe artifact paths (see below).
7. Rejects unknown properties (`additionalProperties: false`).
8. Verifies `sha256` against the canonical hash (see below).
9. Exits nonzero on any failure and never modifies the manifest.

The validator mirrors the schema field-for-field so it runs with zero
dependencies. Pattern/enum/required parity with the schema file is enforced
by an automated test (`test_validator_schema_pattern_parity`). If the schema
changes, update both together and extend
`tests/test_manifest_schema.py`. Contract history: v2.0.0 renamed
`attack_id` → `attack_type` (see
[MANIFEST_MIGRATION_v2.md](../docs/phase1/MANIFEST_MIGRATION_v2.md));
v1 manifests are rejected, never silently accepted.

## Safe artifact path rules

Every entry in `artifacts` must be a relative POSIX-style path that:

- is non-empty and uses `/` separators (no backslashes);
- does not start with `/` and contains no drive letter (`:`);
- contains no `..`, `.`, or empty segment (after percent-decoding);
- contains no null byte (raw or `%00`) and no percent-encoded
  separator (`%2F`, `%5C`) or traversal (`%2E`);
- stays inside the manifest's case directory tree.

Absolute paths, parent traversal (raw or percent-encoded, including
double-encoded forms), UNC paths, and URLs are rejected. The validator
never reads artifact files; existence is a generator concern.

## Canonical hash (`sha256`)

For a generated (non-template) manifest, `sha256` is the hex SHA-256 over
the canonical bytes:

```text
json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
```

The template uses the placeholder `template-placeholder-replaced-at-generation`.
The generator must replace it; the validator warns (does not fail) when the
placeholder is present so templates validate while real manifests carry hashes.
For any other value the validator requires 64 lowercase hex characters and
recomputes the canonical hash: a mismatch fails validation. Whitespace and
key order in the source file do not affect the hash (canonicalization
normalizes both); any meaningful field change invalidates the recorded hash.

## Splits and sizes (preregistered)

- dev: 40 base docs × (1 clean + 3 attack) = 160 cases.
- test: 60 clean + 180 attack + 20 ambiguous/failure = 260 cases.
- Kill Test 1 reader comparison: 40 synthetic invoices × 10 fields.

See [prereg/PREREGISTRATION.md](../prereg/PREREGISTRATION.md) for the full design.
