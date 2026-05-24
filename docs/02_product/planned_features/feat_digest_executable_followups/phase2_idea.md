# Phase 2 — `swap_template` LLM-suggested followups

**Date:** 2026-05-23
**Status:** Idea — deferred from Phase 1 of `feat_digest_executable_followups` per `feature_spec.md` §3 Phase boundaries.
**Priority:** P2 — actionable extension once Tier A is in operator hands and the team has data on whether `narrow`/`widen` followups produce wins.
**Origin:** `feature_spec.md` §3 ("Out of scope" → Tier B) + sibling `idea.md` §"Tier B — `swap_template` followups".
**Depends on:** `feat_digest_executable_followups` Phase 1 (Tier A) shipped first. Builds on the `FollowupItem` discriminated-union + DB column substrate that Phase 1 lays down.

## Problem

Phase 1 handles `narrow` / `widen` / `text` kinds — all within the **same query template**. But the LLM sometimes recognizes that a different template entirely is a better fit: e.g., parameter-importance is highly skewed (some declared params are dead weight), OR several winning trials cluster around a sub-set of params that map cleanly onto a different template's declared params. Today the operator has to notice this themselves; the LLM has no structured way to say "try template X instead."

## Proposed capabilities

### Tier B — `swap_template` discriminated-union kind

- **New FR:** Add `kind="swap_template"` to the `FollowupItem` discriminated union (alongside the Phase 1 `narrow`/`widen`/`text`). The variant carries `{kind: "swap_template", rationale: str, template_id: str (UUIDv7, 36 chars), search_space: SearchSpace}`.
- **New FR:** Cross-template search-space remapping. New domain helper at `backend/app/domain/study/template_swap.py` computes:
  - Intersection: param names declared by both the parent template and the proposed swap-target template — copied from the LLM's `search_space` directly.
  - Disjoint set: param names declared by the swap-target but not the parent — assigned default heuristic bounds via `backend/app/domain/study/search_space_defaults.py` (already exists from `feat_agent_propose_search_space`).
  - Dropped: param names declared by the parent but not the swap-target — dropped silently with a structlog event.
- **New FR:** LLM prompt extension teaching the model when to suggest a swap (parameter-importance distribution skewed, OR winning trials cluster around a sub-set mappable onto a different template).
- **New FR:** UI surface — swap-template followups render with a side-by-side comparison of the two templates' `declared_params` before the operator commits. The "Run this followup" button pre-fills `template_id = <swap_target>` instead of the parent's template.
- **New FR:** The `parent_proposal_id` + `parent_proposal_followup_index` lineage from Phase 1 still applies; the child study's `template_id` differs from the parent's, which the lineage data makes explicit.

## Scope signals

- **Backend:** ~250 LOC. `template_swap.py` domain helper (~100) + extended `FollowupItem` discriminated union (~30) + LLM prompt update (~80) + tests (~50). No new DB columns or migrations.
- **Frontend:** ~200 LOC. Side-by-side template comparison component + extended "Run this followup" prefill for the swap kind + tests.
- **Migration:** None — JSONB column already accommodates the new shape.
- **Config:** None.
- **Audit events:** Reuses the three pre-shaped MVP2 events from Phase 1; the `digest.followup_clicked` event's `followup_kind` field gains `swap_template` as a possible value.

## Why deferred

- **Cross-template search-space remapping is a non-trivial new domain helper.** Phase 1 reuses the existing `SearchSpace` validator unchanged; Phase 2 adds a new transformation layer. Out of Phase 1 scope.
- **UI surface for side-by-side template comparison is its own design decision.** Phase 1's diff-vs-parent renderer doesn't compose cleanly into a two-template comparison; new component required.
- **Value depends on Phase 1 success.** Until we ship Tier A and operators actually use "Run this followup," investing in the cross-template variant is speculative.

## Relationship to other work

- **Depends on Phase 1 substrate** — the discriminated-union schema, JSONB column, lineage columns, and "Run this followup" UI scaffolding all land in Phase 1.
- **Reuses `backend/app/domain/study/search_space_defaults.py`** from `feat_agent_propose_search_space` (shipped 2026-05-21) for the disjoint-set heuristic bounds.
- **Reuses `feat_create_study_search_space_builder` row primitives** for the cross-template comparison (when feasible).
