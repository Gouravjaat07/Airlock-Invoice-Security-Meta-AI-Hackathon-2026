# Phase 4 — UI Design System

Mandatory: white/light theme on every page, modal, and drawer. No dark mode,
no auto theme switching. Tokens in `src/styles/tokens.css`.

## Tokens

- Backgrounds: `--ak-bg/#ffffff`, `--ak-subtle/#f6f8fa` (wells, table heads).
- Text: `#0f172a` headings, `#334155` body, `#475569` secondary, `#64748b`
  captions only (never body copy).
- Accent: teal `#0e7490` / `#155e75`, soft `#ecfeff`. No purple/blue
  gradients, no glassmorphism, no glow-everywhere.
- Status: green/amber/red/blue pairs (bg + border + text), always with an
  icon and readable label — never color alone.
- Type: system stack (no webfont dependency); mono for IDs/hashes/amounts.
  Clear h1/h2/body/caption hierarchy.
- Radius: 4/6/10/999 by element kind; shadows restrained (sm/base/lg).
- Spacing scale 4–40px; content max 1160px; sidebar 240px.

## Components (`src/components`)

Button (4 variants, loading), Field+TextInput/TextArea/Select/PinInput
(show/hide), Badge + 7 domain status badges, Card, Dialog (focus-trapped,
Escape, scroll-lock), Toast (aria-live, auto-dismiss), Tabs (arrow keys),
Table, Pagination (no fake totals — next disabled on short page), Skeleton,
EmptyState, ErrorState (safe message + ref + retry), Alert (4 tones),
PageHeader, FileSlot (drag/drop, chip, remove), EvidencePreview (blob URLs,
revoked on unmount), Timeline (audit, payload in `<details>`), CopyRef,
Progress, KPI cards.

## Layouts and responsive

Sidebar shell ≥920px; sticky topbar + drawer below. Grids 4→2→1 columns.
Tables scroll horizontally inside bordered wrappers; dialogs/drawers are
viewport-safe. Touch targets ≥32px. `prefers-reduced-motion` disables
shimmer/spin. Focus-visible rings everywhere; dialogs trap focus and
restore it; toasts announce politely; tables use scoped headers.
