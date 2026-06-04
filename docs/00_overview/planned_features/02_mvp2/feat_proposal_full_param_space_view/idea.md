# Proposal page — show winning knobs in the context of the full available parameter space

**Date:** 2026-06-03 (preflight-refreshed 2026-06-04)
**Status:** Idea — user request during the same session as [`feat_overnight_final_solution`](../../implemented_features/2026_06_04_feat_overnight_final_solution/idea.md) (which merged 2026-06-04, PR #440)
**Priority:** P2
**Origin:** Operator question reviewing `/proposals/019e8f54-...`: *"when you see a proposal, you can see the knobs that were turned but it is still valuable information which knobs were not turned. Would it make sense to show the complete parameter space so that the user will see which knobs were turned within the context of all available knobs?"*
**Depends on:** None — uses existing schema only. Preflight 2026-06-04 confirmed the proposal detail page already fetches the relevant template's `declared_params` client-side (see [Cap 1 scope-signal note](#scope-signals)).

> **Priority guidance:** P2 — UX clarity improvement, not blocking anything. Inexpensive (no schema change, no new data) but a real upgrade to how operators reason about a proposal in context.

## Problem

The proposal detail page surfaces `config_diff` — the subset of parameters the study **tuned** — and the winning values for them. Today's example proposal carries `{boost: {from: 1.0, to: 2.5}}` and reads as "we tuned title boost." What it does not show: which other knobs *exist* on the same template that the study **did not** tune. The operator is left to guess whether the optimizer considered description boost, fuzziness, function-score decay, etc. and rejected them, or whether those knobs were simply not in the study's search space.

That gap matters because the proposal's own suggested follow-ups (`narrow` / `widen` / `swap_template`) frequently reference parameters that *weren't* in this study's search space — "Try varying `description.boost` next" reads disconnectedly without a visible reference list of "all knobs this template supports." Putting the tuned subset in the context of the full parameter space makes the follow-up cards self-explanatory and lets the operator reason about coverage at a glance.

## Proposed capabilities

### Cap 1 — Render the template's full parameter space on the proposal page

- On `/proposals/[id]`, add a panel (or extend the existing **`<ConfigDiffPanel>`** card titled "Config diff" at [`ui/src/components/proposals/config-diff-panel.tsx:63`](../../../../ui/src/components/proposals/config-diff-panel.tsx#L63)) that lists **every parameter the template declares** — i.e., all of `query_templates.declared_params` for `proposal.template_id`.
- For each parameter, show one of three visual states:
  - **Tuned (winning value)** — appears in `config_diff`. Show the winning value (and ideally the from→to delta from `config_diff`).
  - **Tuned (default-value winner)** — the param was in the study's search space but the optimizer landed back at the parent's prior value (rare but possible). Show the prior value and a subtle "no change" marker.
  - **Not in this study's search space** — declared on the template but the study didn't tune it. Show the parameter name + the template's declared type, with a "not tuned" marker (greyed, italic, or labeled). **NOTE (preflight 2026-06-04):** `query_templates.declared_params` is stored as a flat `Record<string, string>` mapping param name → type tag (`"float"` / `"int"` / `"categorical"`) — see the typed UI shape at [`suggested-followups-panel.tsx:61`](../../../../ui/src/components/proposals/suggested-followups-panel.tsx#L61). The template **does NOT** persist per-param bounds or defaults; those live on each study's `search_space` JSONB. If the panel wants to show bounds/defaults for un-tuned params, that data is derivable only from `parent_study.search_space` (which is already on the page — see Scope signals), not from the template itself.
- The grouping makes the proposal's tuned subset visually distinct from the un-tuned-but-available subset.

### Cap 2 — Connect "not tuned" knobs to the follow-up cards

- When a follow-up card references a parameter that appears in the "not tuned" group (e.g. `swap_template` whose target tunes `description_boost`, or a text suggestion saying "Try varying X next"), the parameter name in the un-tuned list should be clickable/anchored so the operator can see "this knob is the one the follow-up is pointing at."
- Light-weight UX: don't over-engineer the linkage. A shared `data-param-name` attribute the cards highlight on hover is enough.
- **Coordination note (preflight 2026-06-04):** [`<SuggestedFollowupsPanel>`](../../../../ui/src/components/proposals/suggested-followups-panel.tsx) already renders a parent-vs-swap-target `declared_params` diff for `swap_template` cards (see lines 250-291) under the existing `proposal.followup_declared_params_diff` glossary key. The new "not tuned" rendering on the proposal's own panel should align visually with that pattern — same param-name typography, ideally the same colour token for the "added by swap target" / "not in this template" states — so operators don't have to re-learn the grouping.

### Cap 3 — Optional: surface the same view on the study detail page

- The study detail page already shows trial scatter / parameter-importance — those are the *internal* lens on what was tuned. The same "winning knobs in the context of the full template" view would be a complementary *outward* lens.
- Defer this until Cap 1 + Cap 2 prove out. Same data, different mount point; could live behind a tab.

## Scope signals

- **Backend:** **None required.** Preflight 2026-06-04 confirmed the proposal detail page ([`ui/src/app/proposals/[id]/page.tsx:183`](../../../../ui/src/app/proposals/[id]/page.tsx#L183)) already pays for `useTemplate(parentStudy.data?.template_id)` to feed `<SuggestedFollowupsPanel>`'s swap-target diff. Because every chain-link proposal's `template_id` mirrors its parent study's `template_id` (the orchestrator persists `template_id` on the child study; see [`backend/workers/auto_followup.py`](../../../../backend/workers/auto_followup.py)), the **same** `parentTemplateQuery.data.declared_params` already covers the proposal's own template — no second request, no payload change. The earlier wording ("include in the proposal payload to save a round-trip") is obsolete: there is no round-trip to save.
- **Frontend:** New (or extended) panel on `/proposals/[id]`. Logic is pure set algebra on `declared_params.keys()` (already on the page via `parentTemplateQuery.data`) vs `config_diff.keys()` — no client-side computation beyond a `.map()`. Possibly extends `ui/src/components/proposals/`. Bounds/defaults for un-tuned params (if Q2 lands the "show type + bounds" variant) come from `parentStudy.data.search_space` (also already on the page).
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A — read-only UI.

## Why deferred / not yet prioritized

The proposal page works correctly today — it just doesn't give the operator the full picture in one glance. The fix is small but not blocking any pipeline, incident, or daily cost. Captured here so it lands in the MVP2 polish wave alongside the other proposal-UI improvements rather than getting smuggled into an unrelated PR.

## Relationship to other work

- **Compounds value of** [`feat_overnight_final_solution`](../../implemented_features/2026_06_04_feat_overnight_final_solution/idea.md) (PR #440, merged 2026-06-04) and the morning-summary pair ([`feat_overnight_final_solution_phase2`](../../implemented_features/2026_06_04_feat_overnight_final_solution_phase2/idea.md), PR #442; [`feat_overnight_studies_summary_card`](../../implemented_features/2026_06_04_feat_overnight_studies_summary_card/idea.md), PR #444). Now that the overnight chain swaps templates and tunes different knobs automatically, the proposal page IS the morning artifact operators read. The "what did the optimizer leave on the table" lens makes that artifact self-explanatory.
- **Coordinates with** [`feat_overnight_final_solution_phase3`](../feat_overnight_final_solution_phase3/idea.md) (idea-stage; P2) — that idea marks non-winning chain links' proposals as `superseded` so the morning view is unambiguously "one answer." This idea makes that one-answer proposal richer; the two could ship together or in either order.
- **Reuses pattern from** [`<SuggestedFollowupsPanel>`'s declared-params diff](../../../../ui/src/components/proposals/suggested-followups-panel.tsx) — see Cap 2 coordination note.
- **Consumes** existing data only: `proposals.template_id`, `proposals.config_diff`, `query_templates.declared_params`. No new tables, no migration.

## Open questions (resolve at spec time)

- **Q1** — Single panel or two stacked panels (tuned vs not-tuned)? Recommended: one panel with visual grouping; two panels feels heavyweight.
- **Q2** — Display the *type* (float / int / categorical) for un-tuned params, or also their bounds? Recommended: show type from `declared_params` plus the parent study's `search_space` bounds when the param was in the search space; for params *outside* the search space entirely (declared on the template but never tuned in this study), show type only — the template itself stores no bounds. (Preflight 2026-06-04 corrected the earlier "template's stated bounds/default" framing: the template only stores `Record<string, type>`; bounds live on the study's `search_space`.)
- **Q3** — Should `swap_template` follow-ups also call out which params the swap target tunes that the current template doesn't (a third group)? Partially already addressed: `<SuggestedFollowupsPanel>` renders a parent-vs-swap-target `declared_params` diff for swap_template cards today (suggested-followups-panel.tsx:250-291). The remaining question is whether the *new* "full param space" panel should ALSO show the swap target's declared params inline (instead of only on the swap-template card). Recommended: leave that to the swap-template card; the new panel scopes to *this* proposal's template only, keeping the mental model "this is what THIS proposal had to work with."
