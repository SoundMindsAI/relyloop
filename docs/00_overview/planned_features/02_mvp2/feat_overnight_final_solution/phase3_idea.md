# Phase 3 — Proposal `superseded` status for non-winning chain links

**Date:** 2026-06-03
**Status:** Idea — deferred Phase 3 from `feat_overnight_final_solution` Phase 1 spec
**Priority:** Backlog
**Origin:** Carried out of `feat_overnight_final_solution/feature_spec.md` §3 "Phase boundaries" + §19 D-8. Phase 1 ships the cross-knob exploration capability and leans on `best_link_id` + `proposal_id_for_best_link` from the existing `/chain` endpoint to surface the morning artifact as a single proposal. Phase 3 polishes the `/proposals` index by marking non-winning chain links' proposals `superseded` so the morning view is unambiguously "one answer."
**Depends on:** `feat_overnight_final_solution` Phase 1 must be merged first. Independent of Phase 2 (the morning summary card).

> **Priority guidance:** Backlog — defer-until-incident. The Phase 1 capability does not require this. File once an operator (or design partner) reports `/proposals` clutter as friction during morning review.

## Problem

When `follow_suggestions` runs a 4-link chain, today's proposal-creation logic ([`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py) `_on_study_complete`) creates **one `pending` proposal per completed link** — yielding up to 6 proposals (anchor + 5 descendants) in `/proposals`. Phase 1 surfaces a single "best" via `best_link_id` + `proposal_id_for_best_link` on `/chain`, but the index page still shows all 6 as `pending`. The non-winning links' proposals dead-end the operator: they're real `pending` rows but shipping any of them would discard the chain's winning insight.

Phase 3 marks those non-winning proposals `superseded` so:

- the `/proposals` index can hide or visually de-emphasize them by default;
- the `pending` status accurately means "ready to ship, no better alternative known";
- audit trails preserve the full chain history (superseded ≠ deleted).

## Proposed capabilities

### Cap 1 — Add `superseded` to the `proposals.status` CHECK constraint

- **Migration:** alter the CHECK on `proposals.status` to `IN ('pending', 'pr_opened', 'pr_merged', 'rejected', 'superseded')`. Mirror in `Proposal.__table_args__` at [`backend/app/db/models/proposal.py:42`](../../../../backend/app/db/models/proposal.py#L42).
- New value semantics: a `pending` proposal that the system decided is dominated by a sibling chain link's proposal. Not operator-rejected; not auto-deleted; not shipped.
- Allowed state transitions: `pending → superseded` (auto by chain-rollup), `superseded → pending` (operator action via UI, when they explicitly want to ship the runner-up).

### Cap 2 — Auto-supersede non-winning chain links' proposals on chain termination

- On the chain-termination signal (definable as: the tail link reaches a terminal status AND `stop_reason ∈ {"depth_exhausted", "no_lift", "budget", "parent_failed", "cancelled"}`), run a service helper `mark_non_winning_chain_proposals_superseded(chain_anchor_id)`:
  1. Walk the chain via `parent_study_id`.
  2. Identify the `best_link_id` per the same rule as `/chain` endpoint (completed subset, direction-aware argmax/argmin, tie-break by `created_at ASC`).
  3. For every link OTHER than the best, find its `pending` proposal(s) (none if rejected); `UPDATE proposals SET status = 'superseded' WHERE id IN (...) AND status = 'pending'`.
  4. Idempotent — re-running the helper on the same chain produces zero updates.
- Trigger mechanism options: (a) extend `_on_study_complete` to walk the chain; (b) a new dedicated Arq job dispatched after the final link's digest; (c) periodic reconciler. Recommend (a) — same code path that already creates the per-link proposals.

### Cap 3 — Frontend filtering on `/proposals`

- Default filter excludes `superseded`. Operator can opt in via a "Show superseded" toggle.
- `StatusBadge` adds a `superseded` variant (greyed, "Superseded").
- The chain panel (Phase 1 FR-7) MAY also surface the superseded marker per link so the operator sees the audit trail.

## Scope signals

- **Backend:**
  - One Alembic migration: ALTER constraint on `proposals_status_check` (requires drop + re-add with new value list). Idempotent rollback adds the constraint back without `superseded`.
  - New service helper `mark_non_winning_chain_proposals_superseded`.
  - Service-state-machine guard updates at `backend/app/services/proposal_state.py` (if it exists) or wherever proposal transitions are gated.
  - Repo helper `list_pending_proposals_for_chain(anchor_id)`.
- **Frontend:** `/proposals` index filter + status badge + per-link badge on chain panel.
- **Migration:** Yes — `proposals_status_check` CHECK constraint extension. Round-trip verified.
- **Config:** None.
- **Audit events:** MVP3+ — when `audit_log` lands, emit `proposal_superseded` event with `study_id`, `proposal_id`, `chain_anchor_id`, `best_link_id`. Pre-MVP3: structlog INFO only.

## Why deferred from Phase 1

Phase 1's `/chain` endpoint already gives the operator a single morning artifact via `best_link_id` + `proposal_id_for_best_link`. The friction Phase 3 addresses (cluttered `/proposals` index) is real but downstream — operators who use `/chain`-derived links exclusively never see the clutter, and operators who do browse `/proposals` get a visual signal (the badge) only after the system has marked superseded, which itself depends on the chain-termination logic.

Critically: Phase 3 requires a migration that **reopens shipped schema** (the `proposals_status_check` CHECK constraint added in `feat_study_lifecycle`). That's a heavier change than Phase 1's all-JSONB additions. The Phase 1 cap-on-cap approach lets us ship the capability without the schema-extension surface; we can add Phase 3 once an operator reports the friction.

## Relationship to other work

- **Depends on** [`feat_overnight_final_solution`](feature_spec.md) Phase 1 — uses its chain-termination signal.
- **Adjacent to** [`feat_overnight_final_solution`](feature_spec.md) Phase 2 — the morning card (Phase 2) may want to know which intermediate proposals are superseded for cleaner rendering.
- **Independent of** `feat_overnight_studies_summary_card` — different surface.

## Open questions

- **Q1** — When the `best_link_id` flips after chain termination (e.g., a delayed metric re-compute, or operator re-runs the chain with bigger budget): should the previously-superseded proposals flip back to `pending`? Recommend yes — the helper is idempotent; re-running with the new winner reshuffles correctly. Edge case: a proposal already shipped to a PR (`pr_opened`/`pr_merged`) MUST NOT flip back to `pending`. Document the precedence rule.
- **Q2** — Operator UX for ship-the-runner-up: do we surface a "Reinstate this proposal" button on a superseded row, or require the operator to manually `PATCH status = pending`? Recommend the button — keeps the operator in the UI.
- **Q3** — Should `rejected` proposals from prior chain runs be preserved (not flipped to superseded)? Yes — rejection is a stronger operator signal than supersession.
