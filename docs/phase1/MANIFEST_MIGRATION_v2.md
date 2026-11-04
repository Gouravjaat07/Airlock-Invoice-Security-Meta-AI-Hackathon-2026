# Manifest contract migration v1 → v2 (Phase 1 forensic audit)

Date: 2026-10-30.

## Decision

Canonical case field is **`attack_type`** (contract v2.0.0).
The v1 name `attack_id` is rejected, never silently accepted.

## Why

The governing Phase 1 contract names `attack_type` as the canonical field
(release gate D), while the generated schema, template, validator, and tests
used `attack_id`. Two names for one concept is an ambiguous contract: a
producer writing one name and a consumer reading the other silently drops
attack labels. The migration aligns every artifact on the governing name.

## What changed

| Artifact | v1 | v2 |
|---|---|---|
| `eval/manifest.schema.json` | `attack_id` | `attack_type` (+ `$comment` version note) |
| `eval/manifest.dev.template.json` | `manifest_version 1.0.0`, `attack_id` | `manifest_version 2.0.0`, `attack_type` |
| `scripts/validate_manifest.py` | `ATTACK_ID_RE`, `attack_id` | `ATTACK_TYPE_RE`, `attack_type`, fullmatch parity |
| `tests/test_manifest_schema.py` | v1 names | v2 names + `test_legacy_attack_id_field_rejected` |
| `prereg/PREREGISTRATION.md` | contract v1.0.0 | contract v2.0.0 |

Unchanged: the A01–A16 catalogue values, all enums, required sets,
`additionalProperties: false`, and the canonical hash formula.

## Compatibility

There is no compatibility shim. A v1 manifest fails with
`unknown property: attack_id`. This is deliberate: a shim would recreate
the two-name ambiguity. No v1 dataset exists (only the dev template, which
was migrated), so nothing is stranded.

## Verification

```powershell
python scripts\validate_manifest.py eval\manifest.dev.template.json
python -m pytest tests/test_manifest_schema.py -q
```

The template validates with a placeholder-hash warning; the regression
test proves a v1-shaped case is rejected.
