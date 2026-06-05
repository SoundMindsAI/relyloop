# Phase 3 — Proposal `superseded` status for non-winning chain links

**Date:** 2026-06-03 (preflight-refreshed 2026-06-04, re-preflighted 2026-06-05)
**Status:** Idea — deferred Phase 3 from `feat_overnight_final_solution` Phase 1 spec
**Priority:** P2 (active MVP2 scope — `/proposals` index cleanup; lower than the MVP2 headliners but on the roadmap, not defer-until-incident)
**Origin:** Carried out of [`docs/00_overview/implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md`](../../implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md) §3 "Phase boundaries" (line 110) + §19 D-8 (line 702). Phase 1 ships the cross-knob exploration capability and leans on `best_link_id` + `proposal_id_for_best_link` from the existing `/chain` endpoint to surface the morning artifact as a single proposal. Phase 3 polishes the `/proposals` index by marking non-winning chain links' proposals `superseded` so the morning view is unambiguously "one answer."
**Depends on:** `feat_overnight_final_solution` Phase 1 — **merged** as PR #440 on 2026-06-04 (squash `1e9522a0`). The dependency is satisfied; this idea is genuinely runnable once an operator reports the friction. Independent of Phase 2 (merged PR #442, 2026-06-04, squash `0c4e0358`).

> **Priority guidance:** P2 within MVP2 — below the headliners (`feat_query_normalization_tuning`, `feat_fts_rank_ordering`, etc.) but on the active roadmap. The Phase 1 capability does not *require* this; the morning `/proposals` index just stays cluttered until it ships. Operator confirmed (2026-06-04) this is MVP2 scope, not defer-until-incident.

## Problem

When `follow_suggestions` runs a 4-link chain, today's proposal-creation logic at [`backend/workers/orchestrator.py:693-740`](../../../../backend/workers/orchestrator.py#L693-L740) (`_stop`, NOT `_on_study_complete` — the function name was renamed before Phase 1 shipped; preflight 2026-06-04 corrected the citation) creates **one `pending` proposal per completed link** — yielding up to 6 proposals (anchor + 5 descendants) in `/proposals`. `_stop` opens a single transaction that calls `study_state.complete_study` then `repo.create_proposal(... status="pending", config_diff={}, metric_delta=None ...)`, so the per-link `pending` row is durable the instant the chain link transitions to `completed`. Phase 1 surfaces a single "best" via `best_link_id` + `proposal_id_for_best_link` on `/chain`, but the index page still shows all 6 as `pending`. The non-winning links' proposals dead-end the operator: they're real `pending` rows but shipping any of them would discard the chain's winning insight.

Phase 3 marks those non-winning proposals `superseded` so:

- the `/proposals` index can hide or visually de-emphasize them by default;
- the `pending` status accurately means "ready to ship, no better alternative known";
- audit trails preserve the full chain history (superseded ≠ deleted).

## Proposed capabilities

### Cap 1 — Add `superseded` to the `proposals.status` CHECK constraint + every wire-value mirror

- **Migration:** alter the CHECK on `proposals.status` (constraint name `proposals_status_check`) to `IN ('pending', 'pr_opened', 'pr_merged', 'rejected', 'superseded')`. Postgres requires DROP + ADD because `ALTER CONSTRAINT … CHECK` cannot mutate the predicate in place. Round-trip verified per CLAUDE.md Absolute Rule #5: `downgrade()` drops + re-adds the constraint without `'superseded'`. Idempotency guard: pre-flight `DELETE FROM proposals WHERE status = 'superseded'` in the downgrade so the re-added CHECK can never reject existing rows — OR, more conservatively, refuse to downgrade if any `superseded` rows exist (recommend the conservative path; flag the choice as an Open question for `/spec-gen`).
- **Source-of-truth mirrors that MUST move in lockstep** (preflight 2026-06-04 — the original idea only named the model; the full chain has four mirrors enforced by the column discipline in CLAUDE.md "Enumerated Value Contract Discipline"):
  1. **ORM CHECK** — [`backend/app/db/models/proposal.py:42`](../../../../backend/app/db/models/proposal.py#L42) — the `status IN (...)` literal inside `__table_args__` (constraint name `proposals_status_check`).
  2. **Repo filter Literal** — [`backend/app/db/repo/proposal.py:56`](../../../../backend/app/db/repo/proposal.py#L56) — `ProposalStatusFilter = Literal["pending", "pr_opened", "pr_merged", "rejected"]` (used by `list_proposals_paginated`'s `?status=` query-param contract; widen the Literal so operators can filter to `superseded` rows).
  3. **API wire Literal** — [`backend/app/api/v1/schemas.py:1379`](../../../../backend/app/api/v1/schemas.py#L1379) — `ProposalStatusWire = Literal["pending", "pr_opened", "pr_merged", "rejected"]` (the response-payload type the OpenAPI schema exports + the source-of-truth comment cited by the frontend mirror). (preflight 2026-06-05: shifted from `:1322` after the post-2026-06-04 schema additions.)
  4. **Frontend mirror** — [`ui/src/lib/enums.ts:202-204`](../../../../ui/src/lib/enums.ts#L202-L204) — `PROPOSAL_STATUS_VALUES` (the `// Values must match … ProposalStatusWire` comment is already in place; just append `'superseded'`).
  5. **StatusBadge variant map** — [`ui/src/components/common/status-badge.tsx:23-28`](../../../../ui/src/components/common/status-badge.tsx#L23-L28) — the `proposal:` block; add `superseded: 'outline'` (or a new `'muted'` variant if reviewer asks for visual distinction from `rejected`'s `'outline'`). Pure typed-record append; lint-clean against the `StatusBadgeKind` typing.
  6. **`openapi.json` + `types.ts`** — regenerated automatically via `bash scripts/regen-generated-artifacts.sh` (FR-gated by the `generated-artifacts-fresh` job in `pr.yml`). The spec MUST call this out so the implementer doesn't trip the gate.
- New value semantics: a `pending` proposal that the system decided is dominated by a sibling chain link's proposal. Not operator-rejected; not auto-deleted; not shipped.
- Allowed state transitions: `pending → superseded` (auto by chain-rollup), `superseded → pending` (operator action via UI, when they explicitly want to ship the runner-up). Reflect both in the conditional-UPDATE pattern the existing repo uses (see Cap 2).

### Cap 2 — Auto-supersede non-winning chain links' proposals on chain termination

- **Chain-termination signal.** The tail link reaches a terminal status AND the chain's derived `stop_reason ∈ CHAIN_STOP_REASONS \ {"in_flight"}` — i.e. one of `{"depth_exhausted", "no_lift", "budget", "parent_failed", "cancelled"}` per [`backend/app/domain/study/chain_summary.py:55-77`](../../../../backend/app/domain/study/chain_summary.py#L55-L77) `CHAIN_STOP_REASONS`. Use `derive_chain_stop_reason(links, anchor_trials)` from the same module — DO NOT re-derive the matrix here.
- **Reuse, do not rebuild.** The chain walk + best-link selection already exists as pure-DB-read infrastructure shipped by `feat_overnight_autopilot`:
  - [`repo.get_chain_for_study(db, study_id) → ChainTraversalResult | None`](../../../../backend/app/db/repo/study.py#L250-L372) — walks `parent_study_id` to the anchor, then one-child-per-parent down to the tail (capped at 6 links per the linear-chain invariant). Returns `links`, `proposal_id_by_link_id`, `anchor_trials`.
  - [`select_best_link(links)`](../../../../backend/app/domain/study/chain_summary.py#L212) — direction-aware argmax/argmin over the completed subset, tie-break by `created_at ASC`.
- **Service helper to add** (per CLAUDE.md "Service Layer" convention — accepts `db: AsyncSession`, no commit):
  ```python
  async def mark_non_winning_chain_proposals_superseded(
      db: AsyncSession, *, study_id: str
  ) -> int:
      """Returns the number of proposals transitioned pending → superseded.
      Idempotent: re-running on the same chain returns 0. Caller commits."""
  ```
  Body:
  1. `traversal = await repo.get_chain_for_study(db, study_id)`. Early-return 0 if `traversal is None` or `len(traversal.links) < 2` (single-link chains have no siblings to supersede).
  2. `stop_reason = derive_chain_stop_reason(traversal.links, traversal.anchor_trials)`. Early-return 0 if `stop_reason == "in_flight"`.
  3. `best_link_id = select_best_link(traversal.links)`. Early-return 0 if `best_link_id is None` (no completed link → no winner → nothing to supersede).
  4. Build the loser-study-id set: `{link.id for link in traversal.links if link.id != best_link_id}`.
  5. Conditional UPDATE in one round-trip, mirroring [`backend/app/db/repo/proposal.py:121-126`](../../../../backend/app/db/repo/proposal.py#L121-L126)'s `WHERE id=:id AND status='pending'` pattern (preflight 2026-06-05: corrected from `:115-125`, which covered the docstring):
     ```sql
     UPDATE proposals
         SET status = 'superseded'
       WHERE study_id IN :loser_ids
         AND status = 'pending'
     RETURNING id;
     ```
     Return `len(returned_ids)`.
- **Critical: also widen the chain-traversal's proposal filter.** [`backend/app/db/repo/study.py:336-351`](../../../../backend/app/db/repo/study.py#L336-L351) currently builds `proposal_id_by_link_id` from rows where `Proposal.status != "rejected"` (the exact predicate sits at [`study.py:341`](../../../../backend/app/db/repo/study.py#L341)). After Phase 3, this MUST become `Proposal.status.notin_(("rejected", "superseded"))` — otherwise the chain panel will still resolve superseded proposals as the "newest non-rejected" per link, defeating the rollup. The widening cascades automatically to `list_recent_completed_chains` ([`study.py:387`](../../../../backend/app/db/repo/study.py#L387), shipped by `feat_overnight_studies_summary_card` PR #444), which reuses `get_chain_for_study`. This is a one-line change but easy to miss; the spec MUST call it out as a co-requisite of Cap 2.
- **State-machine gating.** `backend/app/services/proposal_state.py` **does not exist** (preflight 2026-06-04 — the original idea hedged "if it exists"; verified absent). RelyLoop's proposal-status transitions are gated via dedicated repo helpers using the conditional-UPDATE pattern (`reject_proposal`, `mark_pr_opened`, `complete_pr_merge`, `record_pr_open_failure`, etc.) — see [`backend/app/db/repo/proposal.py`](../../../../backend/app/db/repo/proposal.py). Phase 3 should add two new helpers in the same file:
  - `bulk_mark_superseded(db, *, study_ids)` — invoked by the chain-rollup service; the conditional UPDATE above.
  - `reinstate_from_superseded(db, *, proposal_id)` — operator-initiated single-row UPDATE gated on `WHERE id=:id AND status='superseded'`. Returns the updated `Proposal` row or raises `InvalidStateTransition` (defined at [`backend/app/db/repo/proposal.py:63`](../../../../backend/app/db/repo/proposal.py#L63)) if the row is no longer superseded (matching the [`reject_proposal`](../../../../backend/app/db/repo/proposal.py#L249) precedent). (preflight 2026-06-05: corrected `InvalidProposalState`, which does not exist in the codebase.)
  Do NOT introduce a `proposal_state.py` central guard for two helpers — the repo-helper pattern is the codebase precedent.
- **Trigger mechanism.** Recommend **(a) extend `_stop` to walk the chain** (per preflight — same code path that already opens the transaction for `study_state.complete_study` + `create_proposal`):
  - After the existing `create_proposal` call inside `_stop`'s transaction, conditionally call `mark_non_winning_chain_proposals_superseded(db, study_id=study_id)` when the newly-completed link is the tail of a multi-link chain (cheap heuristic: skip when `study.parent_study_id is None AND study.auto_followup_depth in (None, 0)` — anchors without descendants can't have losers).
  - The rollup runs **in the same transaction** as the link's own `pending` proposal insert. That single commit either (i) records the loss + supersedes earlier siblings, OR (ii) rolls back atomically on InvalidStateTransition (the same path that handles the existing complete-study race).
  - Reject alternative (b) "new Arq job after the digest" — adds queue surface for a pure-DB operation. Reject (c) "periodic reconciler" — incentivizes drift between operator views.
- **Idempotency.** `WHERE status = 'pending'` guarantees re-running on the same chain returns 0 rows. The helper is safe to invoke from any link's completion — late-arriving links naturally walk a longer chain and re-supersede the same losers no-op-style.

### Cap 3 — Frontend filtering on `/proposals`

- Default filter excludes `superseded` (the rollup is hidden by default; the operator clicks in to inspect). Operator opts in via a "Show superseded" toggle whose value flows through the existing `?status=` repeated-query-param contract on `GET /api/v1/proposals`.
- `StatusBadge` adds a `superseded: 'outline'` (or new `'muted'`) variant at [`ui/src/components/common/status-badge.tsx:23-28`](../../../../ui/src/components/common/status-badge.tsx#L23-L28). The map already keys off the wire value, so the only edit is appending the row.
- A "Reinstate" button on a superseded row's detail page posts to a new `POST /api/v1/proposals/:id/reinstate` (or `PATCH … status='pending'`). The endpoint exact shape is an Open question (see Q2 below).
- The chain panel (Phase 1 FR-7) MAY also surface the superseded marker per link so the operator sees the audit trail. **Co-requisite:** because the chain-traversal helper at `repo/study.py:340` excludes `superseded` (Cap 2), the chain panel's per-link `proposal_id_by_link_id` will not surface superseded proposals at all — the "marker" needs a separate signal. Either (i) extend `ChainTraversalResult` with a `superseded_proposal_id_by_link_id: dict[str, str]` companion field, OR (ii) accept that the chain panel shows only the winning link's proposal CTA and renders losers without a proposal link. Recommend (ii) — simpler, and the operator who wants to see superseded rows clicks the "Show superseded" toggle on `/proposals`.

### Cap 4 — Pre-MVP3 telemetry

Phase 1 added five structlog INFO events as precedent (`auto_followup_strategy_dispatch`, `auto_followup_swap_target_missing`, etc.). Phase 3 emits two:

- `chain_proposals_superseded` — one INFO per non-zero rollup. Fields: `study_id` (the link whose completion triggered the rollup), `chain_anchor_id` (from `ChainTraversalResult.anchor_id`), `best_link_id`, `superseded_count`, `superseded_proposal_ids` (list).
- `chain_proposal_reinstated` — one INFO per operator-initiated `reinstate_from_superseded` UPDATE. Fields: `proposal_id`, `study_id`, `prior_status="superseded"`.

When MVP3's `audit_log` table lands, these promote to `proposal_superseded` / `proposal_reinstated` rows with `actor_type='system'` / `actor_type='user'` respectively — same payload shape, just persisted instead of logged.

## Scope signals

- **Backend:**
  - One Alembic migration: DROP + ADD `proposals_status_check` with the new value list (Postgres can't mutate the predicate in place). Downgrade drops + re-adds without `superseded`; refuse-or-purge policy on existing `superseded` rows is an Open question.
  - New service helper `mark_non_winning_chain_proposals_superseded(db, *, study_id)` in `backend/app/services/` (file location is an Open question — likely a new `chain_rollup.py` or appended to an existing `auto_followup`-adjacent service).
  - Two new repo helpers in [`backend/app/db/repo/proposal.py`](../../../../backend/app/db/repo/proposal.py): `bulk_mark_superseded(db, *, study_ids)` (conditional UPDATE … WHERE status='pending') and `reinstate_from_superseded(db, *, proposal_id)` (single-row conditional UPDATE).
  - **NO new `proposal_state.py` module** — proposal transitions stay in the existing repo-helper-with-conditional-UPDATE pattern.
  - One-line filter widening at [`backend/app/db/repo/study.py:340`](../../../../backend/app/db/repo/study.py#L340): `Proposal.status != "rejected"` → `Proposal.status.notin_(("rejected", "superseded"))`. Co-requisite of Cap 2.
  - `_stop` in [`backend/workers/orchestrator.py:693`](../../../../backend/workers/orchestrator.py#L693) gains a single conditional call to the rollup helper inside its existing transaction.
- **Frontend:**
  - `/proposals` index: default `?status=` filter excludes `superseded`; new "Show superseded" toggle.
  - `StatusBadge` variant table: append `superseded` row to the `proposal:` block in `ui/src/components/common/status-badge.tsx`.
  - Optional: per-link "superseded" marker on the chain panel — recommend deferring per Cap 3 (ii).
  - Optional: "Reinstate" button on a superseded proposal's detail page.
  - Regenerate `ui/openapi.json` + `ui/src/lib/types.ts` via `bash scripts/regen-generated-artifacts.sh` (FR-gated).
- **Migration:** Yes — single migration on `proposals_status_check`. Round-trip verified per CLAUDE.md Absolute Rule #5. Alembic head when implementing: read `state.md` (today `0022_solr_engine_auth_check`).
- **Config:** None.
- **Audit events:** MVP3+ — when `audit_log` lands, emit `proposal_superseded` (system-initiated) + `proposal_reinstated` (user-initiated) events. Pre-MVP3: structlog INFO (`chain_proposals_superseded`, `chain_proposal_reinstated` — see Cap 4).

## Why deferred from Phase 1

Phase 1's `/chain` endpoint already gives the operator a single morning artifact via `best_link_id` + `proposal_id_for_best_link`. The friction Phase 3 addresses (cluttered `/proposals` index) is real but downstream — operators who use `/chain`-derived links exclusively never see the clutter, and operators who do browse `/proposals` get a visual signal (the badge) only after the system has marked superseded, which itself depends on the chain-termination logic.

Critically: Phase 3 requires a migration that **reopens shipped schema** (the `proposals_status_check` CHECK constraint added in `feat_study_lifecycle`). That's a heavier change than Phase 1's all-JSONB additions. The Phase 1 cap-on-cap approach lets us ship the capability without the schema-extension surface; we can add Phase 3 once an operator reports the friction.

## Relationship to other work

- **Depends on** [`feat_overnight_final_solution`](../../implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md) Phase 1 (merged PR #440, 2026-06-04) — uses its chain-termination signal + `CHAIN_STOP_REASONS` + `select_best_link` infrastructure.
- **Adjacent to** [`feat_overnight_final_solution_phase2`](../../implemented_features/2026_06_04_feat_overnight_final_solution_phase2/feature_spec.md) — Phase 2 **already shipped** (PR #442, 2026-06-04) without superseded awareness. Its mount predicate is `stop_reason !== 'in_flight' && links.length >= 2` and its best-config CTA renders from `chainSummary.best_link_id` / `proposal_id_for_best_link` directly. After Phase 3, the chain-traversal filter widening (see Cap 2 co-requisite) automatically prevents superseded proposals from appearing as the "winning proposal" for any link the morning card might consult — no Phase 2 changes required. A future polish item could teach the card to render an explicit "X siblings superseded" sub-line, but that's out of Phase 3 scope.
- **Independent of** [`feat_overnight_studies_summary_card`](../../implemented_features/2026_06_04_feat_overnight_studies_summary_card/feature_spec.md) (merged PR #444, 2026-06-04) — different surface (`/studies` index "ran while away" card vs `/studies/{id}` detail-page morning card). Neither consumes `proposals.status`, BUT its `list_recent_completed_chains` repo helper reuses `get_chain_for_study`, so the Cap-2 co-requisite filter widening (rejected → rejected+superseded) automatically cascades — no Phase 3 changes required in `feat_overnight_studies_summary_card`.
- **Coordination with** [`feat_proposal_full_param_space_view`](../../implemented_features/2026_06_04_feat_proposal_full_param_space_view/feature_spec.md) (merged PR #446, 2026-06-04). PR #446 added `<FullParamSpacePanel>` to `/proposals/[id]` ([`ui/src/app/proposals/[id]/page.tsx:332`](../../../../ui/src/app/proposals/%5Bid%5D/page.tsx#L332)). The proposal-detail page is now denser; Cap 3's "Reinstate" button (per Q2) should sit alongside the existing "Open PR" / "Reject" affordances rather than at panel level, so the chain-rollup audit signal stays close to the other status-mutating actions.

## Open questions

- **Q1 — Best-link flip semantics (locked 2026-06-05).** When the `best_link_id` flips after chain termination (e.g. a delayed metric re-compute, or operator re-runs the chain with bigger budget), previously-superseded proposals DO flip back to `pending`. The helper is idempotent; re-running with the new winner reshuffles correctly. **Edge case:** a proposal already shipped to a PR (`pr_opened`/`pr_merged`) MUST NOT flip back to `pending`. The Cap-2 conditional UPDATE's `WHERE status='superseded'` clause enforces this naturally; document it explicitly in the spec.
- **Q2 — Reinstate UX shape.** Do we surface a "Reinstate this proposal" button (recommend) or require the operator to `PATCH status = pending` from the API? **Recommended default:** button + dedicated endpoint `POST /api/v1/proposals/:id/reinstate` (single-purpose verb, clear audit signal, sidesteps the broader debate about whether arbitrary `PATCH status=` should be allowed). Open sub-question: does the button live on `/proposals/:id` detail page, on the `/proposals` row, or both?
- **Q3 — `rejected` precedence (locked).** `rejected` proposals from prior chain runs are preserved (NOT flipped to `superseded`). Rejection is a stronger operator signal than supersession; the Cap-2 conditional UPDATE's `WHERE status='pending'` clause enforces this automatically.
- **Q4 — Downgrade policy on existing `superseded` rows (locked 2026-06-05).** Option (a): refuse to downgrade if any `superseded` rows exist (safest; forces operator to manually decide each one). The migration's `downgrade()` SELECTs `COUNT(*) WHERE status='superseded'` and `RAISE` with a clear error message instructing the operator to manually `UPDATE … SET status='rejected' WHERE status='superseded'` first, then re-run downgrade. Rejected (b) `DELETE FROM proposals WHERE status='superseded'` — destructive, would lose operator history that the supersession decision had been correct at the time.
- **Q5 — Service-helper location (locked 2026-06-05).** New file `backend/app/services/chain_rollup.py` — the helper is chain-scoped, not proposal-scoped, and the existing `backend/app/services/agent_proposals_dispatch.py` is for the chat-agent tool surface. Rejected alternatives: `backend/app/services/auto_followup_post_complete.py` (autopilot-coupled — Phase 3 also covers non-autopilot chains created by the chat agent) and appending to `agent_proposals_dispatch.py` (scope mismatch).

## Folder placement (resolved 2026-06-04)

Operator confirmed this stays under `02_mvp2/` as active MVP2 scope (priority upgraded from "Backlog" to P2 to match — a folder under `02_mvp2/` with no explicit priority silently buckets as P2 in the dashboard per `feedback_dashboard_priority_p3_buckets_as_p2.md`, so the explicit P2 line keeps the idea and the dashboard consistent). The parent spec's D-8 "defer-until-incident" framing is superseded by this decision — Phase 3 is on the roadmap, just below the headliners.
