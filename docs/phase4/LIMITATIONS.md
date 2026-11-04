# Phase 4 — Limitations

Honest scope boundaries. Anything here is NOT claimed as working.

1. **No live model verification.** The UI renders provider *configuration*
   status only. No real Meta/Baseten/Glimmer calls were made in Phase 4.
2. **Transcript text and segmentation masks are not retrievable.** The
   backend persists only verification metadata (counts, adapter/model,
   errors) in audit events — the evidence tab shows exactly that. No new
   persistence was added for display-only data.
3. **No case search/filter/sort.** The list API offers limit/offset only;
   the UI paginates without faking filters.
4. **No vendor-registry or evaluation UI.** No Phase 4 requirement; the
   APIs exist but the console deliberately exposes no editing surface.
5. **No payment deep-link route.** Payments render in case context and on
   the confirmation result; `GET /payments/mock/{id}` stays API-only.
6. **Fact source geometry unavailable.** `page/region/timecode` are not
   populated by current readers; the UI labels them unavailable.
7. **PDF preview uses the browser viewer** (iframe + blob URL), not a
   custom renderer: no per-page programmatic control beyond native UI.
8. **CSP is deployment configuration**, documented in SECURITY.md, not
   implemented or claimed in-app.
9. **Production serving needs a reverse proxy** (same-origin static +
   API). Verified paths: Vite dev proxy and `vite preview` static smoke.
10. **Browser E2E runs headless Chromium only** (one viewport, desktop).
    Mobile/tablet layouts are implemented responsively but were verified by
    code inspection, not automated viewport runs.
