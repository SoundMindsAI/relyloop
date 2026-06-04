# Phase 2 — Morning summary card + study-detail strategy line

**Date:** 2026-06-03
**Status:** Idea — deferred Phase 2 from `feat_overnight_final_solution` Phase 1 spec
**Priority:** P2
**Origin:** Carried out of `docs/00_overview/implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md` §3 "Phase boundaries" + §19 D-5/D-15. Phase 1 delivered cross-knob/cross-template autonomous exploration with the rollup data already available via the existing `/chain` endpoint; Phase 2 polishes the morning-review surface.
**Depends on:** `feat_overnight_final_solution` Phase 1 (now at `implemented_features/2026_06_04_feat_overnight_final_solution/`) must be merged first.

> **Priority guidance:** P2 — UX polish. Not blocking the capability the Phase 1 spec delivers; lifts the morning-review experience from "open the study detail page → scroll to the chain panel" to "one card at the top says here's the answer."

## Problem

After Phase 1 ships, an operator who picks `follow_suggestions` overnight wakes up to:

- a chain of up to 6 studies, each with its own auto-created `pending` proposal;
- the existing `/chain` endpoint that already rolls up `best_link_id` + `cumulative_lift` + `proposal_id_for_best_link` + `stop_reason`;
- the existing chain panel under `/studies/{id}` that surfaces the rolled-up summary and the new per-link strategy badges (FR-7).

What's missing in Phase 1: a **dedicated morning surface** that says *"explored 4 strategies overnight, settled on swap_template to function-score-v1, +18% vs baseline, here's the PR to ship"* — in one card, surfacing the **path** (which knobs/templates were explored, in order) alongside the winner. The chain panel surfaces the data, but it's mid-page and panel-shaped; a top-of-page summary card would compress the morning review into a single glance.

Also deferred from Phase 1: the **strategy read-only line on the study detail page** (Phase 1 OQ-2 / D-15) — an at-a-glance "this study is running under `follow_suggestions`" cue that lives on the detail page alongside the existing config summary. Defer rationale: redundant with the per-link badges in Phase 1's chain panel; revisit if operator feedback says the badges are too far down the page.

## Proposed capabilities

### Cap 1 — Top-of-page "Overnight result" card on `/studies/{id}` when the chain terminated

- New card mounted above `LinkedEntitiesRow` on `/studies/{study_id}` when `chain.links.length >= 2` AND `chain.stop_reason in {"no_lift", "depth_exhausted", "budget", "parent_failed", "cancelled"}` (i.e., terminal chain).
- Content:
  - Headline: *"Overnight exploration complete — {N} studies, +{X.YY}% lift"*.
  - One-line path summary: *"Explored: {kind₁} → {kind₂} → {kind₃}"* using the per-link `selected_followup_kind` values from `StudyChainLink` (Phase 1 FR-6).
  - Best config link → `/proposals/{proposal_id_for_best_link}` (already exists in `/chain` response).
  - Total lift vs anchor baseline (already computed by `/chain`).
  - Reason it stopped (the existing `stop_reason` mapped to a friendly phrase).

### Cap 2 — `/studies` list "ran while away" badge

- Coordinates with sibling [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md) (already in 02_mvp2). The two ideas overlap — the morning card on the detail page (Cap 1 here) is the deep view; the index-page badge from the sibling idea is the discoverability cue. Resolve at Phase 2 spec time whether to fold them or coordinate them.

### Cap 3 — Strategy read-only line on the study detail page

- When the local study has `config.auto_followup_strategy = "follow_suggestions"`, surface a one-line "Strategy: Try suggested follow-ups" badge in the existing study-detail config summary (above or beside `LinkedEntitiesRow`).
- For `"narrow"` / `None` / `"narrow"` (default), surface nothing (or a subtle "Strategy: Refine same knobs" line, depending on UX call).

### Cap 4 — Narrative summary in the morning card

- Optional: a short natural-language paragraph in the card summarizing what the chain found. Could reuse the existing digest narrative of the winning link OR generate a chain-level narrative via a small LLM call. Defer the LLM-call decision to spec time — likely "no new LLM call, reuse the winning digest's narrative."

## Scope signals

- **Backend:** No new endpoint required. `/chain` already exposes `best_link_id`, `cumulative_lift`, `proposal_id_for_best_link`, `stop_reason`, and per-link `selected_followup_kind` (from Phase 1 FR-6). Cap 4's narrative reuse just reads `digests.narrative` for the best link.
- **Frontend:** New `OvernightResultCard` component (`ui/src/components/studies/overnight-result-card.tsx`) mounted on `/studies/{id}`. Cap 3 adds a line to the existing study-detail config summary. Both consume data already returned by existing endpoints.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A pre-MVP3.

## Why deferred from Phase 1

Phase 1's job was the **capability** — let the autopilot explore across knobs and templates autonomously. The data needed for the morning rollup card is already exposed by the existing `/chain` endpoint plus Phase 1's additive `selected_followup_kind` field. The card itself is a UX polish that can be designed once operators have used Phase 1 for a few cycles and we know what summary shape lands best. Shipping Phase 2 with Phase 1 would force UX decisions (card placement, copy, narrative source) before any operator has used the capability — a worse design loop than "ship the capability, observe usage, design the card."

## Relationship to other work

- **Builds on** [`feat_overnight_final_solution`](../../implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md) Phase 1 — depends on its `selected_followup_kind` field and the strategy persistence.
- **Coordinates with** [`feat_overnight_studies_summary_card`](../feat_overnight_studies_summary_card/idea.md) — index-page "ran while away" surface; resolve overlap at Phase 2 spec time.
- **Composes with** [`feat_study_convergence_indicator`](../../implemented_features/2026_05_31_feat_study_convergence_indicator/feature_spec.md) — the morning card may want to surface the winning link's convergence verdict too.

## Open questions

- **Q1** — Mount point: top of `/studies/{id}` (above all panels) vs a new tab? Recommend top-of-page banner card; tabs hide information.
- **Q2** — Card visibility predicate: every terminated chain, or only `follow_suggestions` chains? Recommend every terminated chain ≥ 2 links — the rollup is useful for narrow-only chains too.
- **Q3** — Fold Cap 3 (strategy line) into Cap 1 (card) or keep separate? Recommend keep separate — Cap 1 fires only on terminal chains, Cap 3 also helps mid-chain operators.
- **Q4** — Fold with `feat_overnight_studies_summary_card`? Spec-time decision.
