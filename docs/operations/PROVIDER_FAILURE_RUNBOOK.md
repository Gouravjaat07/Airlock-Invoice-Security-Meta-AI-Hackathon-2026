# Provider failure runbook

Failures are explicit and local: one provider's outage never reroutes
to another provider or to fixtures, and never produces a verdict by
itself.

## Triage by symptom

| Symptom | Meaning | First action |
|---|---|---|
| Case `ERROR` + `E_API_UNAVAILABLE` | Transport/provider failure | Inspect provider status + logs; fix cause; re-run case |
| Case `ERROR` + `E_RATE_LIMIT` | 429 survived retries | Wait out `Retry-After`; lower inflight; re-run |
| Case `ERROR` + `E_READER_UNAVAILABLE` | Selection failure (disabled/unconfigured/missing key/breaker) | Fix config or wait for breaker cooldown |
| Verdict `DENY` + R8 | Refusal/malformed content | Check prompt/schema versions; inspect sanitized warnings |
| Verdict `DENY` + R9 | Required verifier errored | Same as transport failure, then re-run |
| `breaker_open` in `/providers` | 5 consecutive provider-side failures | Find root cause; breaker half-opens after 60 s |
| `INCOMPLETE` notes | Timeout/read abort after possible acceptance | Reconcile: call may have been billed; do not blindly retry |

## Breaker behavior

- Trips on 5 consecutive provider-side failures (timeout, server,
  rate-limit, unavailable). Auth/config/refusal failures never trip
  it (retrying those is pointless).
- Per-provider isolation: Meta, Baseten, Glimmer breakers are
  independent. In-memory only: a restart clears state.
- Test hook: `GUARDS.reset_for_tests()`. No operator reset
  endpoint exists by design — fix the cause, not the signal.

## Retry policy (automatic, bounded)

- Retried: 429 (honor `Retry-After`, ≤300 s), 5xx, connect
  failures, safe timeouts. Exponential backoff + 25% jitter,
  `AIRLOCK_PROVIDER_MAX_RETRIES` (default 2).
- Never retried: 400/401/402/403/404/413, schema failures,
  refusals, 504/gateway-timeout (per provider guidance — the
  request may have been accepted and billed).

## Reconciliation after ambiguity

1. Identify the case + provider + `request_id` (case audit,
   sanitized logs — never raw payloads).
2. Check the provider dashboard for the request (usage/billing).
3. Re-run the case explicitly (`POST .../process`); idempotency
   and duplicate guards make re-runs safe.
4. Verify the audit chain (`POST /api/v1/audit/verify`); retries
   must not duplicate audit events (single transaction per step).

## Escalation to the owner

- 401/402/403/404: config or account problem — operator fixes,
  no vendor call needed.
- Repeated 5xx/429 across hours: provider incident — pause live
  intake, keep fixture/dev flows, resume after smoke passes.
- Any suspected credential leak: rotate immediately, purge logs,
  re-run `check_secret_hygiene.py`.
