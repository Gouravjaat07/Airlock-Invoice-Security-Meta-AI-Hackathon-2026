# Phase 4 — API Integration

Base URL: same-origin (`VITE_API_BASE_URL`, default empty). Dev server
proxies `/api` to `http://127.0.0.1:8000` (backend has no CORS by design).
Production: serve `web/dist` behind the same origin as the API.

## Endpoints consumed (all verified against `app/api`)

| Method | Path | Auth | CSRF | Purpose |
|---|---|---|---|---|
| POST | /api/v1/auth/login | — | — | PIN → cookie + `{session_id,csrf_token,expires_at}` |
| POST | /api/v1/auth/logout | cookie | — | revoke + clear cookie |
| GET | /api/v1/auth/me | cookie | — | session restore |
| POST | /api/v1/auth/csrf-refresh | cookie | — | rotate CSRF (new, §4.1) |
| GET | /api/v1/health | — | — | status/version/schema/policy |
| GET | /api/v1/dashboard/summary | cookie | — | counts + recent (new, §4.1) |
| GET | /api/v1/cases?limit&offset | — | — | newest-first page |
| POST | /api/v1/cases | — | — | multipart intake + `Idempotency-Key` |
| GET | /api/v1/cases/{id} | — | — | full summary view |
| POST | /api/v1/cases/{id}/process | — | — | run pipeline (≤10 min, cancellable wait) |
| POST | /api/v1/cases/{id}/reject | cookie | header | to REJECTED |
| POST | /api/v1/cases/{id}/facts/{fid}/edit | cookie | header | owner correction + re-run |
| GET | /api/v1/cases/{id}/artifacts/{aid}/content | cookie | — | preview bytes (new, §4.1) |
| GET | /api/v1/proposals?limit&offset | cookie | — | newest-first page (new, §4.1) |
| GET | /api/v1/proposals/{id} | cookie | — | ProposalView |
| POST | /api/v1/proposals/{id}/challenge | cookie | header | issue bearer (memory only) |
| POST | /api/v1/proposals/{id}/confirm | cookie | header | `{challenge_id,pin}` → payment view |
| GET | /api/v1/cases/{id}/payments/mock | cookie | — | payment views |
| GET | /api/v1/payments/mock/{id} | cookie | — | single payment view |
| GET | /api/v1/audit/{case} | cookie | — | case events (parsed payloads) |
| GET | /api/v1/audit/recent?limit&offset | cookie | — | global newest-first (new, §4.1) |
| POST | /api/v1/audit/verify | cookie | — | `{ok,events,break_at?,reason?}` |
| GET | /api/v1/providers | cookie | — | 3 task statuses (config, never live-probed) |

## Client behavior (`src/api/client.ts`)

- `credentials: "include"` always; JSON bodies get Content-Type, FormData
  never does (browser boundary). Timeouts per call (30 s default, 120 s
  intake, 10 min process). AbortController linked for cancel.
- Errors: envelope `{code,message,request_id}` → `ApiError`; malformed JSON
  and network failures mapped; request_id shown, never traces/paths.
- 401 → single-flight session drop + login redirect (login/boot opt out).
- 403 CSRF rejection → single-flight token rotation + exactly one retry
  (safe: `validate_csrf` runs before any service logic).
- No retries otherwise; mutations never auto-retry.

## Shapes that need client parsing

`verdict.reasons_json|rule_ids_json|rule_details_json` are JSON strings —
`parseVerdict` validates each item and flags `degraded` instead of throwing.
Fact `value` is `unknown` by field (string|null|bank object|line-item list).
