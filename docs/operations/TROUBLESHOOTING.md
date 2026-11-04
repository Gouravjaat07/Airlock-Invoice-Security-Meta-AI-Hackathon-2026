# Troubleshooting

## Backend won't start

- `Policy file not found` — run from the repo root; `policy/rules.toml`
  must exist.
- `Unsafe configuration: ...` — read the message: production
  forbids fixture/mock readers, insecure cookies, custom fixtures,
  and the eval API. Fix env, restart.
- `migrations_pending` — run the DB upgrade path (see `app/main.py`
  / `app/storage/database.py`); the server fails fast by design.

## Cases fail with `E_READER_UNAVAILABLE`

- Fixture mode: set `AIRLOCK_FIXTURE_READER=1` and upload a
  registered fixture artifact (unregistered bytes always fail).
- Live mode: check `GET /api/v1/providers` — `missing_credential`
  (export the key), `misconfigured` (fix selector/URL), or
  `breaker_open` (see the failure runbook).

## Cases fail with `E_API_UNAVAILABLE` / `E_RATE_LIMIT`

Provider-side. Check the provider dashboard, honor `Retry-After`,
then re-run the case. Persistent 401 → rotate the key; 402 →
fix billing; 404 model → check the model ID against
`META_API_CONTRACTS.md`.

## Verdict surprises

- Unexpected `DENY` + R8: schema/refusal — inspect rule details
  and sanitized warnings; re-run `phase5_eval.py`.
- Unexpected `ESCALATE`: read `rule_ids_json` — R5 cap/PO, R6
  due window, R7 SAM/voice conflict, R10 ambiguity each name
  their evidence.
- `false-ALLOW` in eval: stop. Do not weaken R1–R10 to make it
  pass — investigate the pipeline change that caused it.

## Frontend

- Blank page / 401 loop: session expired — log in again. Check the
  Vite proxy (`/api` → `127.0.0.1:8000`) and that the backend runs.
- Providers page shows `missing_credential`: backend config, not a
  UI bug — export the key server-side and refresh.
- `npm test` failure mentioning `fetch`: a test forgot `stubFetch`
  — tests never touch the network.

## E2E

Follow `web/e2e/smoke.mjs` header exactly: isolated temp DB/BLOB
paths, seeded vendors, `AIRLOCK_E2E_PIN`, backend on :8000,
frontend dev server on :5173. Never point E2E at the real DB.
Multimodal (3-file) runs: `web/e2e/multimodal.mjs`
(`npm run e2e:multimodal`); live-provider startup:
`docs/operations/MULTIMODAL_DEV_STARTUP.md`.

## Multimodal lanes

- Voice/SAM shows "not evaluated": the artifact was uploaded but
  the comparison never ran — read the R7 message and the lane
  `reason`; fix the upstream failure (usually extraction).
- Voice/SAM shows "failed" + `error_code`: provider-side failure
  category (`auth`, `rate_limit`, `timeout`, `server`, ...); the
  case never falls back to mock/fixture.
- SAM count 0 with ESCALATE: a completed empty stream — evidence
  of zero detections, not proof of a match. Correct behavior.
- `extraction.rejected` lists `qty`/`price` naming the required
  field: the model renamed a schema field; fix the prompt or the
  document, never guess-merge the value.

## Live smoke

- Preflight fails: env not exported in *this* shell (remember:
  `.env` is never auto-loaded).
- `--live` without `--allow-billable` (or vice versa): refused
  with exit 2 — re-run with both flags.
- `contributor` model: refused — use the Standard model ID.
- Glimmer refused/unreachable: start the local runtime first;
  Airlock never starts or downloads it.
