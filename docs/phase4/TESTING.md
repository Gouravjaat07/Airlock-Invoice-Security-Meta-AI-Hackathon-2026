# Phase 4 — Testing

## Frontend (`web/`, Vitest + React Testing Library)

- `npm test` — unit (format, error map, verdict parsing, slot validation),
  component (badges, uploader UI incl. invalid-type message), API contract
  (client: envelope mapping, CSRF attach/rotate/retry-once, 401 handling,
  multipart boundary, timeouts), integration through the real router with a
  stubbed network boundary: login flow (toggle, invalid PIN + field clear,
  success → overview, expired banner), case detail (facts, DENY policy tab,
  process + refresh, EXECUTED hides action, artifact preview), approval flow
  (review → challenge → checkbox + PIN → payment; **challenge bearer never
  rendered**; ineligible/non-pending withhold actions).
- `npm run typecheck` (strict `tsc --noEmit`), `npm run lint` (eslint:
  recommended + react-hooks, `no-explicit-any` error).
- `npm run build` — typecheck + production bundle; `dist/` inspected for
  size and secret absence.

## Backend (unchanged gates + new endpoint tests)

- `tests/api/test_phase4_endpoints.py` — auth (401s), proposals list +
  pagination, artifact bytes round-trip + 404 oracle checks, dashboard
  counts, audit-recent shape + route-ordering, CSRF rotation lifecycle,
  fact source/producer projection.
- Full suite, Ruff, hygiene, Phase 2 strict gate, Phase 3 eval, Phase 3
  strict gate all re-run after the additions (see final report).

## Integrated

- Real backend (uvicorn, isolated temp DB) + real Vite dev server (proxy)
  with scripted workflows through the proxy: login, dashboard, intake,
  process, verdict, challenge, confirm, payment, audit, providers.
- Built-bundle smoke: `vite preview` serves `dist/index.html` (static only;
  preview has no API proxy by design).
- Real-browser E2E (Playwright headless Chromium, `npm run e2e`): 13/13
  steps green against live backend + Vite proxy on an isolated temp DB —
  login page, white-theme computed style, wrong PIN, login, intake, process
  to ALLOW, policy tab, evidence preview, proposal review, approval (with a
  DOM check that the challenge bearer never renders), audit verify,
  providers, logout. Prereqs are documented in `web/e2e/smoke.mjs`.

## Synthetic data

Tests use `fixtures/` and in-test literals only. No real PINs, bank data,
or provider credentials anywhere in the suite.
