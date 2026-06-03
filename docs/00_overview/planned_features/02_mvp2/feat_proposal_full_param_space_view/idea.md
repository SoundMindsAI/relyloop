# Proposal page — show winning knobs in the context of the full available parameter space

**Date:** 2026-06-03
**Status:** Idea — user request during the same session as `feat_overnight_final_solution`
**Priority:** P2
**Origin:** Operator question reviewing `/proposals/019e8f54-...`: *"when you see a proposal, you can see the knobs that were turned but it is still valuable information which knobs were not turned. Would it make sense to show the complete parameter space so that the user will see which knobs were turned within the context of all available knobs?"*
**Depends on:** None — uses existing schema only.

> **Priority guidance:** P2 — UX clarity improvement, not blocking anything. Inexpensive (no schema change, no new data) but a real upgrade to how operators reason about a proposal in context.

## Problem

The proposal detail page surfaces `config_diff` — the subset of parameters the study **tuned** — and the winning values for them. Today's example proposal carries `{boost: {from: 1.0, to: 2.5}}` and reads as "we tuned title boost." What it does not show: which other knobs *exist* on the same template that the study **did not** tune. The operator is left to guess whether the optimizer considered description boost, fuzziness, function-score decay, etc. and rejected them, or whether those knobs were simply not in the study's search space.

That gap matters because the proposal's own suggested follow-ups (`narrow` / `widen` / `swap_template`) frequently reference parameters that *weren't* in this study's search space — "Try varying `description.boost` next" reads disconnectedly without a visible reference list of "all knobs this template supports." Putting the tuned subset in the context of the full parameter space makes the follow-up cards self-explanatory and lets the operator reason about coverage at a glance.

## Proposed capabilities

### Cap 1 — Render the template's full parameter space on the proposal page

- On `/proposals/[id]`, add a panel (or extend the existing "Recommended config" panel) that lists **every parameter the template declares** — i.e., all of `query_templates.declared_params` for `proposal.template_id`.
- For each parameter, show one of three visual states:
  - **Tuned (winning value)** — appears in `config_diff`. Show the winning value (and ideally the from→to delta from `config_diff`).
  - **Tuned (default-value winner)** — the param was in the study's search space but the optimizer landed back at the parent's prior value (rare but possible). Show the prior value and a subtle "no change" marker.
  - **Not in this study's search space** — declared on the template but the study didn't tune it. Show the parameter name + the template's default/type, with a "not tuned" marker (greyed, italic, or labeled).
- The grouping makes the proposal's tuned subset visually distinct from the un-tuned-but-available subset.

### Cap 2 — Connect "not tuned" knobs to the follow-up cards

- When a follow-up card references a parameter that appears in the "not tuned" group (e.g. `swap_template` whose target tunes `description_boost`, or a text suggestion saying "Try varying X next"), the parameter name in the un-tuned list should be clickable/anchored so the operator can see "this knob is the one the follow-up is pointing at."
- Light-weight UX: don't over-engineer the linkage. A shared `data-param-name` attribute the cards highlight on hover is enough.

### Cap 3 — Optional: surface the same view on the study detail page

- The study detail page already shows trial scatter / parameter-importance — those are the *internal* lens on what was tuned. The same "winning knobs in the context of the full template" view would be a complementary *outward* lens.
- Defer this until Cap 1 + Cap 2 prove out. Same data, different mount point; could live behind a tab.

## Scope signals

- **Backend:** No change required. `proposal.template_id` is already on the proposal; the proposal detail endpoint can include the template's `declared_params` in its response payload (one additional column read on the existing JOIN, or a separate `GET /api/v1/query-templates/{id}` call from the UI). Lightly favor including it in the proposal payload to keep the page round-trip count at 1.
- **Frontend:** New (or extended) panel on `/proposals/[id]`. Logic is pure set algebra on `declared_params.keys()` vs `config_diff.keys()` — no client-side computation beyond a `.map()`. Possibly extends `ui/src/components/proposals/`.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A — read-only UI.

## Why deferred / not yet prioritized

The proposal page works correctly today — it just doesn't give the operator the full picture in one glance. The fix is small but not blocking any pipeline, incident, or daily cost. Captured here so it lands in the MVP2 polish wave alongside the other proposal-UI improvements rather than getting smuggled into an unrelated PR.

## Relationship to other work

- **Adjacent to** [`feat_overnight_final_solution`](../feat_overnight_final_solution/idea.md) (this session) — when the overnight chain can swap templates / tune different knobs automatically, the proposal page becomes *the* artifact operators read in the morning. Making it self-explanatory (this idea) compounds the value of the autonomous-exploration work.
- **Adjacent to** [`feat_proposal_full_param_space_view`'s sibling] — none currently.
- **Consumes** existing data only: `proposals.template_id`, `proposals.config_diff`, `query_templates.declared_params`. No new tables, no migration.

## Open questions (resolve at spec time)

- **Q1** — Single panel or two stacked panels (tuned vs not-tuned)? Recommended: one panel with visual grouping; two panels feels heavyweight.
- **Q2** — Display the *type* (float / int / categorical) for un-tuned params, or just the name? Recommended: show type + the template's stated bounds/default — that's the most useful framing of "what could have been tuned."
- **Q3** — Should `swap_template` follow-ups also call out which params the swap target tunes that the current template doesn't (a third group)? Probably yes, but lower priority than Cap 1 + Cap 2.
