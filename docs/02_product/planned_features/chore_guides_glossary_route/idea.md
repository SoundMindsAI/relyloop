# Glossary route in the Guides catalog

**Date:** 2026-05-21
**Status:** Idea — surfaced during `feat_pr_metric_confidence` Story 1.5 review
**Origin:** Audit question from operator during the metric-key-drift fix conversation — "do we need a Glossary in the Guides section?" The audit confirmed [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) has 103+ entries today and grows with every feature (6 more land with `feat_pr_metric_confidence` Story 2.2). The keys are only discoverable via hover on inline `<InfoTooltip>` / `<HelpPopover>` triggers — there's no canonical reference surface.
**Depends on:** None (glossary data structure already exists; this is purely a render layer + route).

## Problem

The glossary is a load-bearing terminology source-of-truth (cited 100+ times across the codebase, parity-tested against backend Literal enums, locked by source-of-truth comments). But operators can only access it via the inline tooltip triggers that appear next to specific UI elements — meaning:

- An operator reading the PR body in GitHub can't look up what "Late-trial 1σ" means without first navigating to a study detail page that happens to render the term.
- A new user landing on `/judgments` can't browse the full set of judgment-related terms without hovering each element one at a time.
- Cross-feature concept search (e.g., "what's the difference between *runner_up_gap* and *runner_up_metric*?") requires file-system grep into `glossary.ts` — not viable for non-engineers.

The [`/guide`](../../../../ui/src/app/guide/page.tsx) catalog page is the natural home: it already aggregates long-form docs (`tutorial-first-study`, `workflows-overview`) and visual walkthroughs. A third section — **Glossary** — fits the same "operator reference" axis.

## Proposed capabilities

### Route + page

- New route `/guide/glossary` (and a third card on `/guide` next to the existing long-form-doc and walkthrough sections).
- Search box (case-insensitive substring match over keys + short text + long text).
- Optional category facets driven by key prefix (`study.*`, `judgment.*`, `proposal.*`, `confidence.*`, `chat.*`, …) — derive from key segments, no hand-maintained taxonomy.
- Each rendered entry shows the key (as code), the short form, and the long form (rendered through the existing `react-markdown` safety filter from `feat_contextual_help`).
- Deep-linkable anchors: `/guide/glossary#study.metric.ndcg` so tooltips' "Read more" can link directly into the page (future enhancement).

### Discoverability

- Add a Glossary entry to the home page's `StartHereChecklist` (introduced by `feat_contextual_help` Phase 3) as one of the "Learn the terminology" steps.
- Link from each guide's script.md footer ("See the glossary for definitions of every term used in this walkthrough").

## Scope signals

- **Backend:** none (glossary is a frontend `.ts` constant).
- **Frontend:** new page component at `ui/src/app/guide/glossary/page.tsx`; new card on the `/guide` catalog page; small enhancement to `GUIDE_REGISTRY` shape if it grows a "reference" category; vitest tests for search + category facets.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (read-only page, no state mutations).
- **Estimated size:** small — 1 new page (~200 LOC), 1 catalog card addition, ~80 LOC of vitest. The existing `glossary.ts` constant is already shaped to render directly.

## Why not yet prioritized

The glossary is functional today via the inline-tooltip surface — every term IS discoverable in context, just not in a single browsable list. Operators on the current MVP1 path (clone → run tutorial → ship first PR) don't hit the wall this would solve until they're routinely cross-referencing terms while reading PR bodies or making product decisions across multiple features. The need scales with operator-team size + tenure, which lands more naturally at MVP4 (multi-tenant, multiple platform-engineering teams sharing one deployment).

That said, the implementation cost is small enough that a quiet sprint-friction sweep could pick this up at any point — it's not gated on any deeper work landing first.

## Relationship to other work

- **Sibling:** [`chore_guides_faq`](../chore_guides_faq/idea.md) — operator-judgment-shaped Q&A that exceeds the 1–2 sentence tooltip budget. The Glossary answers "what does X mean?"; the FAQ answers "what should I do about X?" Different content axis, both belong under `/guide`.
- **Coordinates with:** the 6 new confidence-related glossary entries landing in `feat_pr_metric_confidence` Story 2.2. Whichever lands first sets the convention for any new prefix-grouped section.
- **Coordinates with:** the `feat_contextual_help` precedent (lives in `docs/00_overview/implemented_features/2026_05_15_feat_contextual_help/`) — that feature introduced the InfoTooltip + glossary infrastructure this builds on.
