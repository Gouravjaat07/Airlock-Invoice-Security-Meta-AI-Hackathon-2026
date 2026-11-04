# API reference (Phase 2, `/api/v1`)

Base: `http://127.0.0.1:8000/api/v1`. OpenAPI: `/api/openapi.json`,
interactive docs: `/api/docs`. All errors use the envelope
`{"error": {"code", "message", "request_id", "details"}}`; no tracebacks.

## Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/login` | no | `{"pin"}` → HttpOnly session cookie + `csrf_token` |
| POST | `/auth/logout` | yes | Revokes session, clears cookie |
| GET | `/auth/me` | yes | Session state |

Cookie-authenticated mutations must send `X-CSRF-Token` (or `csrf_token`
in JSON bodies that accept it). `Authorization: Bearer <token>` (token
from the login `Set-Cookie`) skips CSRF. PIN failures are generic 401;
5 failures globally → 429 lockout (15 min, single-owner scope).

## Cases

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/cases` | no | Multipart: `invoice` (required) + `delivery` + `voice` |
| GET | `/cases` | no | List (`limit`/`offset`) |
| GET | `/cases/{id}` | no | Full summary: state, facts, verdict, proposal, payments |
| POST | `/cases/{id}/process` | no | Run pipeline (idempotent; 200 always carries verdict) |
| POST | `/cases/{id}/reject` | owner | NEEDS_REVIEW/PROPOSED → REJECTED |
| POST | `/cases/{id}/facts/{fid}/edit` | owner | Typed correction → deterministic re-run |

`POST /cases` honors `Idempotency-Key`. `POST .../process` on a finished
case returns the existing outcome (no second proposal/verdict).

## Vendors

`GET /vendors`, `POST /vendors` (owner), `GET /vendors/{id}`,
`PATCH /vendors/{id}` (owner), `POST/GET
/vendors/{id}/bank-change-requests` (owner). Bank references are
transient inputs; only HMAC fingerprints are stored/returned. Changes
stay `pending` until the cooling-off elapses; the old fingerprint rules
meanwhile.

## Proposals, payments, audit, eval

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/proposals/{id}` | owner | Stored deterministic proposal |
| POST | `/proposals/{id}/challenge` | owner | One-time proposal-bound challenge |
| POST | `/proposals/{id}/confirm` | owner | `{"challenge_id","pin"}` → MOCK payment |
| GET | `/payments/mock/{id}` | owner | Mock payment view (always `mock: true`) |
| GET | `/cases/{id}/payments/mock` | owner | Case payments |
| GET | `/audit/{case_id}` | owner | Sanitized case events |
| POST | `/audit/verify` | owner | Full chain verification |
| POST | `/evaluation/run` | owner | Dev-only scenario run (flag-gated) |
| GET | `/evaluation/runs/{id}` | owner | Run summary |
| GET | `/evaluation/results/{id}` | owner | Per-scenario results |

Error codes: `E_UPLOAD E_SCHEMA E_READER_UNAVAILABLE E_READER_TIMEOUT
E_API_UNAVAILABLE E_AUTH E_RATE_LIMIT E_EXPIRED E_DUPLICATE E_POLICY_DENY
E_POLICY_ESCALATE E_CONFLICT E_STATE_TRANSITION E_AUDIT E_STORAGE
E_DATABASE E_INTERNAL`. Unknown ids → `E_SCHEMA` with 404.
