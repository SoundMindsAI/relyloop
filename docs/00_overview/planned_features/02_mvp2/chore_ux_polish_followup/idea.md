# UX-audit polish follow-up (dark-mode long-tail + IA + forms)

**Date:** 2026-07-11
**Status:** Idea — deferred remainder of the 2026-07-11 UX audit, whose high/medium findings shipped across PRs #616–#620
**Priority:** P2
**Origin:** UX audit (5-agent sweep, 2026-07-11). The five fix PRs — #616 (wire values), #617 (resilience), #618 (a11y), #619 (IA), #620 (theming/dark mode) — each deferred a low-severity tail, tracked here.
**Depends on:** None (all build on the merged PRs above)

## Problem

The UX audit's high- and medium-severity findings are fixed and merged. A
low-severity tail was deliberately deferred to keep each PR reviewable. The
sharpest item is that **dark mode is now reachable (toggle shipped, primitives
migrated + Playwright-verified) but not yet swept across the long tail** — some
ad-hoc hardcoded colors remain light-only, so a human dark-mode QA pass is
needed before calling dark mode 100% done.

## Proposed capabilities

### Dark-mode completion (from #620)

- Sweep the ~49 `text-blue-600` link occurrences (31 files) to a
  `text-primary`/`buttonVariants({variant:'link'})` token so links theme in
  dark mode; sweep any remaining `bg-*-50` callouts to the new `<Alert>`
  primitive.
- Migrate the three Recharts charts off hardcoded hex series colors to a
  theme-aware palette, and add axis labels + units (Y is the objective metric,
  X is `trial_number` — currently unlabeled).
- **Human dark-mode QA pass** across every route/surface (the token migration
  is correct-by-construction, but the long tail needs eyes).

### IA & navigation tail (from #619)

- Empty-state CTA parity: add a `primaryCta` to the studies / query-sets /
  templates empty states (wire the page's create handler through, mirroring
  `clusters-table`'s `onRegisterCluster`).
- Cluster-tree breadcrumb consistency: extract the leaf page's breadcrumb into
  a shared `<ClusterTreeBreadcrumb>` and render it on the intermediate
  index-summary + documents-list pages (F5).
- Reverse "used by" links on template / query-set / judgment-list detail pages
  (mirror `StudiesByClusterTable`); make template `parent_id` a link (F7).
- Resolve the query-set→cluster link to the cluster **name** (currently links
  but shows the raw UUID — needs a `useCluster` call via a sub-component).

### Forms & polish (from #617/#618)

- Comprehensive `aria-invalid`/`aria-describedby` association across the large
  study-creation wizard's fields (the small dialogs were done in #618; wizard
  errors are announced via `role="alert"` but not yet field-associated).
- Centralized `formatDateTime()` (and a companion `formatNumber()`) util to
  replace the ad-hoc `toLocaleString()` calls for consistent, locale-stable
  formatting. Note: only the **date-time** `toLocaleString()` calls belong in
  `formatDateTime()`; some occurrences format **numbers** (e.g.
  `doc_count.toLocaleString()` in `create-study-modal.tsx`) and belong in
  `formatNumber()` instead — don't blanket-replace.
- Per-list `errorMessage`/`onRetry` wiring on the DataTable error state (the
  optional props landed in #617 with a page-reload fallback; wire real
  `query.error.message` + `query.refetch` through the consumer tables).

## Scope signals

- **Backend:** none.
- **Frontend:** `ui/src/components/**` (primitives + charts + tables + wizard),
  `ui/src/app/**` (breadcrumb pages, empty-state CTAs).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.

## Why deferred

All items are low-severity polish. Each was split out of its parent PR to keep
that PR focused and reviewable; the dark-mode long-tail sweep in particular
benefits from a dedicated human visual-QA pass rather than being rushed into
the theming PR. None blocks the shipped high/medium fixes.

## Relationship to other work

Direct continuation of PRs #616–#620 (all merged, `implemented_features`-bound
once finalized). No conflicts; purely additive polish.
