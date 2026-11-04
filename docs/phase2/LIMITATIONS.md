# Limitations — read before any deployment talk (Phase 2)

Verified: deterministic offline prototype behavior on synthetic data
within the test scope (see `results/phase2/`). NOT verified / NOT built:

- **No live model integration.** Reader, SAM, ASR, and planner are
  deterministic doubles. Fixture verdicts are software tests, not
  measurements of real-world model robustness. No claim is made about
  defeating adaptive multimodal attacks.
- **No real payments** (by design) — and no PCI/fraud/treasury controls.
- **Single owner, single PIN.** No multi-user identity, roles, MFA,
  recovery, or account lifecycle. PIN entropy is the owner's job.
- **Local secrets.** `.env` file + OS file permissions; no KMS/HSM,
  no rotation automation (bank-key rotation invalidates stored
  fingerprints — see code comments).
- **Local SQLite + blobs.** Single writer, no replication, no PITR,
  manual backups only. Audit chain is tamper-evident, not tamper-proof.
- **No malware scanning** of uploads; no PDF active-content sandbox
  (parsers are bounded but not sandboxed); image/audio/video parsing is
  header-level, not full decode.
- **No production hardening**: no TLS termination, WAF, structured
  backup/DR, metrics/alerting, abuse pipelines, data-retention
  enforcement, or formal security/privacy/regulatory review.

Production also needs: threat modeling of the real reader, red-team
evaluation on non-synthetic documents, key-management design, tenant
isolation, incident response, and compliance review. None of that is
claimed here.

- **Public intake endpoints (deliberate, local-only).** `POST/GET
  /cases`, `POST /cases/{id}/process`, and `GET /vendors*` require no
  authentication (see API.md): anyone who can reach the loopback server
  can submit invoices and read case summaries, facts, and vendor
  fingerprints (HMAC digests, not reversible without the bank key).
  Safe only because Phase 2 binds to 127.0.0.1 with synthetic data;
  any network exposure needs authentication on every route first.
- **No PO consumption ledger.** `remaining_amount` is checked per
  invoice but never decremented, so repeated or concurrent invoices
  against one PO are each evaluated against the same balance (see
  POLICY.md interpretation 3). A reserve/release/consume lifecycle is
  a Phase 3 dependency.
- **Global login lockout.** Failed-PIN lockout is a single global
  bucket (no trusted proxy exists to key per-client buckets), so a
  local attacker can trigger a 15-minute owner lockout. Per-account
  buckets plus trusted-proxy configuration are deployment work.
- **Single global currency precision.** No per-currency minor-unit
  table; amounts that cannot quantize to `currency_precision` fail R3
  (see POLICY.md interpretation 7).
- **Header-level media parsing.** Pixel/duration caps are enforced
  from PNG/JPEG headers and MP4 mvhd; unparseable headers are accepted
  (fail-open) with the upload size cap as the remaining bound, and no
  full decode, malware scan, or PDF active-content sandbox exists.
