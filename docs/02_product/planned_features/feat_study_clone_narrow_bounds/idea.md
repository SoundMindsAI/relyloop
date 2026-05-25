# Clone study — "narrow bounds" smart-rewrite action

**Date:** 2026-05-24
**Status:** Idea — deferred follow-up of [`feat_study_clone_from_previous`](../feat_study_clone_from_previous/) (per that spec's locked D-3).
**Priority:** P2 — "exploit, don't explore" iteration mode. Unblocked once `feat_study_clone_from_previous` ships.
**Origin:** [`feat_study_clone_from_previous/feature_spec.md`](../feat_study_clone_from_previous/feature_spec.md) §3 "Out of scope", §19 D-3 + OQ-1. Split out of the v1 idea after the preflight + spec cycles agreed bundling would balloon the v1 review surface for marginal additional value.
**Depends on:** `feat_study_clone_from_previous` (v1 must ship first — this builds on the same `?clone_from` deep-link + prefill helper + cloneSource UI metadata).

## Problem

`feat_study_clone_from_previous` v1 ships verbatim-copy + editable-fields. The next iteration friction is: after cloning, the engineer must manually narrow the `search_space` bounds around the best-trial values (read from the source study's winning trial or the proposal's recommended config). Today that's another JSON edit; the "exploit don't explore" mode is the most common follow-up shape per the relevance-tuning loop's UX review (2026-05-19).

## Proposed capability

### Checkbox on Step 4 (search space) of the cloned modal

- **Label:** "Narrow bounds around the source study's winning params (±20%)"
- **Visibility:** only when `initialValues.cloneSource` is present (the v1 surface — never on the bare "New study" flow).
- **Default:** unchecked. The engineer opts in.
- **When checked:** the prefilled `search_space_text` JSON is rewritten so each `low/high` clamps to ±20% around the best-trial's value for that param. Read from `proposals[study_id].config` (winning config) or `trials.best_trial_id` (winning trial's params). Pure-frontend transformation; no backend support needed (the source's best-trial data is already exposed via `GET /api/v1/studies/{id}` and `GET /api/v1/studies/{id}/trials/{best_trial_id}` or the proposal endpoint).

### Optional: read-only "best trial params" reference panel

- Per `feat_study_clone_from_previous` OQ-1. A collapsed panel on Step 4 showing the source's best-trial params as a read-only reference table so the engineer can eyeball "narrow around these" before opting in.
- Decide at spec time: bundle or split. Recommended default: bundle into this follow-up (the reference panel is tightly coupled to the smart-rewrite UX — both need the same data fetches).

## Scope signals

- **Backend:** ~0 LOC. Best-trial data is already exposed.
- **Frontend:** ~120 LOC. Smart-rewrite helper (`narrowBoundsAroundWinner`) + UI checkbox + reference panel + vitest for the rewrite helper + one Playwright case that clones → narrows → submits → asserts the resulting `search_space` matches the ±20% clamp shape.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none (pre-MVP2).

## Why deferred

`feat_study_clone_from_previous` v1 already ships ~210 LOC across backend + frontend + 4 test layers. Bundling the smart-rewrite would have added ~60 LOC + new test surface (rewrite logic edge cases — what if a param has no best-trial value? what about non-numeric params like `tie_breaker`? what about params not present in the source's search_space?). The v1 review surface is already large; splitting keeps each PR reviewable and lets the team validate the manual-clone usage signal before committing to the smart-rewrite UX. Per the project's "tangential discoveries" rubric, the implementation path here exceeds 60 minutes once edge-case tests are accounted for, so it qualifies as a genuine follow-up rather than an inline addition.

## Open questions for /spec-gen

- **OQ-N1:** What's the right rewrite for a param with no best-trial value (e.g., the param was added to `search_space` after the winning trial was scored)? Options: skip (leave bounds untouched), or clamp to a default range. Recommended default: skip.
- **OQ-N2:** Non-numeric params (e.g., categorical `tie_breaker` choices)? Recommended default: leave untouched; "narrow" only meaningfully applies to numeric ranges.
- **OQ-N3:** Should the checkbox label show the actual ±X% value derived from the source's metric variance (smart) or the fixed ±20% (simple)? Recommended default: fixed 20% for v1 of this follow-up; smart-variance is a v2 elaboration.

## Relationship to other work

- **Hard depends on** `feat_study_clone_from_previous` (must ship first; this extends its surface).
- **Independent of** `feat_agent_propose_search_space` (if/when written) — agent-proposed search spaces are a separate prefill source; both could coexist as different opt-in modes on Step 4.
