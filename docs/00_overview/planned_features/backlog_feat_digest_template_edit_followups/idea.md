# `edit_template` LLM-suggested followups for the digest worker

**Label:** `backlog` — folder is prefixed `backlog_` per operator convention (2026-05-24): captured, not in the active prioritized backlog; not surfaced by `/pipeline status` or the MVP1 dashboard tables. Promote out of `backlog_` (rename to `feat_digest_template_edit_followups/`) when the listed prerequisites are met.

**Date:** 2026-05-23 (originated as `phase3_idea.md` inside [`feat_digest_executable_followups/`](../../implemented_features/2026_05_24_feat_digest_executable_followups/idea.md); split into this standalone backlog folder 2026-05-24 because Phase 3 is genuinely beyond MVP1 scope and was blocking Phase 1's finalization).

**Status:** Backlog — captured for record.

**Priority:** Backlog — likely out of MVP1 scope entirely. Promote to P2 once the template-editor UI surface exists AND `feat_digest_executable_followups` Phase 2 (`swap_template`) has shipped + produced evidence that operators trust LLM-suggested cross-template moves.

**Origin:** [`feat_digest_executable_followups`](../../implemented_features/2026_05_24_feat_digest_executable_followups/feature_spec.md) §3 ("Out of scope" → Tier C) + sibling [`idea.md`](../../implemented_features/2026_05_24_feat_digest_executable_followups/idea.md) §"Tier C — template-edit suggestions". Originally captured as `phase3_idea.md` inside that folder; split into a standalone backlog folder per the 2026-05-24 finalization decision so that Phase 1's `implemented_features/` move isn't blocked by future-work tracking.

**Depends on (hard blockers; promote out of `backlog_` only when all are met):**
- [`feat_digest_executable_followups`](../../implemented_features/2026_05_24_feat_digest_executable_followups/idea.md) Phase 1 (substrate) — **shipped 2026-05-24 as PR #225 squash `83c526f2`.** ✅
- [`feat_digest_executable_followups_swap_template`](../feat_digest_executable_followups_swap_template/idea.md) (Phase 2 (`swap_template` — proves out cross-template UX before edit-template stretches further). ⏳ deferred.
- A template-editing UI surface that does NOT yet exist — likely a separate feature (`feat_template_editor` or similar) before this can land. ⏳ not yet captured as its own idea.

## Problem

[`feat_digest_executable_followups`](../../implemented_features/2026_05_24_feat_digest_executable_followups/idea.md) Phase 1 ships `narrow`/`widen`/`text` and Phase 2 adds `swap_template` — all of which preserve template authoring as a strictly operator-driven activity. But the LLM can sometimes spot template-body improvements that no parameter tuning can reach: e.g., "add a `category^2` field-boost to the template body — your winning trials all came from categories with multiple matching terms."

Today templates are operator-authored only. Letting LLM suggestions flow into template-body edits requires a much larger trust-and-validation surface: changes to template body alter query rendering semantics, which is materially riskier than search-space narrowing.

## Proposed capabilities

### `edit_template` discriminated-union kind

- **New FR:** Add `kind="edit_template"` to the `FollowupItem` discriminated union (introduced by Phase 1, extended by Phase 2). Carries `{kind: "edit_template", rationale: str, template_id: str, body_patch: dict}` where `body_patch` is a JSON Patch (RFC 6902) or equivalent applied to the parent template's `body_jsonata` (or whichever template-body field is canonical at the time).
- **New FR:** Template-edit validation pipeline. The patched body MUST parse cleanly against the engine adapter's rendering layer (i.e., `ElasticAdapter.render(patched_body, sample_params)` succeeds) before the followup is persisted.
- **New FR:** Operator-mediated apply surface. NOT a "Run this followup" one-click — instead, "Open in template editor" that loads the patched body into the (yet-to-exist) template-editing UI for explicit review.
- **New FR:** Lineage capture on the template version (new). When the operator commits the edit, the new template version records `parent_template_id` + `derived_from_proposal_id` + `derived_from_followup_index`.

## Scope signals

- **Backend:** ~400+ LOC. New domain helper for body-patch application + validation + template-version lineage columns + migration + tests.
- **Frontend:** Large (~500+ LOC). Requires a template-editing UI surface that does NOT exist today (templates are file-based today; the in-tool editor is unbuilt).
- **Migration:** Yes — template-versions lineage columns.
- **Config:** None.
- **Audit events:** New event types `digest.template_edit_suggested` + `template_version.derived_from_followup`.

## Why this is backlog (likely beyond MVP1)

- **Template-body edits change query rendering semantics.** Materially different risk profile from search-space narrowing. Needs a real review surface, real validation, and operator trust that the LLM's edits don't silently break production templates.
- **No template-editing UI today.** Templates are file/JSON in the repo, edited in IDEs. Building an in-tool template editor is its own spec — likely MVP2 or later. Until that lands, this feature has no surface to render against.
- **The Phase 1 + Phase 2 pair already covers the common case** of LLM-suggested followups. Edit-template is the long tail.
- **Trust model.** Operators haven't yet decided whether they trust LLM suggestions to modify the very thing that defines query behavior. Phase 1's success metrics (do operators actually click "Run this followup"? Do those studies win?) inform whether this is worth the investment.

## Promotion criteria — when to rename this folder out of `backlog_`

Rename to `feat_digest_template_edit_followups/` (drop the `backlog_` prefix) when **all** of the following are true:
1. `feat_digest_executable_followups` Phase 2 (`swap_template`) has shipped AND produced ≥1 month of operator usage data showing positive lift on the cross-template suggestions.
2. A template-editing UI surface exists (separate `feat_template_editor` or equivalent has shipped).
3. The operator team has explicitly green-lit LLM-suggested template-body edits as in-scope.

## Relationship to other work

- **Depends on [`feat_digest_executable_followups`](../../implemented_features/2026_05_24_feat_digest_executable_followups/idea.md) Phase 1 + Phase 2 substrate** (Phase 1 shipped 2026-05-24; Phase 2 still deferred via `phase2_idea.md` in that folder).
- **Depends on a template-editing UI surface** that does NOT yet exist — likely a separate feature (`feat_template_editor` or similar) before this can land. That feature isn't even captured as its own idea yet; before promoting this folder out of `backlog_`, the operator should first scope and ship the editor.
- **Adjacent to [`feat_agent_propose_search_space`](../../implemented_features/2026_05_21_feat_agent_propose_search_space/idea.md)** — same agent flow, different target (template body vs search space).
