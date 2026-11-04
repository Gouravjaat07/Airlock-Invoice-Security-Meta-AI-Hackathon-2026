# Security Policy

Airlock is a hackathon prototype for invoice verification and payment
control. It handles synthetic data only and executes mock payments only.

## Non-negotiable invariants

- Only the authenticated owner (T0) can authorize a payment proposal.
- Model outputs are untrusted data (T2): they never approve, authorize,
  or execute payments, and never write trusted registries.
- Payment execution is mock-only; no real payment rail exists.
- Policy R1–R10 is deterministic; provider selection is explicit and
  fail-closed with no silent fallback.
- Audit records are hash-chained and tamper-evident.

Details: [threat model](docs/security/THREAT_MODEL.md),
[red-team matrix](docs/security/RED_TEAM_TEST_MATRIX.md).

## Reporting a vulnerability

This repository has no hosted service and no bug-bounty program. If you
find a security issue in the code:

1. Do not open a public issue with exploit details or credentials.
2. Contact the repository owner privately with a description, affected
   file/route, and (if possible) a minimal synthetic reproduction.
3. Do not include real invoices, bank data, API keys, or personal data.

## Scope

In scope: `app/` (API, pipeline, policy, auth, providers), `scripts/`
audit tooling, `web/` console, CI workflows, and the security
documentation above.

Out of scope: live provider behavior billed to your own keys, the
operator's local machine, and any real financial institution.

## Safe testing rules

- Synthetic fixtures only (`fixtures/`); never real financial data.
- Never commit `.env` or any credential; CI runs fully offline.
- Live provider smokes are explicit opt-in
  (`--live --allow-billable`) and must never run from pytest or CI.
- Suspect an exposed key? Treat it as compromised and rotate it;
  do not "verify" by using it.

## Known limitations (accepted, documented)

- Audit chain is tamper-evident, not tamper-proof against a privileged
  DB administrator.
- Login lockout is global (lockout-DoS trade-off); see threat model R3.
- `POST /audit/verify` appends an event (verify mutates the chain).
- Live model quality (Spark/Voice/SAM) is contract-tested against mocks;
  live verification is a separate, explicitly authorized activity.
