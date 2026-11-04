# Phase 2 — Deterministic Secure Backend

This directory holds Phase 2 design and verification notes. The normative
Phase 1 record is unchanged under `docs/phase1/`.

- [API.md](API.md) — endpoint contracts, auth, errors, idempotency.
- [DATABASE.md](DATABASE.md) — schema, migrations, transactions, limits.
- [POLICY.md](POLICY.md) — R1–R10 definitions, interpretations, precedence.
- [AUTH.md](AUTH.md) — PIN, sessions, challenges, CSRF, rate limits.
- [AUDIT.md](AUDIT.md) — hash chain design and its honest limitations.
- [ADAPTERS.md](ADAPTERS.md) — fixture reader, mock SAM/ASR, explainer, mock pay.
- [MIGRATION.md](MIGRATION.md) — future PostgreSQL/object-storage/queue path.
- [LIMITATIONS.md](LIMITATIONS.md) — what Phase 2 is not (read before deploy).
- [EVALUATION.md](EVALUATION.md) — scenarios, A01–A16 mapping, eval API.
