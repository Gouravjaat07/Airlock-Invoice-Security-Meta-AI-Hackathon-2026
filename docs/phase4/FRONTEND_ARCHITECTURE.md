# Phase 4 — Frontend Architecture

React 19 + TypeScript (strict) + Vite 7 console in `web/`. React Router v7
routes/guards, TanStack Query v5 server state, hand-rolled CSS tokens
(no Tailwind), Vitest + React Testing Library tests.

## Structure

- `src/main.tsx` — providers (router, query client, toasts, session), CSS.
- `src/App.tsx` — public `/login`, guarded shell, 404.
- `src/api/` — `types.ts` (1:1 backend contracts), `client.ts` (single fetch
  wrapper), `endpoints.ts` (typed calls), `hooks.ts` (queries/mutations),
  `parse.ts` (safe verdict-JSON parsing).
- `src/auth/session.tsx` — restore/login/logout, in-memory CSRF + rotation.
- `src/components/` — icons, controls, feedback, badges, overlays (dialog,
  toast), misc (tabs, timeline, copy), FileUploader, EvidencePreview.
- `src/layouts/Shell.tsx` — sidebar/drawer + session footer.
- `src/pages/` — Login, Dashboard, Cases, Intake, CaseDetail (5 tabs),
  Proposals, Proposal (approval), Audit, Providers, Settings.
- `src/utils/` — format (display-only, amounts untouched), errors (safe copy).
- `src/styles/` — tokens, base, components, shell. White theme enforced by
  tokens (`--ak-bg: #ffffff`); no dark mode anywhere.

## State rules

- Server state ONLY in TanStack Query (one key per resource, `retry: false`,
  explicit invalidation after mutations). No duplicated server copies.
- Local UI state in component state (tabs, dialogs, form fields, uploads).
- Sensitive material (CSRF token, challenge bearer, PIN) in memory only:
  cleared on logout/expiry/completion/unmount. Nothing sensitive persists.
- No polling loops: processing is a single long request with user cancel;
  abort stops waiting, never the server job (UI says so); refresh re-reads.

## Routing

BrowserRouter. `/login` public; everything else behind `RequireAuth`
(boot splash → `/login?expired=1` on expiry). Deep links: case/proposal IDs.
No notification center (no backend support); toasts + inline alerts only.
