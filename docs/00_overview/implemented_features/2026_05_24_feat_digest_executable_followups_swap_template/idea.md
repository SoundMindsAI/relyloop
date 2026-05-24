# `swap_template` LLM-suggested followups for the digest worker

**Date:** 2026-05-23 (originated as `phase2_idea.md` inside [`feat_digest_executable_followups/`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/idea.md); split into this standalone folder 2026-05-24 so it ships cleanly through `/pipeline --auto` with standard artifact names and a clean feature branch).

**Status:** Idea — ready for `/pipeline`.

**Priority:** P2 — actionable extension of [`feat_digest_executable_followups`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/idea.md) Phase 1 (Tier A, shipped 2026-05-24 as PR #225 squash `83c526f2`). All substrate is in place; this is a pure extension of the existing `FollowupItem` discriminated union with one new kind variant plus its UI surface.

**Origin:** [`feat_digest_executable_followups`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/feature_spec.md) §3 ("Out of scope" → Tier B) + sibling [`idea.md`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/idea.md) §"Tier B — `swap_template` followups". Originally captured as `phase2_idea.md` inside that folder; split into a standalone folder per the 2026-05-24 decision (see PR #227 for the sibling Phase-3 split to backlog, and the rationale for splitting deferred phases out before pipelining them in `impl-execute` Step 8.6).

**Depends on (all met):**
- [`feat_digest_executable_followups`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/idea.md) Phase 1 — **shipped 2026-05-24 as PR #225 squash `83c526f2`.** ✅ Substrate (Pydantic discriminated-union `FollowupItem`, JSONB `digests.suggested_followups` column, `studies.parent_proposal_id` + `parent_proposal_followup_index` lineage columns, `POST /api/v1/studies` `parent` body, "Run this followup" UI scaffolding, `useStudy(parent_study_id)` lazy prefetch) all in place.
- [`feat_agent_propose_search_space`](../../../00_overview/implemented_features/2026_05_21_feat_agent_propose_search_space/idea.md) — **shipped 2026-05-21 as PR #175 squash `5d29355`.** ✅ Provides `backend/app/domain/study/search_space_defaults.py` for the disjoint-set heuristic bounds.

## Problem

Phase 1 of `feat_digest_executable_followups` handles `narrow` / `widen` / `text` kinds — all within the **same query template**. But the LLM sometimes recognizes that a different template entirely is a better fit: e.g., parameter-importance is highly skewed (some declared params are dead weight), OR several winning trials cluster around a sub-set of params that map cleanly onto a different template's declared params. Today the operator has to notice this themselves; the LLM has no structured way to say "try template X instead."

## Proposed capabilities

### `swap_template` discriminated-union kind

- **New FR:** Add `kind="swap_template"` to the `FollowupItem` discriminated union (introduced by Phase 1 — joins the existing `narrow` / `widen` / `text` variants). The variant carries `{kind: "swap_template", rationale: str, template_id: str (UUIDv7, 36 chars), search_space: SearchSpace}`.
- **New FR:** Cross-template search-space remapping. New domain helper at `backend/app/domain/study/template_swap.py` computes:
  - **Intersection:** param names declared by both the parent template and the proposed swap-target template — copied from the LLM's `search_space` directly.
  - **Disjoint set:** param names declared by the swap-target but not the parent — assigned default heuristic bounds via [`backend/app/domain/study/search_space_defaults.py`](../../../../backend/app/domain/study/search_space_defaults.py) (already exists from `feat_agent_propose_search_space`).
  - **Dropped:** param names declared by the parent but not the swap-target — dropped silently with a structlog event.
- **New FR:** LLM prompt extension teaching the model when to suggest a swap (parameter-importance distribution skewed, OR winning trials cluster around a sub-set mappable onto a different template).
- **New FR:** UI surface — swap-template followups render with a side-by-side comparison of the two templates' `declared_params` before the operator commits. The "Run this followup" button pre-fills `template_id = <swap_target>` instead of the parent's template.
- **New FR:** The `parent_proposal_id` + `parent_proposal_followup_index` lineage from Phase 1 still applies; the child study's `template_id` differs from the parent's, which the lineage data makes explicit.

## Scope signals

- **Backend:** ~250 LOC. `template_swap.py` domain helper (~100) + extended `FollowupItem` discriminated union (~30) + LLM prompt update (~80) + tests (~50). **No new DB columns or migrations** — the JSONB column already accommodates the new shape.
- **Frontend:** ~200 LOC. Side-by-side template comparison component + extended "Run this followup" prefill for the swap kind + tests.
- **Migration:** None.
- **Config:** None.
- **Audit events:** Reuses the three pre-shaped MVP2 events from Phase 1; the `digest.followup_clicked` event's `followup_kind` field gains `swap_template` as a possible value.

## Why this is a separate feature (not Phase 1's scope)

- **Cross-template search-space remapping is a non-trivial new domain helper.** Phase 1 reuses the existing `SearchSpace` validator unchanged; this adds a new transformation layer. Out of Phase 1 scope by design.
- **UI surface for side-by-side template comparison is its own design decision.** Phase 1's diff-vs-parent renderer doesn't compose cleanly into a two-template comparison; new component required.
- **Value-after-Phase-1 framing.** Per the original phase boundaries, the intent was to ship Tier A and observe whether operators actually use "Run this followup" before investing in the cross-template variant. Phase 1 is now in operator hands — this folder is the trigger for shipping Tier B when the operator decides the substrate has earned the extension.

## Relationship to other work

- **Builds on [`feat_digest_executable_followups`](../../../00_overview/implemented_features/2026_05_24_feat_digest_executable_followups/idea.md) Phase 1 substrate** — discriminated-union schema, JSONB column, lineage columns, and "Run this followup" UI scaffolding all already landed.
- **Reuses [`backend/app/domain/study/search_space_defaults.py`](../../../../backend/app/domain/study/search_space_defaults.py)** from `feat_agent_propose_search_space` (shipped 2026-05-21) for the disjoint-set heuristic bounds.
- **Reuses `feat_create_study_search_space_builder` row primitives** (shipped 2026-05-20) for the cross-template comparison (when feasible).
- **Adjacent backlog item:** [`../../../02_product/planned_features/backlog_feat_digest_template_edit_followups/idea.md`](../../../02_product/planned_features/backlog_feat_digest_template_edit_followups/idea.md) — the Tier C `edit_template` extension, prefixed `backlog_` because its template-editor UI prerequisite doesn't exist. Promotes out of `backlog_` once this feature ships AND the editor lands.
