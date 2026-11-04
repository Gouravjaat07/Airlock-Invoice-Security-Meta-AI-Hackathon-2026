# Authentication and approval (Phase 2)

## PIN

Argon2id (`argon2-cffi`) via `app/auth/pin.py`. No default PIN; without
`AIRLOCK_PIN_HASH`, login fails closed. Hashes never leave the server.

## Sessions

Opaque 256-bit tokens; only SHA-256 hashes stored (`auth_sessions`).
30-minute expiry (configurable), explicit revocation (logout), last
activity tracking. Transport: HttpOnly + Secure + SameSite=Lax cookie
(`Secure` may be disabled only via the explicit loopback development
setting, never in production). `Authorization: Bearer` also accepted.
`AIRLOCK_SESSION_SECRET` is generated at setup but currently reserved
(high-entropy random tokens need no HMAC key); it is never logged.

## Approval challenges

Per proposal: cryptographically random id, bound to the exact proposal
hash + session, 5-minute expiry, single-use consumed transactionally
with payment creation. Wrong proposal/session, reuse, or expiry all
fail closed with generic messages. Only the SHA-256 of the bearer is
stored (`auth_challenges.challenge_hash`, migration 003); migration 003
invalidates challenges pending at upgrade time (fail-closed, re-issue).

## Rate limiting and lockout

DB-backed fixed windows (`rate_limits`, multi-process safe): 5 failed
PIN attempts → 15-minute lockout (login and confirmation), 30
requests/minute per session, challenge issuance capped per
proposal+session. Auth failures are generic (no user/session oracle).

Login lockout is **global** (`login:owner`), never keyed by client IP or
`X-Forwarded-For`: Phase 2 configures no trusted proxy, so any
client-derived key is trivially rotated. Trade-off: a local attacker
can deliberately trigger the global lockout (short denial of owner
login). Acceptable for the single-owner loopback prototype; a
multi-user deployment needs per-account buckets plus trusted-proxy
configuration (see LIMITATIONS.md).

## CSRF

Cookie-authenticated mutations require the per-session CSRF token
(`X-CSRF-Token` header or `csrf_token` body field). No wildcard CORS
with credentials (no CORS middleware is installed in Phase 2).
