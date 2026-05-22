# Home-page first-run nudge — surface meaningful demo data when the stack is fresh

**Date:** 2026-05-21
**Status:** Idea — product-design-shaped follow-up paired with the auto-seed-on-make-up chore
**Priority:** P1 — polish layer on the auto-seed shipped in PR #182; needs a small design pass (banner copy, badge styling, StartHereChecklist interaction) before it lands.
**Origin:** Same operator session as the four study-no-signal fail-fast follow-ups. Auto-seeding meaningful demo data into a fresh `make up` (now implemented on PR #182, merged 2026-05-21) handles the bootstrap path — but it doesn't address the operator who comes back to a longer-lived dev stack, finds an empty `/studies` listing, and isn't sure whether to (a) run their tutorial through `make seed-demo FORCE=1`, (b) author their own cluster + judgments, or (c) pick from the meaningful demo clusters that already exist.
**Depends on:** The auto-seed implementation shipped in PR #182 (`scripts/install.sh` + `scripts/seed_meaningful_demos.py --if-empty`). No corresponding planned-feature folder exists because the auto-seed was implemented in-line on PR #182 rather than scaffolded as a separate spec. This idea is the *next* layer of first-run UX. Coordinates with `feat_contextual_help` Phase 3's existing `StartHereChecklist` component.

## Problem

The auto-seed chore solves the "fresh stack = empty dropdowns" problem. It does NOT solve:

1. **The "is this real data or seed data?" question.** An operator on a long-lived stack sees 4 meaningful demo clusters (`acme-products-prod`, `news-search-staging`, etc.) alongside whatever they've created. Nothing marks the demo clusters as such; nothing nudges the operator toward them as a tutorial starting point.
2. **The "where do I start?" gap on the home page.** [`ui/src/app/page.tsx`](../../../../ui/src/app/page.tsx) shows the existing `StartHereChecklist` from `feat_contextual_help_mvp2` Phase 3 — a Stripe-style **3-step** checklist (Register cluster → Create query set + judgments → Run study). Source: [`ui/src/components/dashboard/start-here-checklist.tsx`](../../../../ui/src/components/dashboard/start-here-checklist.tsx). The checklist marks items "done" based on data presence, but it doesn't acknowledge demo data: an operator with auto-seeded clusters sees the cluster step marked done without understanding *why* (they didn't register one). **Critical design note for /spec-gen:** the checklist auto-hides entirely once all 3 steps are non-empty (see `start-here-checklist.tsx:48-52` early-return). On an auto-seeded fresh stack, steps 1 and 2 are already done — only step 3 remains visible. The "banner above the checklist" framing in capability A below has to account for this: either (a) the banner stands alone and renders independently of the checklist's visibility, or (b) the banner replaces the checklist on the demo-data path.
3. **The "I deleted everything, now what?" recovery path.** An operator who `make seed-demo FORCE=1`'d to start over, or who cleared the dev DB during local testing, has no in-UI affordance to re-seed. They have to remember the `make` target name.

Currently the home page assumes everything in the database is operator-authored. With the auto-seed chore landed, that assumption breaks.

## Proposed capabilities

Three interleaved surfaces, all on the home page:

### A. Demo-data callout on a fresh stack

When the home-page query for studies returns zero rows AND the cluster list contains demo-tagged rows (the 4 `make seed-demo` slugs: `acme-products-prod`, `corp-docs-search`, `news-search-staging`, `jobs-marketplace-prod`), render a banner above the existing `StartHereChecklist`:

> **You're set up with demo data.**
> Four sample clusters (`acme-products-prod`, `corp-docs-search`, `news-search-staging`, `jobs-marketplace-prod`) are pre-loaded with realistic queries, judgments, and a winning study. Try running your own optimization — pick a cluster from the [Create Study](#) button to use a pre-loaded judgment list.

Banner dismissable + sticky-dismissed (localStorage). Self-archives once the operator creates their first study.

### B. Demo-tag visual treatment in dropdowns + lists

The 4 demo clusters carry distinct name prefixes (`acme-`, `corp-`, `news-`, `jobs-` — no common prefix) and no machine-readable tag. Two paths:

- **Path 1 (recommended):** Backend exposes a `tags: list[str]` field on cluster rows. The seed script tags the 4 demo clusters with `["demo"]`. The frontend renders a small "Demo" badge next to demo-tagged rows in:
  - `/clusters` list
  - `/studies` cluster filter chip
  - Create-study modal cluster dropdown
- **Path 2 (lighter):** Hard-code the 4 demo slugs in `ui/src/lib/demo-data.ts` and check membership at render time. No migration; coupling to hardcoded names.

Path 1 is more correct but adds a migration + new API surface. Path 2 lets us ship the badge in a few hours.

### C. "Reset demo data" affordance

Add a "Reset to demo state" action — either:
- A new button on the home page's empty-state (visible only when no studies exist), OR
- An entry in the (currently nonexistent) settings/admin menu

The button hits a new POST `/api/v1/_test/demo/reseed` endpoint (similar gating as `/api/v1/_test/studies/seed-completed` — development-only). Confirmation dialog quotes the same wipe-warning text as `make seed-demo`. This closes the recovery loop: operators who blew away state from the CLI side can fix it from the UI side too.

C is the lowest priority — power users will know `make seed-demo FORCE=1`. Inline if scope is tight.

### Tests

- Vitest: banner renders when zero studies + demo clusters present; hides when first study created; respects localStorage dismissal.
- Vitest: cluster badges render for demo-tagged rows; don't render for operator-authored rows.
- Backend (if path 1): migration adds `clusters.tags JSONB`, default `[]`. Seed script tags demo rows. New filter param `?tag=demo` for the clusters list.

## Scope signals

- **Backend:** 0 LOC for path 2 of B; ~80 LOC for path 1 (migration + ORM + Pydantic + seed script update + 1 filter param). C adds ~30 LOC for the gated endpoint.
- **Frontend:** ~120 LOC for the banner component + ~30 LOC for badge wiring + dismissal localStorage logic. ~5 vitest cases.
- **Migration:** none for path 2; one column-add for path 1.
- **Config:** none.
- **Audit events:** N/A in MVP1.
- **Estimated size:** small-to-medium — depends on path 1 vs 2 for B and whether C ships in v1. Lower bound (path 2 of B, no C): ~200 LOC + 90 minutes. Upper bound (path 1, includes C): ~350 LOC + 3 hours.

## Why not yet prioritized

The auto-seed chore on PR #182 handles the literal "fresh stack experience" — an operator running `make up` for the first time now lands on a populated dev stack with meaningful demos selectable. This idea is the *polish* layer: visual treatments + dismissable banners + reset affordances. None of it is blocking; the auto-seed alone gets you 80% of the way to "first study can produce meaningful trials."

The remaining 20% is a product-design surface (banner copy, badge styling, banner dismiss-vs-archive semantics, interaction with the existing `StartHereChecklist`). That deserves its own design pass rather than an impulse implementation.

## Relationship to other work

- **Depends on:** the PR #182 auto-seed implementation (`scripts/install.sh` step 8 + `seed_meaningful_demos.py --if-empty`) — the demo data must reliably exist before the home page can call attention to it.
- **Coordinates with:** `feat_contextual_help_mvp2` Phase 3's `StartHereChecklist` ([`ui/src/components/dashboard/start-here-checklist.tsx`](../../../../ui/src/components/dashboard/start-here-checklist.tsx)) — needs to know about demo-authored vs operator-authored data so the checklist doesn't falsely-claim-complete on auto-seeded rows. Checklist auto-hides when all 3 steps are non-empty, so the demo-nudge banner cannot rely on the checklist being visible on a populated stack.
- **Compositional claim withdrawn:** an earlier draft of this idea claimed the demo-tag badge surface could double as an `e2e-test` filter via [`chore_e2e_test_rows_isolation`](../../../00_overview/implemented_features/2026_05_21_chore_e2e_test_rows_isolation/feature_spec.md) (now shipped as PR #186). The shipped feature did NOT introduce a tag column — cleanup uses a frontend-side per-worker JSONL registry of `(resource, id)` tuples. So the "one more tag value" composition is invalid; path 1 of B can't piggy-back on infrastructure that doesn't exist.
- **Composes with:** [`chore_guides_glossary_route`](../chore_guides_glossary_route/idea.md) + [`chore_guides_faq`](../chore_guides_faq/idea.md) — first-run nudges naturally link to glossary terms + FAQ entries.
