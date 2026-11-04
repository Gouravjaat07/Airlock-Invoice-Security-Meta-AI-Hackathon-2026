# Policy configuration

`rules.toml` holds the versioned thresholds for the deterministic R1–R10
policy engine. Rule identifiers and their DENY/ESCALATE meanings are fixed
in `app/pipeline/policy.py` and cannot be changed from this file.

- `meta.version` is recorded on every verdict.
- `rules.per_invoice_cap_default` applies when a vendor has no specific cap.
- `rules.currency_precision` is the enforced decimal scale for money.
- `rules.due_date_max_days` bounds R6 (default 120).
- `rules.sam_count_min/max` bound the accepted SAM count range.
- `rules.catalogue_tolerance_default` applies when a catalogue item has none.
- `rules.bank_change_cooldown_hours` gates bank-change activation.

Changing thresholds requires re-running the policy test suite; changing
rule semantics requires a version bump plus an ADR entry.
