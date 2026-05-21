# Glossary route in the Guides catalog

**Date:** 2026-05-21
**Status:** Idea — surfaced during `feat_pr_metric_confidence` Story 1.5 review
**Priority:** P1 — operator-facing terminology surface; cheap to ship (~200 LOC of UI render, 0 backend, no migration). Operator explicitly asked about this on 2026-05-21. Prereq for `chore_guides_faq`.
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

## Process integration — keeping the glossary current as the codebase grows

The glossary will rot the moment a feature ships with new UI terms but no matching `glossary.ts` entries. Today nothing in the pipeline enforces "did this feature introduce a new term that needs a glossary entry?" — the tooltip inventory in `spec-gen` Step 3 #11 captures *tooltip text* but doesn't enforce that the text resolves to a glossary key. We need to bolt this check onto the existing pipeline gates rather than create a parallel surface. **Recommendation: three coordinated edits, in leverage order.**

### 1. `.claude/skills/impl-execute/SKILL.md` — Step 3 (Guide impact assessment) — primary gate

This is the only **MANDATORY blocking gate** in the post-implementation flow (it blocks Step 8 finalization). It's the right place for the load-bearing check because nothing ships without passing it. Extend the existing questionnaire (currently 3 items: regenerate / new guide / route mapping) with two glossary-shaped questions:

- **New terminology:** "Did this PR introduce any new product term (status value, metric name, parameter type, error code, role, regime label) that operators will see in the UI or in a PR body? If yes, list the term + the glossary key it would live under + whether the entry exists in `ui/src/lib/glossary.ts`. Missing entries block finalization until added or a `chore_glossary_<slug>` idea file is captured."
- **Drift on existing entries:** "Did this PR change the behavior of an already-documented term (e.g., a metric formula changed, a status transition rule shifted, a default value moved)? If yes, the matching glossary entry's `long` form must be updated in the same PR — silent semantic drift in glossary copy is its own bug class."

This is the **single most leveraged edit** because Step 3 is already the bottleneck for tenant-facing UI changes.

### 2. `.claude/skills/spec-gen/SKILL.md` — Step 3 #11 (Tooltip inventory audit) — upstream identification

Right now #11 verifies the spec includes a tooltip inventory. Extend it to also verify the tooltip inventory **enumerates the glossary keys** each entry will reference (or note "new key — to be added in Story X.Y"). This pushes the check upstream to spec-review time, where catching the gap costs ~5 minutes vs. ~30 minutes at impl-execute Step 3.

Wording change: "verify the spec includes a tooltip inventory **and that every entry cites either an existing glossary key (verify via `grep` of `ui/src/lib/glossary.ts`) or names a new key to be added in a specific story.**"

### 3. `.claude/skills/impl-plan-gen/SKILL.md` — line 111 (Tooltip plan requirement) — plan-time enforcement

Currently the plan must include "tooltip text, trigger, placement, and actual JSX/markup pattern" for every tooltipped element. Extend to require the glossary key column and source-of-truth file path. This forces the plan author to acknowledge the glossary surface during planning, not during implementation when the cost of discovery is highest.

Wording change: "tooltip text, trigger, placement, **glossary key, source-of-truth comment target**, and actual JSX/markup pattern from the codebase."

### What NOT to update

- **`pipeline/SKILL.md`** — already references "Assess guide impact" via Step 3; no edit needed, it inherits the impl-execute change.
- **`guide-gen/SKILL.md`** — generates walkthrough screenshots, not glossary entries; out of scope.
- **`bug-fix/SKILL.md`** — bug fixes rarely add new terminology; if they do, the impl-execute hand-off catches it (bug-fix chains into `/impl-execute --ad-hoc` which runs Step 3 in ad-hoc mode per SKILL.md line 769).
- **`idea-preflight/SKILL.md`** — audits live-codebase claims; not the right surface for "should add a glossary entry."
- **A new `glossary-gen` skill** — overkill. Glossary entries are 2–5 lines of TS; the friction is *remembering* to add them, not *authoring* them. Gates beat tools here.

### Acceptance criterion for this idea

This idea is "done" when:
1. The Glossary route ships per "Proposed capabilities" above, AND
2. The three skill edits above are applied (can ship in the same PR as the route or a sibling chore PR), AND
3. The next post-edit feature merge demonstrably runs the new questionnaire (verified by a one-line "glossary delta: N new keys added, M existing keys updated" note in the PR description).
