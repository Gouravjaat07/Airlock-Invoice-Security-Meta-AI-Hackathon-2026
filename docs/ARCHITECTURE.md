# Airlock Architecture (current)

Single-owner invoice verification and payment-control pipeline.
Entry points: `app/main.py:create_app()` (API), `app/cli.py` (ops),
`web/` (owner console). Authoritative detail:
[decisions](ARCHITECTURE_DECISIONS.md),
[trust boundaries](architecture/TRUST_BOUNDARIES.md),
[provider architecture](architecture/PROVIDER_ARCHITECTURE.md),
[API](phase2/API.md), [database](phase2/DATABASE.md),
[frontend](phase4/FRONTEND_ARCHITECTURE.md).

## Data flow

```
upload (validated, hashed, deduped) → blob store + artifact rows
  → reader (registry-selected, fail-closed) → strict validation (T2 facts)
  → vendor resolve → SAM lane ∥ voice lane → corroboration
  → R1–R10 policy → ALLOW_PROPOSAL | ESCALATE | DENY
  → proposal (canonical hash) → owner challenge+PIN confirm
  → MOCK execution → hash-chained audit throughout
```

Full flow: [DATA_FLOW.md](DATA_FLOW.md). Privacy: [phase1](phase1/DATA_FLOW_AND_PRIVACY.md).

## Layers and boundaries

- `app/api/` — thin routes, auth deps, error envelope. No business logic.
- `app/pipeline/` — ingest, reader select, validate, registry resolve,
  lanes, corroboration, policy, proposals, state machine. No model I/O
  except through adapters.
- `app/providers/` — Meta/Baseten/Glimmer clients, prompts v5, currency
  v5, resilience (timeout/retry/breaker). No trusted writes.
- `app/adapters/` — fixture/mock readers, explainer templates, mock pay.
- `app/domain/` — enums, facts/provenance, vendors, POs, proposals,
  taint classes (T0 owner → T3 raw).
- `app/services/` — case/approval/proposal/vendor/audit orchestration.
- `app/storage/` — SQLite (WAL, migrations, repos) + blob store.
- `app/auth/` — PIN (Argon2id), sessions, challenges, rate limits.
- `app/evaluation/` — scenario fixtures, verdict eval, media metrics.
- `web/` — console; backend authoritative for all state.

Models write T2 facts; deterministic verifiers and the owner decide.
Policy rules are fixed in code; `policy/rules.toml` carries thresholds
only. See [POLICY_ENGINE.md](POLICY_ENGINE.md).

## Runtime characteristics

Sync FastAPI (no background queue claimed); ≤2 concurrent cases
(`BoundedSemaphore`); per-request SQLite connections; 5 s busy
timeout; idempotent reprocess with optimistic versioning;
duplicate-key race guarded at proposal time. Limits: single node,
single owner, mock payments. PostgreSQL migration stays a documented
future boundary, not a rewrite.
