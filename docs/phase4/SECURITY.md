# Phase 4 — Security

## Session and CSRF

- HttpOnly `airlock_session` cookie; JS never reads it. `/auth/me` restores;
  401s collapse single-flight into logout + `/login?expired=1`.
- CSRF token in memory only (never storage/URL/logs). Mutations send
  `X-CSRF-Token`; a 403 rejection rotates via `POST /auth/csrf-refresh` and
  retries once. Logout clears state + server revocation + query caches.
- No PIN/credential defaults; PIN field `autocomplete=off`, cleared after
  every submit; no client attempt counter (server lockout authoritative).

## Approval and payments

- Challenge bearer in component state only — never rendered (tested),
  cleared on success/discard/unmount/logout. Confirm needs an explicit
  checkbox + PIN; PIN state cleared in `onSettled`.
- UI gates (PENDING + current ALLOW verdict) are hints; the server enforces
  every transition, hash binding, expiry, and single-use rule.
- Mock-only wording everywhere (`MOCK PAYMENT — NO MONEY TRANSFERRED`);
  ambiguous timeouts reconcile by refetch, never blind re-submit.

## Content and transport

- Same-origin only; browser never calls Meta/Baseten/local-model endpoints.
  No secrets in the bundle (`VITE_` vars are non-secret; verified by build
  grep + secret hygiene). No `.env` exposure; `web/dist` ignored by git.
- Uploads rendered as data: blob-URL previews (`img`/`audio`/`video`/
  PDF iframe), object URLs revoked, no `dangerouslySetInnerHTML`, filenames
  never used as paths, svg/html never executed.
- Errors show safe copy + request ref; no traces/SQL/paths/provider bodies.
- No notification center (would be fake); no vendor/policy/registry editing
  UI (no authorized backend workflow exposed to the console).

## Residual notes

- CSP headers are a deployment concern: document `default-src 'self'` +
  `frame-src blob:` (PDF preview) needs when placing behind a proxy;
  not implemented in-app, not claimed.
- Case list/detail APIs are server-public by design; the console gates all
  routes behind owner login as a product choice (server still enforces).
