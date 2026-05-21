# FAQ in the Guides catalog

**Date:** 2026-05-21
**Status:** Idea — surfaced during `feat_pr_metric_confidence` Story 1.5 review
**Origin:** Audit question from operator during the metric-key-drift fix conversation — "do we need an FAQ in the Guides section?" The header of [`docs/08_guides/README.md`](../../../03_runbooks/) line 3 *mentions* "FAQs" as one of the documented content types, but no FAQ file exists in the repo and no FAQ surface exists in the UI — that's stale ambition from when the Guides directory was first sketched.
**Depends on:** None.

## Problem

Tooltips and the glossary answer "**what does X mean?**" within a 1–2 sentence budget. They don't carry the operator-judgment-shaped questions that come up *after* the term is understood:

- "My CI band is missing — why?" (Answer requires citing FR-7's degradation table + the 5-query minimum + the per_query_metrics IS NULL old-study case.)
- "Convergence regime is *noisy* — should I rerun with a different sampler?" (Answer needs to balance "noisy is often fine" vs "noisy + sharp_peak warrants caution" vs "noisy on a 10-trial study is meaningless — get more trials first.")
- "The PR body shows `regressed: 2` — should I reject?" (Answer requires explaining that regressors aren't categorical bad: an operator who cares about a specific query catalog should look at the named regressors, but a global-relevance operator might be fine with a 2-regression / 14-improvement trade.)
- "Why does my study have `confidence: null` instead of a partial shape?" (Answer cites AC-3 vs AC-3a — the difference between "winner trial exists but per_query_metrics IS NULL" and "best_trial_id IS NULL".)
- "When should I trust the LLM-as-judge ratings vs override them?" (Answer cites the κ calibration story + the override path from `feat_llm_judgments`.)
- "I rejected a proposal — what happens to the open PR on GitHub?" (Answer cites the `proposal.status='rejected'` → no automatic GitHub action; operator must close the PR manually. Documented in [`pr-open-debugging.md`](../../../03_runbooks/pr-open-debugging.md) but not surfaced in-app.)

Today this knowledge lives in:
- Spec edge/error-flow sections (read by engineers, not operators).
- Runbooks under [`docs/03_runbooks/`](../../../03_runbooks/) (good for SREs, not operator-facing).
- Tooltips (too short for the *why*).
- Tribal knowledge in chat history (lost).

The result: every operator who hits one of these questions asks the same one — either internally to the platform team, or by giving up. The FAQ surfaces the canonical answers at a discoverable URL.

## Proposed capabilities

### Page + content

- New route `/guide/faq` and a fourth section on `/guide` (next to long-form docs, walkthroughs, and the proposed [Glossary route](../chore_guides_glossary_route/idea.md)).
- Curated content — **not** a sprawling community-style Q&A. Initial pass targets ~15–20 entries grouped by phase: **Studies & Confidence** (5–7 entries), **Judgments** (3–4), **Proposals & PRs** (3–4), **Chat agent** (2–3), **Setup & install** (2–3).
- Each entry: a clear question header + a 3–5 sentence answer + cross-links to relevant tooltips (glossary keys), runbooks, and spec ACs.
- Anchor-deep-linkable: `/guide/faq#confidence-ci-missing` so tooltips can link to the canonical answer.

### Authoring source

- Markdown files under [`docs/08_guides/faq/`](../../../08_guides/) — one `.md` per top-level category, shipped in-app via the same `react-markdown` pipeline the guide scripts already use.
- Registered in `GUIDE_REGISTRY` (or a sibling `FAQ_REGISTRY`) with parity tests against the actual markdown files.

### Discoverability

- Surface relevant entries from inline `<HelpPopover>` triggers via a "Related FAQ →" footer link (uses the deep-link anchors).
- Add a "Common questions" callout on the home page below the existing `StartHereChecklist` (from `feat_contextual_help` Phase 3).

## Scope signals

- **Backend:** none.
- **Frontend:** new page component at `ui/src/app/guide/faq/page.tsx` + per-category markdown rendering; new card on `/guide`; vitest for category/anchor parity + smoke that all referenced glossary keys resolve. Optional `<RelatedFAQ>` component for the "Related FAQ →" footer in tooltips/popovers.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (read-only).
- **Estimated size:** small-to-medium — 1 new page (~250 LOC including markdown loader + category index), 5–6 markdown files (~200 lines of operator-facing prose total in the first pass), ~100 LOC of vitest. The content writing is the bulk of the work, not the implementation.

## Why not yet prioritized

The MVP1 path is "operator reads tutorial-first-study.md → runs the loop → ships PRs." The questions an FAQ would answer mostly surface *after* the operator has done that loop a few times — i.e., they're not blocking first-run success. Until the operator base is wider than the maintainer + a handful of design partners, every FAQ-shaped question can be answered in chat / Slack faster than it can be authored as a curated entry. Worth doing once routine support questions start repeating themselves.

Also worth deferring until [`chore_guides_glossary_route`](../chore_guides_glossary_route/idea.md) lands — the FAQ entries will reference glossary terms heavily, and having the glossary as a target for `[term](/guide/glossary#term)` deep links makes the FAQ content much richer.

## Relationship to other work

- **Sibling:** [`chore_guides_glossary_route`](../chore_guides_glossary_route/idea.md) — different content axis (Glossary = "what does X mean?", FAQ = "what should I do about X?"). The Glossary should land first because the FAQ deep-links into it.
- **Supersedes:** the stale "FAQs" mention in [`docs/08_guides/README.md`](../../../08_guides/README.md) line 3, which is currently aspirational with no concrete artifact.
- **Coordinates with:** the existing operator-facing runbooks under [`docs/03_runbooks/`](../../../03_runbooks/) (webhook debugging, PR-open debugging, agent debugging, judgment debugging) — those are SRE-level; the FAQ would link to them for operators who need to escalate.

## Process integration — keeping the FAQ current as features ship

FAQ entries are different from glossary entries in two important ways: (a) they're **operator-judgment-shaped** ("should I X?", "why is Y?", "when does Z?") rather than definitional, and (b) they tend to surface *during implementation* — when the implementer notices an edge case that operators will ask about — rather than at spec-time. That means the leverage points differ from the [Glossary route's process integration](../chore_guides_glossary_route/idea.md#process-integration--keeping-the-glossary-current-as-the-codebase-grows). **Recommendation: two coordinated edits, in leverage order.**

### 1. `.claude/skills/impl-execute/SKILL.md` — Step 2.5 (Tangential observations sweep) — primary catch-net

Step 2.5 is already a **BLOCKING** step before push, designed to flush noticed-but-uncaptured issues. It has 5 prompts today (pre-existing failures, flaky tests, deferred coverage, stale paths, "someday" thoughts). Add a 6th prompt explicitly shaped for FAQ candidates:

- **"Did I notice during implementation any operator-judgment-shaped question that has no canonical answer in the current docs?"** Examples: *"What happens if I X?"* / *"Should I trust Y in case Z?"* / *"My pipeline shows N — is that a bug or expected?"* If yes, either (a) file a focused `chore_faq_<slug>/idea.md` capturing the question + draft answer + the spec/AC citation that backs the answer, OR (b) if `chore_guides_faq` has already shipped, draft the entry directly under `docs/08_guides/faq/<category>.md` in this PR. Tooltips/glossary are NOT the right surface — they're definitional, not judgment-shaped.

This is the **single most leveraged edit** because Step 2.5 is where the implementer is already walking back through their session looking for things to capture. FAQ-shaped questions are exactly the kind of "I noticed but didn't act" item it's designed to catch.

### 2. `.claude/skills/impl-execute/SKILL.md` — Step 3 (Guide impact assessment) — feature-level coverage check

Step 3 already evaluates whether walkthrough guides need regeneration. Add a third class of impact:

- **"Does this feature introduce a new operator decision point** (e.g., a new status the operator must adjudicate, a new error code that requires a judgment call, a new metric that informs a tuning choice, a new failure mode that operators will hit and not know how to interpret)? If yes, evaluate whether an FAQ entry is needed in addition to (or instead of) a tooltip/glossary entry. The rubric: *tooltip if 1–2 sentences suffice; glossary if it's a definitional term; FAQ if the answer requires balancing trade-offs or citing operator context.*"

### Why not earlier in the pipeline (spec-gen / impl-plan-gen)?

We considered putting an FAQ check in `spec-gen` Step 3 (alongside the tooltip inventory in #11) and `impl-plan-gen` (alongside the tooltip plan requirement at line 111), but rejected both:

- **`spec-gen`** — operator-judgment questions are usually *discovered* during implementation, not predicted from the spec. The spec author can list anticipated questions but they tend to be too generic to be useful FAQ entries until the actual edge cases surface in code.
- **`impl-plan-gen`** — same reason as spec-gen. Pre-planning FAQ entries leads to either over-planning (entries that don't match real operator confusion) or hollow placeholders.

The right model is: spec/plan identify *anticipated* questions in their "edge cases" or "operator concerns" sections (which they already do); implementation **catches and captures** the actual ones via Step 2.5 + Step 3.

### What NOT to update

- **`spec-gen/SKILL.md`** — see above; the existing "edge cases" + "error flows" sections already serve as the anticipated-FAQ surface. No new check needed.
- **`impl-plan-gen/SKILL.md`** — same reasoning.
- **`bug-fix/SKILL.md`** — bug fixes routinely surface "ohh that's why" questions that *are* FAQ-shaped. But `/bug-fix` chains into `/impl-execute --ad-hoc` per SKILL.md line 769, which runs Step 2.5 + Step 3 in ad-hoc mode — so the catch-net already covers bug-fix output without a dedicated edit.
- **`guide-gen/SKILL.md`** — generates walkthrough screenshots, not FAQ entries.
- **`idea-preflight/SKILL.md`** — audits a *single* idea file against the codebase; not a general process gate.
- **A new `faq-gen` skill** — same reasoning as the parallel decision on the Glossary route. FAQ entries are short prose; the friction is *noticing* the question, not authoring it. Gates beat tools.

### Acceptance criterion for this idea

This idea is "done" when:
1. The `/guide/faq` route ships per "Proposed capabilities" above with the initial 15–20 curated entries, AND
2. The two `impl-execute` SKILL.md edits above are applied, AND
3. The next post-edit feature merge demonstrably runs the new questionnaire (verified by a one-line "FAQ delta: N entries added (or 'no operator-judgment surface added')" note in the PR description). Silence is acceptable when there's genuinely nothing to add; the discipline is the explicit assertion, not the count.
