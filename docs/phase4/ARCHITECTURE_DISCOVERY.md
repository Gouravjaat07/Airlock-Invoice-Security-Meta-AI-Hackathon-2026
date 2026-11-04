# Phase 4 — Architecture Discovery

Date: 2026-11-01. Method: direct source inspection + OpenAPI route inventory.
No code was written before this document.

## 1. Frontend starting state

- `web/` contains **only `.gitkeep`**. No scaffold, no package.json, no UI.
- Decision: new React + TypeScript + Vite app (Node v22.18.0, npm 10.9.3,
  registry reachable). React Router for routes/guards, TanStack Query for
  server state (both justified: deep links + polling-free server cache with
  invalidation). Hand-rolled CSS design tokens (no Tailwind) to guarantee the
  mandatory white theme with zero build risk. No state lib beyond that; forms
  are controlled components with small validators.

## 2. Backend route inventory (all under `/api/v1`, envelope `{error:{...}}`)

Public (no session): `GET /health`, `POST /cases` (multipart intake),
`GET /cases` (paginated list), `GET /cases/{id}`, `POST /cases/{id}/process`,
`GET /vendors`, `GET /vendors/{id}`, `POST /auth/login`.
Owner session required: `/auth/me`, `/auth/logout`, case reject + fact edit,
proposals get/challenge/confirm, payments views, audit views, evaluation
(dev), `/providers`, vendor mutations.
Mutations needing CSRF (`X-CSRF-Token` header or body field, cookie flow):
reject, fact edit, challenge, confirm, evaluation run, vendor mutations.
Upload/process/logout need no CSRF token. No CORS middleware: same-origin only
(Vite dev proxy; production via reverse proxy — documented, no backend mount,
so API 404 JSON semantics are untouched).

## 3. Auth/session model (verified in `app/auth/sessions.py`)

- PIN login → HttpOnly `airlock_session` cookie (Secure/SameSite=Lax) +
  `{session_id, csrf_token, expires_at}` body. Token never in body/JS.
- `/auth/me` restores `{authenticated, session_id, expires_at}` but the raw
  CSRF token is hash-stored and unrecoverable → refresh loses mutation
  ability. Fix (new, minimal): `POST /auth/csrf-refresh` rotates and returns
  a fresh token (session-auth, no CSRF bootstrap needed — SOP protects it).
- Challenge id is a `ch_…` bearer, in-memory only, never stored/logged.
- Lockout: global login bucket 5/15min; per-session 30/min; challenge 10/min.

## 4. Response shapes (verified, not assumed)

- Case detail/intake/process/reject/edit → `_summary_view`: case, artifacts
  `{id,kind,media_type,size_bytes,sha256}` (kinds: `invoice|delivery|voice`),
  facts `{id,field,value,taint_class,validation_status,validated_by}`,
  raw `verdict` row (frontend JSON-parses `reasons_json`, `rule_ids_json`,
  `rule_details_json` → `[{rule_id,passed,reason_code,message,evidence}]`),
  raw proposal row or null, raw payment rows, `explanation` string|null.
- Fact fields: vendor_name, invoice_number, issue_date, due_date, currency,
  subtotal, tax, total, bank `{fingerprint,match}`, po_reference?,
  line_items `[{description,quantity,unit_price,catalogue_item_id,
  extracted_item_id}]`. Taint T0–T3; status CONFIRMED/CONFLICT/UNCONFIRMED/….
- States: case UPLOADED…EXECUTED/REJECTED/NEEDS_REVIEW/ERROR/…, proposal
  PENDING/CONFIRMED/EXPIRED/REJECTED, payment MOCK_COMPLETED/FAILED.
- `issue_challenge` → `{challenge_id, proposal_hash, expires_in_minutes,
  proposal}`. `confirm` → payment view `{payment_id,…,status,label,mock}`.
- Audit event: `{id,ts,case_id,event_type,actor_*,payload(prev_hash,
  event_hash}`; verify → `{ok,events,break_at?,reason?}`.
- Providers: 3 statuses `{task,provider,model,availability,reason}`;
  availability ∈ ready/missing_credential/misconfigured/disabled/
  breaker_open/not_applicable.
- Voice/SAM evidence is NOT persisted retrievably; only audit-event metadata
  (counts, adapter/model, errors) exists. UI shows that + R7; no transcript
  text, no masks (documented limitation, no new tables for display-only data).

## 5. Required backend additions (all minimal, tested, no migration)

1. `GET /proposals` — paginated owner list (new `ProposalRepository.list`).
2. `GET /cases/{id}/artifacts/{aid}/content` — owner-session, case-bound
   bytes with stored media type (invoice PII needs stricter-than-list auth).
3. `GET /dashboard/summary` — owner counts by state/verdict + recent cases +
   pending proposals + payments (read-only aggregate, existing repos).
4. `GET /audit/recent` — bounded owner list (new `recent(limit,offset)`).
5. `POST /auth/csrf-refresh` — CSRF rotation for session restore (§3).
6. Extend fact projection with stored `source` + `producer` (read-only,
   no secrets) for evidence/provenance display; update pinned tests.

No policy/auth/payment semantic changes. No vendor-registry or evaluation UI
(no Phase 4 requirement). Console gates all routes behind login by product
choice (server keeps its own auth model; documented).

## 6. Frontend contract map

Typed in `web/src/api/types.ts` 1:1 with §4; client sends credentials always,
CSRF header on the §2 mutations, `Idempotency-Key` on intake; 401 → session
drop + login redirect (single-flight); envelope errors mapped to safe UI copy
with request_id retained; no secrets/paths/traces rendered.
