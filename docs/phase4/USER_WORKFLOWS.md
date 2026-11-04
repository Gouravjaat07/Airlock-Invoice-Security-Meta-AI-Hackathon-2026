# Phase 4 — User Workflows

All flows use synthetic fixtures in tests; the console never fabricates data.

## Login → overview

PIN → cookie session → dashboard KPIs (all from `/dashboard/summary`) +
recent cases. Refresh restores via `/auth/me`; CSRF rotates lazily on first
rejection. Logout revokes server-side and clears everything client-side.

## Intake → processing

New case: invoice PDF/image (required) + delivery photo/MP4 + WAV voice note
(optional). Client pre-checks mirror server defaults; the server re-validates.
One idempotency key per attempt series makes retries safe. Success navigates
to the case; processing starts from the case page (single long request with
“Stop waiting”, which cancels the wait — never the server job).
With the fixture reader, uploads must be registered fixture bytes; see
FIXTURE_WORKFLOW.md for the supported UI workflow and dev-only registration.

## Review → policy → evidence

Case tabs: Overview (facts with taint/validation/producer, proposal link),
Policy (exact verdict + R1–R10 table + server explanation), Evidence (blob
previews + voice/SAM verification metadata from audit events), Payments
(mock table), Audit (case timeline). Owner actions: reject (NEEDS_REVIEW /
PROPOSED), field correction (typed, audited, server re-runs policy).

## Approval → mock execution

Proposal review shows exact backend values. Eligible ⇔ PENDING + bound to the
current ALLOW verdict. Start approval → challenge (expiry shown) → explicit
checkbox + PIN → payment view with the MOCK label. Replay/expired/stale
challenges surface the server error with a path forward (new challenge).

## Audit and providers

Audit page: global newest-first trail + “Verify chain” (tamper-evident
result, honestly caveated). Providers page: per-task configured status —
ready means selectable, never live-verified; rendering it makes no paid calls.
