# Phase 3 — `edit_template` LLM-suggested followups (stretch)

**Date:** 2026-05-23
**Status:** Idea — deferred from Phase 1 of `feat_digest_executable_followups` per `feature_spec.md` §3 Phase boundaries.
**Priority:** Backlog — likely out of MVP1 scope entirely; captured for record.
**Origin:** `feature_spec.md` §3 ("Out of scope" → Tier C) + sibling `idea.md` §"Tier C — template-edit suggestions".
**Depends on:** `feat_digest_executable_followups` Phase 1 (substrate) + likely Phase 2 (`swap_template` proves out the cross-template UX before edit-template stretches further). Also depends on a yet-to-be-designed template-edit review surface.

## Problem

Phase 1 ships `narrow`/`widen`/`text` and Phase 2 adds `swap_template` — all of which preserve template authoring as a strictly operator-driven activity. But the LLM can sometimes spot template-body improvements that no parameter tuning can reach: e.g., "add a `category^2` field-boost to the template body — your winning trials all came from categories with multiple matching terms."

Today templates are operator-authored only. Letting LLM suggestions flow into template-body edits requires a much larger trust-and-validation surface: changes to template body alter query rendering semantics, which is materially riskier than search-space narrowing.

## Proposed capabilities

### Tier C — `edit_template` discriminated-union kind

- **New FR:** Add `kind="edit_template"` to the `FollowupItem` discriminated union. Carries `{kind: "edit_template", rationale: str, template_id: str, body_patch: dict}` where `body_patch` is a JSON Patch (RFC 6902) or equivalent applied to the parent template's `body_jsonata` (or whichever template-body field is canonical at the time).
- **New FR:** Template-edit validation pipeline. The patched body MUST parse cleanly against the engine adapter's rendering layer (i.e., `ElasticAdapter.render(patched_body, sample_params)` succeeds) before the followup is persisted.
- **New FR:** Operator-mediated apply surface. NOT a "Run this followup" one-click — instead, "Open in template editor" that loads the patched body into the (yet-to-exist) template-editing UI for explicit review.
- **New FR:** Lineage capture on the template version (new). When the operator commits the edit, the new template version records `parent_template_id` + `derived_from_proposal_id` + `derived_from_followup_index`.

## Scope signals

- **Backend:** ~400+ LOC. New domain helper for body-patch application + validation + template-version lineage columns + migration + tests.
- **Frontend:** Large (~500+ LOC). Requires a template-editing UI surface that does NOT exist today (templates are file-based today; the in-tool editor is unbuilt).
- **Migration:** Yes — template-versions lineage columns.
- **Config:** None.
- **Audit events:** New event types `digest.template_edit_suggested` + `template_version.derived_from_followup`.

## Why deferred (likely beyond MVP1)

- **Template-body edits change query rendering semantics.** Materially different risk profile from search-space narrowing. Needs a real review surface, real validation, and operator trust that the LLM's edits don't silently break production templates.
- **No template-editing UI today.** Templates are file/JSON in the repo, edited in IDEs. Building an in-tool template editor is its own spec — likely MVP2 or later.
- **The Phase 1 + Phase 2 pair already covers the common case** of LLM-suggested followups. Edit-template is the long tail.
- **Trust model.** Operators haven't yet decided whether they trust LLM suggestions to modify the very thing that defines query behavior. Phase 1's success metrics (do operators actually click "Run this followup"? Do those studies win?) inform whether Phase 3 is worth the investment.

## Relationship to other work

- **Depends on Phase 1 + Phase 2 substrate.**
- **Depends on a template-editing UI surface** that does NOT yet exist — likely a separate feature (`feat_template_editor` or similar) before this can land.
- **Adjacent to `feat_agent_propose_search_space`** — same agent flow, different target (template body vs search space).
