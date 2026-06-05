# Feature Specification — Overnight Final Solution Phase 3 (Proposal supersession on chain rollup)

**Date:** 2026-06-05
**Status:** Draft
**Owners:** RelyLoop maintainers
**Related docs:**
- [`idea.md`](idea.md) — preflight-cleaned 2026-06-05
- [`feat_overnight_final_solution`](../../implemented_features/2026_06_04_feat_overnight_final_solution/feature_spec.md) (Phase 1 — PR #440, 2026-06-04)
- [`feat_overnight_final_solution_phase2`](../../implemented_features/2026_06_04_feat_overnight_final_solution_phase2/feature_spec.md) (Phase 2 — PR #442, 2026-06-04)
- [`feat_overnight_studies_summary_card`](../../implemented_features/2026_06_04_feat_overnight_studies_summary_card/feature_spec.md) (PR #444, 2026-06-04)
- [`feat_proposal_full_param_space_view`](../../implemented_features/2026_06_04_feat_proposal_full_param_space_view/feature_spec.md) (PR #446, 2026-06-04 — Cap-3 placement context)
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md)
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md)

---

## 1) Purpose

- **Problem:** Today's `_stop` orchestrator path creates **one `pending` proposal per completed chain link** ([`backend/workers/orchestrator.py:693-740`](../../../../backend/workers/orchestrator.py#L693-L740)). When `feat_overnight_autopilot` runs a 4-link chain, the operator's morning `/proposals` index shows up to 6 `pending` proposals (anchor + 5 descendants). Phase 1 surfaced a single "best" via `best_link_id` + `proposal_id_for_best_link` on `/chain`, but the index page still shows all 6 as ready-to-ship. Shipping any non-winner discards the chain's winning insight; the clutter dead-ends the operator.
- **Outcome:** Non-winning chain links' proposals transition `pending → superseded` when the chain terminates. `/proposals` defaults to hiding `superseded`; operators opt into seeing them. `pending` accurately means "ready to ship, no better alternative known." The full chain history is preserved (superseded ≠ deleted, no chain-traversal data loss).
- **Non-goal:** Auto-rejecting losers, auto-deleting losers, auto-opening a PR for the winner, or changing the winner-selection algorithm itself (that's `select_best_link` from Phase 1, unchanged here).

## 2) Current state audit

### Existing implementations

- **`backend/app/db/models/proposal.py`** ([line 42](../../../../backend/app/db/models/proposal.py#L42)): the `proposals_status_check` CHECK constraint admits `status IN ('pending', 'pr_opened', 'pr_merged', 'rejected')` — Phase 3 extends this.
- **`backend/app/db/repo/proposal.py`** ([line 56](../../../../backend/app/db/repo/proposal.py#L56)): `ProposalStatusFilter = Literal["pending", "pr_opened", "pr_merged", "rejected"]` — the `?status=` query-param contract used by `list_proposals_paginated` ([line 169](../../../../backend/app/db/repo/proposal.py#L169), [line 221](../../../../backend/app/db/repo/proposal.py#L221)).
- **`backend/app/api/v1/schemas.py`** ([line 1379](../../../../backend/app/api/v1/schemas.py#L1379)): `ProposalStatusWire = Literal["pending", "pr_opened", "pr_merged", "rejected"]` — the response-payload type the OpenAPI schema exports.
- **`backend/app/db/repo/study.py`** ([line 341](../../../../backend/app/db/repo/study.py#L341)): `get_chain_for_study`'s proposal lookup filters `Proposal.status != "rejected"` to build `proposal_id_by_link_id`. This widens to `notin_(("rejected", "superseded"))`.
- **`backend/workers/orchestrator.py`** ([line 693](../../../../backend/workers/orchestrator.py#L693)): `_stop` opens the single transaction that calls `study_state.complete_study` then `repo.create_proposal(... status="pending" ...)`. Phase 3 appends a conditional rollup call inside that same transaction.
- **`backend/app/api/v1/proposals.py`** ([line 367](../../../../backend/app/api/v1/proposals.py#L367)): `list_proposals_endpoint` accepts `status_filter: ProposalStatusWire | None` — **a single optional value, not a list.** Phase 3 leaves this contract unchanged (D-15 revised) and adds a new sibling boolean param `include_superseded: bool = False`. The repo helper `list_proposals_paginated` ([line 192](../../../../backend/app/db/repo/proposal.py#L192)) implements the existing `status` filter as `Proposal.status == status`; Phase 3 adds an `include_superseded: bool = False` kwarg that, when `False`, appends `Proposal.status != 'superseded'` whenever `?status=` is not explicitly set.
- **`ui/src/lib/enums.ts`** ([lines 202-204](../../../../ui/src/lib/enums.ts#L202-L204)): `PROPOSAL_STATUS_VALUES` mirror, sourced from `ProposalStatusWire` per the form-dropdown discipline.
- **`ui/src/components/common/status-badge.tsx`** ([lines 23-28](../../../../ui/src/components/common/status-badge.tsx#L23-L28)): the `proposal:` block in the `StatusBadgeVariantMap` (`pending: 'secondary'`, `pr_opened: 'default'`, `pr_merged: 'success'`, `rejected: 'outline'`).
- **`backend/app/services/proposal_state.py`**: **does not exist**. RelyLoop's proposal-status transitions are gated via repo helpers using the conditional-UPDATE pattern (`reject_proposal` at [line 249](../../../../backend/app/db/repo/proposal.py#L249), `mark_proposal_pr_opened` at [line 272](../../../../backend/app/db/repo/proposal.py#L272), etc.). Phase 3 follows this precedent; it does NOT introduce a centralized state guard.
- **`backend/app/domain/study/chain_summary.py`** ([line 68](../../../../backend/app/domain/study/chain_summary.py#L68)): `CHAIN_STOP_REASONS` frozenset (`{depth_exhausted, no_lift, budget, parent_failed, cancelled, in_flight}`); [`derive_chain_stop_reason`](../../../../backend/app/domain/study/chain_summary.py#L107) + [`select_best_link`](../../../../backend/app/domain/study/chain_summary.py#L212) — Phase 3 reuses, does not rebuild.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| `ui/src/app/proposals/page.tsx` | three-state filter chips (`all` / `study` / `manual`) + status-multi-filter | adds a "Show superseded" toggle that flows through the existing `?status=` repeated-query-param contract; default URL behavior unchanged for backward links |
| `ui/src/app/proposals/[id]/page.tsx` | proposal-detail page below `<ConfigDiffPanel>` + `<FullParamSpacePanel>` (added by PR #446) | adds a "Reinstate" button visible only when `proposal.status === 'superseded'`, placed alongside the existing "Open PR" / "Reject" affordances per D-11 |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/db/test_proposal_repo_conditional_update.py` | `WHERE status='pending'` precedent | 1 | Existing tests on `update_proposal_for_digest` continue passing unchanged; Phase 3 adds new tests against `bulk_mark_superseded` + `reinstate_from_superseded` in `test_proposal_supersession.py` (new file). |
| `backend/tests/integration/test_orchestrator_stop_supersedes_losers.py` (new) | `_stop` rollup | — | New: integration test that seeds a 3-link chain, completes the tail, asserts losers transition `pending → superseded` atomically with the winner's `pending` insert. |
| `backend/tests/integration/test_studies_chain_endpoint.py` | `proposal_id_by_link_id` resolution | existing | Phase 3 adds a case: when a link's only proposal is `superseded`, the link's `proposal_id_by_link_id` entry is **absent** (not surfaced as the "newest non-rejected"). |
| `backend/tests/contract/test_proposals_filter_contract.py` | `?status=` allowlist | existing | Extend `ProposalStatusWire` literal allowlist assertion to include `superseded`. |
| `ui/src/__tests__/components/proposals/proposals-list-page.test.tsx` | filter chip plumbing | existing | Add: default URL excludes `?status=superseded`; "Show superseded" toggle appends it; URL contract round-trips. |
| `ui/src/__tests__/components/common/form-select-discipline.test.tsx` | enums-import lint | existing | No code change — the lint guard automatically picks up the new `PROPOSAL_STATUS_VALUES` entry. |

### Existing behaviors affected by scope change

- **`/proposals` index default filter:** Current: returns all non-deleted proposals regardless of status. New: SQL-side default is unchanged (server returns all statuses); the frontend default URL drops `superseded` from its status set. Decision needed: No — the wire contract is backward-compatible (clients that don't filter still see everything; the front-end default just narrows what it asks for).
- **`get_chain_for_study` proposal resolution:** Current: returns the newest `status != 'rejected'` proposal per link. New: returns the newest `status NOT IN ('rejected', 'superseded')` proposal per link. Decision needed: No — losers' proposals are intentionally hidden from chain-traversal consumers (Phase 1's `best_link_id` + Phase 2's `<OvernightResultCard>` + Phase 3's `/proposals` filter all collaborate on the "one answer" promise).
- **`POST /api/v1/proposals/:id/reinstate`:** New endpoint. Current: no operator path to undo supersession. New: single-purpose endpoint flips `superseded → pending`; gated by `WHERE status='superseded'` (idempotent, race-safe). Decision needed: No (placement is D-11; verb is locked).

---

## 3) Scope

### In scope

- **Cap 1 — Schema + wire-value mirrors.** Alembic migration `0023_proposals_superseded_status` extends `proposals_status_check` to admit `superseded`. ORM CHECK literal, `ProposalStatusFilter` repo Literal, `ProposalStatusWire` API Literal, frontend `PROPOSAL_STATUS_VALUES` mirror, and `StatusBadge`'s `proposal:` variant map all move in lockstep. `openapi.json` + `types.ts` regenerated via `scripts/regen-generated-artifacts.sh`.
- **Cap 2 — Service helper + repo helpers + chain-traversal co-requisite.** New `backend/app/services/chain_rollup.py` with `mark_non_winning_chain_proposals_superseded(db, *, study_id)`. New `backend/app/db/repo/proposal.py` helpers `bulk_mark_superseded(db, *, study_ids)` (conditional UPDATE `WHERE status='pending'` RETURNING ids) and `reinstate_from_superseded(db, *, proposal_id)` (conditional UPDATE `WHERE status='superseded'` raising `InvalidStateTransition` on miss). One-line widening at `backend/app/db/repo/study.py:341` from `Proposal.status != "rejected"` to `Proposal.status.notin_(("rejected", "superseded"))`. `_stop` ([`backend/workers/orchestrator.py:693`](../../../../backend/workers/orchestrator.py#L693)) appends a conditional call to the rollup helper inside its existing transaction.
- **Cap 3 — Frontend filter + reinstate UX + glossary.** `/proposals` index default URL excludes `?status=superseded`; a "Show superseded" toggle appends it. `StatusBadge` `proposal:` block adds `superseded: 'outline'` (visually distinct from `rejected` via copy + the existing card-frame, not the badge variant — D-12). `/proposals/[id]` adds a "Reinstate" button visible only when `proposal.status === 'superseded'`, placed alongside the existing "Open PR" / "Reject" affordances (D-11). New glossary entries `proposal.status.superseded` + `proposal.reinstate`.
- **Cap 4 — Pre-MVP3 telemetry.** Two new structlog INFO event types: `chain_proposals_superseded` (one per non-zero rollup) and `chain_proposal_reinstated` (one per operator reinstate). MVP3+ promotes both to `audit_log` rows.

### Out of scope

- Auto-rejecting non-winners (rejection stays an operator decision; supersession is the system's neutral signal).
- Auto-deleting non-winners (preserves audit trail).
- Auto-opening a PR for the best link (Phase 1's `best_link_id` + the operator's existing "Open PR" button continue to handle this).
- Changing `select_best_link`'s winner-selection algorithm.
- Surfacing the superseded marker on the chain panel (Cap 3 (ii) per idea — the chain panel renders only winning links' proposal CTAs; operators inspect losers via the "Show superseded" toggle on `/proposals`).
- Modifying `feat_overnight_studies_summary_card`'s `<RecentChainsCard>` — its `RecentChainSummary` response doesn't carry per-link proposal IDs, so it's unaffected by the chain-traversal filter widening.
- Modifying `feat_overnight_final_solution_phase2`'s `<OvernightResultCard>` — its best-config CTA renders from `chainSummary.best_link_id` / `proposal_id_for_best_link` directly; widening the chain-traversal filter automatically prevents superseded proposals from being chosen as a link's "newest non-rejected," but no Phase 2 code changes.

### API convention check

Verified against [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix:** `/api/v1/<resource>`. New endpoint lands at `/api/v1/proposals/{proposal_id}/reinstate`. ✓
- **Router file:** `backend/app/api/v1/proposals.py` (new endpoint joins existing `reject_proposal_endpoint` + `open_pr_endpoint`). ✓
- **HTTP method:** `POST` (single-purpose verb; sidesteps the broader debate about whether arbitrary `PATCH status=` should be allowed — see D-11). ✓
- **Non-auth error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per the shared `error_envelope()` helper at [`backend/app/api/v1/proposals.py:79-89`](../../../../backend/app/api/v1/proposals.py#L79-L89). ✓
- **Auth:** N/A — MVP1–MVP3 is single-tenant, no auth surface.

### Phase boundaries

**Single-phase delivery.** This spec covers the full Phase 3 scope as defined in the parent feature's §3 boundaries. No Phase 4 is deferred from this spec.

---

## 4) Product principles and constraints

- **The PR is the contract.** Supersession is internal bookkeeping; nothing in `proposals.status='superseded'` reaches GitHub or the operator's config repo. Only operator-initiated `open_pr` actions ship anywhere.
- **Audit trail preserved.** A superseded row stays in the DB indefinitely (no auto-delete, no hard-delete). The operator can always reinstate.
- **`rejected` is stronger than `superseded`.** Operator-initiated rejection beats system-initiated supersession — the rollup never touches a `rejected` row (Q3 locked).
- **`pr_opened` / `pr_merged` are stronger still.** Once a proposal is shipped, it's outside Phase 3's purview — the rollup never touches non-`pending` rows.
- **One-way flip on rollup; operator-initiated flip-back.** The system can supersede; only the operator can reinstate. Distinct verbs, distinct event types, distinct audit signals.

### Anti-patterns

- **Do not** introduce a `backend/app/services/proposal_state.py` central guard — the conditional-UPDATE-on-repo-helper precedent ([`reject_proposal`](../../../../backend/app/db/repo/proposal.py#L249), `mark_proposal_pr_opened`, etc.) is the codebase convention; a new central guard for two helpers would be net new abstraction surface for no benefit.
- **Do not** schedule the rollup as a separate Arq job after the digest — it's a pure-DB operation that belongs in the same transaction as the `_stop` `create_proposal` insert. Decoupling it adds queue surface, eventual-consistency windows, and operator-visible drift between `/chain` and `/proposals`.
- **Do not** implement a periodic reconciler — incentivizes silent state drift between operator views and the system's notion of "the answer."
- **Do not** auto-flip superseded → pending when `best_link_id` flips at operator-initiated re-run time — the Cap-2 helper is idempotent; re-running it with the new winner naturally reshuffles, and the `WHERE status='superseded'` guard prevents touching `pr_opened`/`pr_merged` rows (Q1 locked).
- **Do not** widen the chain-traversal filter at `study.py:341` without also widening the rollup helper — they must move in lockstep or the chain panel will still surface superseded proposals as the "newest non-rejected." This is the most common silent-regression risk.
- **Do not** mark frontend option values from memory. Every `<select>` and filter chip MUST cite `PROPOSAL_STATUS_VALUES` from `@/lib/enums` per the form-dropdown discipline.

---

## 5) Assumptions and dependencies

- **Dependency: `feat_overnight_final_solution` Phase 1 (PR #440, merged 2026-06-04).** Status: implemented. Provides `repo.get_chain_for_study`, `CHAIN_STOP_REASONS`, `derive_chain_stop_reason`, `select_best_link`. Hard dependency — Phase 3 cannot exist without the chain-traversal infrastructure.
- **Dependency: `feat_overnight_final_solution_phase2` (PR #442, merged 2026-06-04).** Status: implemented. Independent — Phase 2's `<OvernightResultCard>` consumes `chainSummary.best_link_id` directly, not `proposal_id_by_link_id`. The Cap-2 chain-traversal filter widening cascades but requires no Phase 2 code changes.
- **Dependency: `feat_overnight_studies_summary_card` (PR #444, merged 2026-06-04).** Status: implemented. Soft — its `list_recent_completed_chains` repo helper reuses `get_chain_for_study`, so the Cap-2 filter widening cascades automatically. No PR #444 code changes required.
- **Coordination with `feat_proposal_full_param_space_view` (PR #446, merged 2026-06-04).** Status: implemented. Adds `<FullParamSpacePanel>` to `/proposals/[id]:332`. Phase 3's "Reinstate" button placement (D-11) sits alongside the existing "Open PR" / "Reject" affordances, not at panel level, so the chain-rollup audit signal stays close to other status-mutating actions.
- **Alembic head when implementing:** `0022_solr_engine_auth_check`. New migration is `0023_proposals_superseded_status`.

---

## 6) Actors and roles

- **Primary actors:** the orchestrator (system, fires the rollup on chain termination) and the relevance engineer (operator, can reinstate via UI).
- **Role model:** N/A — RelyLoop MVP1–MVP3 is single-tenant, no auth surface (per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).
- **Permission boundaries:** Any operator can reinstate any superseded proposal — there's no per-user gating because there are no users.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

**Pre-MVP3:** structlog INFO events (Cap 4). When MVP3's `audit_log` lands, both promote per the matrix below.

**MVP3+ audit-event matrix** (forward-declared so the audit-log feature picks this up cleanly):

| event_type | actor_type | visibility | metadata_json fields |
|---|---|---|---|
| `proposal_superseded` | `system` | tenant-visible | `study_id` (the triggering link), `chain_anchor_id`, `best_link_id`, `superseded_count`, `superseded_proposal_ids` (list) |
| `proposal_reinstated` | `user` | tenant-visible | `proposal_id`, `study_id`, `prior_status` (always `"superseded"`) |

Both metadata payloads contain no credentials, tokens, or PII — only study/proposal UUIDs.

---

## 7) Functional requirements

### FR-1: Add `superseded` to the `proposals.status` allowlist + every wire-value mirror

- Requirement:
  - The system **MUST** accept `superseded` as a valid value for `proposals.status` at the DB CHECK layer, the ORM CHECK layer, the repo `Literal` filter, the API wire `Literal`, the frontend `PROPOSAL_STATUS_VALUES` mirror, and the `StatusBadge` `proposal:` variant map.
  - The Alembic migration `0023_proposals_superseded_status` **MUST** include both `upgrade()` and `downgrade()` and round-trip cleanly per CLAUDE.md Absolute Rule #5.
  - The `downgrade()` **MUST** abort with a clear operator message if any `superseded` rows exist (Q4 locked — option (a) refuse).
  - `bash scripts/regen-generated-artifacts.sh` **MUST** be run after the wire-value mirror cascade so `ui/openapi.json` + `ui/src/lib/types.ts` reflect the new value (the `generated-artifacts-fresh` CI job otherwise red-lights the PR).
- Notes: see §9 for the migration body sketch; see Cap 1 in [`idea.md`](idea.md) for the five lockstep mirror sites.

### FR-2: Service helper `mark_non_winning_chain_proposals_superseded`

- Requirement:
  - The system **MUST** expose `mark_non_winning_chain_proposals_superseded(db: AsyncSession, *, study_id: str) -> tuple[int, list[str]]` at `backend/app/services/chain_rollup.py` (Q5 locked). Returns `(superseded_count, superseded_proposal_ids)` — see D-19 for why the IDs are returned alongside the count.
  - The function **MUST** be idempotent: re-running on the same chain returns 0.
  - The function **MUST** early-return `(0, [])` when: (a) `get_chain_for_study` returns `None`, (b) the chain has fewer than 2 links (no siblings to supersede), (c) the derived `stop_reason == "in_flight"`, or (d) `select_best_link` returns `None` (no completed link → no winner).
  - The function **MUST** delegate the actual UPDATE to `repo.bulk_mark_superseded(db, study_ids=loser_ids)` — no inline SQL in the service layer.
  - The function **MUST NOT** commit; the caller commits per the service-layer convention.
  - The function **MUST** return a `(count, list_of_superseded_proposal_ids)` tuple — not just the count — so the caller can emit the post-commit structlog event with the full IDs payload per FR-7 / D-19.
- Notes: reuses Phase 1's `get_chain_for_study` + `derive_chain_stop_reason` + `select_best_link`. No chain math re-derived.

### FR-3: Repo helpers `bulk_mark_superseded` + `reinstate_from_superseded`

- Requirement:
  - The system **MUST** expose `bulk_mark_superseded(db: AsyncSession, *, study_ids: list[str]) -> list[str]` at `backend/app/db/repo/proposal.py`. Implementation: conditional UPDATE-RETURNING gated on `WHERE study_id IN :study_ids AND status='pending'`. Returns the IDs of the rows actually transitioned (zero-row case returns `[]`).
  - The system **MUST** expose `reinstate_from_superseded(db: AsyncSession, *, proposal_id: str) -> Proposal` at the same file. Implementation **MUST** follow the existing [`reject_proposal`](../../../../backend/app/db/repo/proposal.py#L249) read-check-mutate precedent so the endpoint can distinguish 404 from 409 (D-17): (1) `row = await get_proposal(db, proposal_id)`, (2) `if row is None: raise LookupError`, (3) `if row.status != 'superseded': raise InvalidStateTransition(proposal_id, row.status)`, (4) `row.status = 'pending'; await db.flush(); return row`. The repo function **MUST NOT** use the conditional-UPDATE pattern here — that pattern collapses both error cases into one zero-row signal and cannot drive the endpoint's 404-vs-409 contract. Caller commits.
  - Both helpers **MUST** export from `backend/app/db/repo/__init__.py` `__all__`.
- Notes: mirrors the conditional-UPDATE precedent at [`update_proposal_for_digest`](../../../../backend/app/db/repo/proposal.py#L121-L126) and [`reject_proposal`](../../../../backend/app/db/repo/proposal.py#L249).

### FR-4: Chain-traversal proposal-filter widening (co-requisite of FR-2)

- Requirement:
  - The system **MUST** widen the proposal filter at [`backend/app/db/repo/study.py:341`](../../../../backend/app/db/repo/study.py#L341) from `Proposal.status != "rejected"` to `Proposal.status.notin_(("rejected", "superseded"))`.
  - The cascading consumer `list_recent_completed_chains` ([`backend/app/db/repo/study.py:387`](../../../../backend/app/db/repo/study.py#L387)) inherits the widened filter automatically; no separate change required.
  - The `/api/v1/studies/{study_id}/chain` endpoint's `proposal_id_by_link_id` field **MUST** therefore omit any link whose only proposal is `superseded`.
- Notes: This is the single most common silent-regression risk — without this widening, the chain panel still resolves superseded proposals as "newest non-rejected," defeating Phase 3.

### FR-5: `_stop` orchestrator wires the rollup into the existing transaction

- Requirement:
  - After the existing `create_proposal` call inside `_stop` ([`backend/workers/orchestrator.py:693-740`](../../../../backend/workers/orchestrator.py#L693-L740)), the system **MUST** conditionally call `services.chain_rollup.mark_non_winning_chain_proposals_superseded(db, study_id=study_id)` when the newly-completed link could be a tail-of-multi-link-chain.
  - Cheap heuristic gate (avoid wasted SELECTs on anchors that can't have descendants): skip when `study.parent_study_id is None AND (study.config or {}).get("auto_followup_depth") in (None, 0)`.
  - The rollup **MUST** run in the same transaction as the link's own `pending` proposal insert. On `study_state.InvalidStateTransition`, the existing `db.rollback()` path applies (the rollup never commits independently).
  - Late-arriving links (e.g., a delayed child completing minutes after the tail) **MUST NOT** require special handling — the helper's idempotency means each successive call re-supersedes the same losers no-op-style.
- Notes: Rejected alternatives (Arq job after digest; periodic reconciler) — see §4 anti-patterns.

### FR-6: `POST /api/v1/proposals/{proposal_id}/reinstate` endpoint + `?status=` list-widening

- Requirement:
  - The system **MUST** expose `POST /api/v1/proposals/{proposal_id}/reinstate` at [`backend/app/api/v1/proposals.py`](../../../../backend/app/api/v1/proposals.py).
  - Request body: empty `{}` (single-purpose verb; the proposal_id in the path is the sole input).
  - Response (200 OK): the full `ProposalDetail` payload reflecting the new `status='pending'` (and `pr_state`/`pr_url`/etc unchanged).
  - The system **MUST** add an `?include_superseded: bool = False` query param to `list_proposals_endpoint`; the existing `status_filter: ProposalStatusWire | None` parameter stays single-value (D-15 revised). The repo helper's existing `Proposal.status == status` filter stays unchanged; a new `include_superseded` kwarg, when `False`, appends `Proposal.status != 'superseded'` whenever `?status=` is not explicitly set. Backward-compatible: every existing URL contract unchanged; net change is one new optional query param + one new repo kwarg.
  - Error codes (both reuse existing catalog entries — D-16 — to match the [`reject_proposal_endpoint`](../../../../backend/app/api/v1/proposals.py#L463-L500) precedent and avoid frontend branching surface):
    - `404` `PROPOSAL_NOT_FOUND` — proposal id does not exist. `retryable: false`.
    - `409` `INVALID_STATE_TRANSITION` — proposal exists but `status != 'superseded'` (i.e., already `pending`, or `pr_opened`/`pr_merged`/`rejected`). `retryable: false`. Message includes the current status (e.g., `"proposal {id} is in status 'pending'; only 'superseded' proposals can be reinstated"`). Recovery: refresh the page; the proposal is no longer in a reinstatable state. Same code the reject endpoint already raises — no new error code introduced.
- Notes: The endpoint **MUST** emit a `chain_proposal_reinstated` structlog INFO event (FR-7) before commit.

### FR-7: Telemetry — structlog INFO events

- Requirement:
  - The system **MUST** emit `chain_proposals_superseded` (INFO) **after the caller commits**, NOT inside the service helper (D-19). The helper returns `(count, ids)` to its caller; the caller (`_stop`) emits the structlog event from within its own scope after `await db.commit()` succeeds. Emitting before commit risks the transaction rolling back while the log claims a durable state change. Fields: `study_id` (the triggering link), `chain_anchor_id` (from `ChainTraversalResult.anchor_id`), `best_link_id`, `superseded_count` (len of returned IDs), `superseded_proposal_ids` (list).
  - The system **MUST** emit `chain_proposal_reinstated` (INFO) inside the reinstate endpoint handler **after `await db.commit()`** (D-19). Fields: `proposal_id`, `study_id`, `prior_status` (always `"superseded"`).
- Notes: When MVP3's `audit_log` lands, both promote per the §6 matrix.

### FR-8: Frontend filter + reinstate button + glossary

- Requirement:
  - The `/proposals` index URL contract **MUST** default to excluding `?status=superseded` (other statuses unchanged). A "Show superseded" toggle (checkbox, label) appends `superseded` to the status set; URL contract round-trips bidirectionally.
  - The `StatusBadge` `proposal:` variant map **MUST** add `superseded: 'outline'` (re-using the `outline` variant alongside `rejected` — visual distinction comes from the badge label text + the row's lower visual weight in the list, not a new variant per D-12).
  - The `/proposals/[id]` detail page **MUST** render a "Reinstate" button visible only when `proposal.status === 'superseded'`. Placement: alongside the existing "Open PR" / "Reject" affordances (D-11). On click → POST `/api/v1/proposals/{id}/reinstate`; on success → invalidate `['proposals']` + the per-id detail query.
  - The glossary **MUST** gain two new keys: `proposal.status.superseded` ("Marked as a non-winning sibling of an overnight-chain proposal. The chain identified a better alternative; this proposal is preserved for audit and can be reinstated if you want to ship it instead.") and `proposal.reinstate` ("Flip this superseded proposal back to pending so you can ship it. Useful when the chain's automatically-chosen winner doesn't match your judgment.").
- Notes: Both glossary keys MUST be referenced by `<InfoTooltip>` mounts on the badge + button respectively (mirrors the established pattern from `feat_contextual_help`).

---

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/proposals/{proposal_id}/reinstate` | Flip a superseded proposal back to `pending`. | `PROPOSAL_NOT_FOUND` (404), `INVALID_STATE_TRANSITION` (409) |
| `GET` | `/api/v1/proposals?include_superseded=true` | **Additive flag (D-15 revised):** the existing `?status=` parameter stays single-value (`ProposalStatusWire \| None`). New optional `?include_superseded: bool = False`. When `false` (default) AND no `?status=` filter, the backend implicitly appends `Proposal.status != 'superseded'`. When `true`, all five statuses are returned. When `?status=` is explicitly set, the `include_superseded` flag is ignored (explicit beats implicit). | `VALIDATION_ERROR` (422) on unknown values |

### 8.2 Contract rules

- Error body **MUST** use the standard envelope: `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }`.
- The reinstate endpoint **MUST** return `200 OK` (not `204 No Content`) — the body carries the updated `ProposalDetail` so the frontend can update its cache without a refetch.
- Status codes **MUST** be deterministic per scenario per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md).

### 8.3 Response examples

**Success — `POST /api/v1/proposals/{id}/reinstate` → 200 OK:**
```json
{
  "id": "01972b9c-...",
  "study_id": "01972b8a-...",
  "status": "pending",
  "config_diff": {"mm": {"from": "75%", "to": "60%"}},
  "metric_delta": {"from": 0.412, "to": 0.487, "absolute": 0.075, "relative": 0.182},
  "pr_state": null,
  "pr_url": null,
  "created_at": "2026-06-05T12:34:56Z",
  "...": "(remaining ProposalDetail fields unchanged)"
}
```

**Failure — proposal does not exist → 404 PROPOSAL_NOT_FOUND:**
```json
{
  "detail": {
    "error_code": "PROPOSAL_NOT_FOUND",
    "message": "Proposal '01972b9c-...' not found.",
    "retryable": false
  }
}
```

**Failure — proposal is not in `superseded` status → 409 INVALID_STATE_TRANSITION:**
```json
{
  "detail": {
    "error_code": "INVALID_STATE_TRANSITION",
    "message": "proposal '01972b9c-...' is in status 'pending'; only 'superseded' proposals can be reinstated",
    "retryable": false
  }
}
```

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `?status` (GET /api/v1/proposals) | `pending`, `pr_opened`, `pr_merged`, `rejected`, **`superseded`** | `backend/app/db/repo/proposal.py` (`ProposalStatusFilter` Literal) + `backend/app/api/v1/schemas.py` (`ProposalStatusWire` Literal) | `ui/src/lib/enums.ts` (`PROPOSAL_STATUS_VALUES`) consumed by the proposals filter chip group at `ui/src/app/proposals/page.tsx`; `StatusBadge` variant map at `ui/src/components/common/status-badge.tsx:23-28` |
| `Proposal.status` (response) | same five values | same | same |

### 8.5 Error code catalog

**No new error codes introduced (D-16).** The reinstate endpoint reuses both the `PROPOSAL_NOT_FOUND` (404) and `INVALID_STATE_TRANSITION` (409) codes already raised by the [`reject_proposal_endpoint`](../../../../backend/app/api/v1/proposals.py#L463-L500). This keeps the proposals router's error-code surface tight (frontends already branch on `INVALID_STATE_TRANSITION` for wrong-status writes); message text disambiguates the specific transition. The `?status=` widening (D-15) raises the standard `VALIDATION_ERROR` (422) for unknown values via Pydantic — no spec change.

---

## 9) Data model and state transitions

### Modified table: `proposals`

- Modify CHECK constraint `proposals_status_check` to admit `superseded`:
  - Before: `status IN ('pending', 'pr_opened', 'pr_merged', 'rejected')`
  - After: `status IN ('pending', 'pr_opened', 'pr_merged', 'rejected', 'superseded')`

No new columns, no new indexes, no new tables.

### Migration `0023_proposals_superseded_status` sketch

```python
revision: str = "0023"
down_revision: str | None = "0022"

def upgrade() -> None:
    op.drop_constraint("proposals_status_check", "proposals", type_="check")
    op.create_check_constraint(
        "proposals_status_check",
        "proposals",
        "status IN ('pending', 'pr_opened', 'pr_merged', 'rejected', 'superseded')",
    )

def downgrade() -> None:
    # Hard-guard (Q4 locked option (a)): refuse if any superseded rows exist.
    bind = op.get_bind()
    count = bind.execute(
        sa.text("SELECT COUNT(*) FROM proposals WHERE status = 'superseded'")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Cannot downgrade {revision}: {count} proposal row(s) with status='superseded'. "
            f"Update them to 'rejected' first: UPDATE proposals SET status='rejected' WHERE status='superseded';"
        )
    op.drop_constraint("proposals_status_check", "proposals", type_="check")
    op.create_check_constraint(
        "proposals_status_check",
        "proposals",
        "status IN ('pending', 'pr_opened', 'pr_merged', 'rejected')",
    )
```

### Required invariants

- `bulk_mark_superseded`'s conditional UPDATE `WHERE status='pending'` ensures already-shipped (`pr_opened`/`pr_merged`) and already-rejected proposals are never touched by the rollup (Q3 locked).
- `reinstate_from_superseded`'s conditional UPDATE `WHERE status='superseded'` ensures non-superseded proposals can't be flipped to `pending` via the endpoint.
- A `superseded` row can never appear before migration 0023 runs (CHECK enforces).

### State transitions

**Proposal status state machine (Phase 3 additions in bold):**

```
   ┌──────────┐  reject_proposal  ┌────────────┐
   │ pending  │ ─────────────────▶│  rejected  │
   └────┬─┬───┘                   └────────────┘
        │ │
        │ └─── mark_proposal_pr_opened ─────────────▶ pr_opened ──(webhook)─▶ pr_merged
        │
        │  bulk_mark_superseded
        ▼  (system, on chain rollup)
   ┌──────────────┐
   │  superseded  │ ◀──┐
   └──────┬───────┘    │ reinstate_from_superseded (operator)
          └────────────┘
```

**Allowed transitions:**
- `pending → superseded` (system-initiated via `bulk_mark_superseded`)
- `superseded → pending` (operator-initiated via `reinstate_from_superseded`)

**Forbidden transitions (enforced by conditional UPDATEs):**
- `pr_opened → superseded` / `pr_merged → superseded` (rollup `WHERE status='pending'` skips)
- `rejected → superseded` (rollup `WHERE status='pending'` skips)
- `pr_opened → pending` / `pr_merged → pending` / `rejected → pending` (reinstate `WHERE status='superseded'` skips)

### Idempotency/replay behavior

- The rollup's `WHERE status='pending'` clause makes it a natural no-op on re-run for the same chain (after the first call transitioned losers, they're now `superseded` and won't match the WHERE).
- Late-arriving links walk the now-longer chain and call the helper again; idempotent — same losers, already `superseded`, zero rows matched, zero new structlog events.
- The reinstate endpoint's read-check (D-17) makes a duplicate POST after a successful first one return `409 INVALID_STATE_TRANSITION` (the proposal is now `pending`); UI handles this by refreshing the cache.

---

## 10) Security, privacy, and compliance

- **Threats:**
  - (T1) Malicious operator reinstates a `superseded` proposal to ship a worse config. Mitigation: out of scope — operators are trusted (single-tenant, no auth surface).
  - (T2) Race condition where `_stop` rolls up losers while a separate operator flow opens a PR for a loser. Mitigation: `bulk_mark_superseded`'s `WHERE status='pending'` + `mark_proposal_pr_opened`'s `WHERE status='pending'` are mutually exclusive — whichever transaction commits first wins the row; the loser raises `InvalidStateTransition` and the operator sees a friendly error.
  - (T3) Stale chain traversal where a UI session built against pre-Phase-3 data shows superseded proposals as winners. Mitigation: TanStack Query invalidates the chain query on supersession (server-side widened filter makes the next refetch correct).
- **Controls:** All status transitions go through repo helpers using conditional UPDATEs — no direct ORM mutations. The reinstate endpoint emits a structlog INFO before commit (auditable via log scraping pre-MVP3; promoted to `audit_log` row at MVP3+).
- **Secrets/key handling:** None — Phase 3 introduces no secrets.
- **Auditability:** Pre-MVP3 via structlog INFO events. MVP3+ via `audit_log` rows (forward-declared in §6).
- **Data retention/deletion/export impact:** None — `superseded` rows are preserved indefinitely (same as `rejected`).

---

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** No new pages. The `/proposals` index gains a single "Show superseded" toggle; `/proposals/[id]` gains a "Reinstate" button visible only when relevant.
- **Labeling taxonomy:**
  - "Show superseded" (checkbox label on `/proposals` index) — present tense, matches existing filter chip vocabulary.
  - "Superseded" (badge label inside `<StatusBadge kind="proposal" value="superseded" />`) — single word, matches the existing "Pending" / "PR Opened" / "PR Merged" / "Rejected" set.
  - "Reinstate" (button label on `/proposals/[id]` when `status='superseded'`) — single word verb; tooltip explains the consequence.
- **Content hierarchy:** On `/proposals/[id]`, the "Reinstate" button sits alongside the existing "Open PR" / "Reject" affordances. Visual priority unchanged: ConfigDiffPanel (top), FullParamSpacePanel (below, added by PR #446), action buttons (bottom).
- **Progressive disclosure:** Superseded proposals are hidden from `/proposals` by default; operators opt in. The badge + reinstate flow is only visible to operators who explicitly toggle "Show superseded."
- **Relationship to existing pages:** Extends `/proposals` (index + detail) — no new routes.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| `<StatusBadge kind="proposal" value="superseded" />` | "Marked as a non-winning sibling of an overnight-chain proposal. The chain identified a better alternative; this proposal is preserved for audit and can be reinstated if you want to ship it instead." | `info icon click` | `<InfoTooltip glossaryKey="proposal.status.superseded">` adjacent to the badge |
| "Reinstate" button on `/proposals/[id]` | "Flip this superseded proposal back to pending so you can ship it. Useful when the chain's automatically-chosen winner doesn't match your judgment." | `info icon click` | `<InfoTooltip glossaryKey="proposal.reinstate">` adjacent to the button |
| "Show superseded" toggle on `/proposals` index | "Show proposals that were automatically marked as non-winners by an overnight chain. Hidden by default to focus on actionable proposals." | `hover` / `focus` on the checkbox label | inline helper text below the checkbox |

All three keys land in `ui/src/lib/glossary.ts` per FR-8.

### Primary flows

1. **System rollup on chain termination (no operator interaction):**
   - Operator opts into an overnight 4-link chain in the wizard.
   - Chain runs; the tail link completes.
   - `_stop` opens its existing transaction: completes the tail study + creates its `pending` proposal + calls `mark_non_winning_chain_proposals_superseded(db, study_id=tail_id)`.
   - Rollup walks the chain, picks `best_link_id` via `select_best_link`, builds the loser set, conditional-UPDATEs losers' pending proposals to `superseded`. Structlog INFO `chain_proposals_superseded` fires.
   - Operator opens `/proposals` next morning: only 1 row (the chain's winner) shows; clutter avoided.

2. **Operator inspects + reinstates a superseded proposal:**
   - Operator on `/proposals` checks "Show superseded."
   - URL becomes `…?status=pending&status=superseded` (existing query-param contract).
   - Superseded rows appear with the `superseded` badge + tooltip explaining what it means.
   - Operator clicks a superseded row → `/proposals/[id]` detail page.
   - "Reinstate" button visible; tooltip explains the consequence.
   - Operator clicks → POST `/reinstate` → 200 → cache invalidates → status flips to `pending` in the UI.
   - Operator now sees the "Open PR" button (it gates on `status='pending'` per existing logic).

### Edge/error flows

- **Reinstate a proposal that's no longer superseded** (e.g., the operator opened two tabs, reinstated in one): the second POST returns `409 INVALID_STATE_TRANSITION`. UI shows a toast: "This proposal is no longer superseded — refreshing." Then invalidates the cache.
- **Reinstate-then-late-rollup** (D-18): an operator reinstates a superseded proposal mid-chain, then a late-arriving link completes and the rollup walks the chain again. The reinstated proposal is now `pending`; if it's still not the best link, the rollup re-supersedes it. **This is expected behavior for Phase 3 scope** — the rollup represents the system's current best understanding of "who's the winner." Operator-facing mitigation: wait until the chain has terminally completed before reinstating (the chain panel's `stop_reason` field shows when it's safe), OR open a PR for the reinstated proposal before another link completes (`pr_opened` is protected from rollup per FR-3's `WHERE status='pending'` guard). A future feature could add a `protected` flag that exempts a row from the rollup; deferred from Phase 3 to keep scope tight.
- **Reinstate a deleted proposal:** returns `404 PROPOSAL_NOT_FOUND`. UI shows a toast: "Proposal no longer exists." Navigates back to `/proposals`.
- **Concurrent supersession + open_pr race** (T2 above): one transaction's `WHERE status='pending'` clause wins; the other raises `InvalidStateTransition`. Existing error mapping translates this to `409 INVALID_PROPOSAL_STATE` (existing code).
- **Chain with all-failed links + 1 completed link:** `select_best_link` returns the one completed link's id; there are no `pending` losers to supersede; rollup early-returns 0; no structlog event.
- **Chain with all-failed links + no completed link:** `select_best_link` returns `None`; rollup early-returns 0; no structlog event.

---

## 12) Given/When/Then acceptance criteria

### AC-1: Migration round-trip (FR-1)

- Given a clean Postgres at Alembic head `0022_solr_engine_auth_check`
- When the operator runs `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
- Then the `proposals_status_check` CHECK constraint admits `superseded` after the first upgrade, rejects it after the downgrade, and admits it again after the re-upgrade — no errors, no orphan rows.

### AC-2: Downgrade hard-guard refuses if `superseded` rows exist (FR-1, Q4)

- Given the upgrade has been applied and at least one row carries `status='superseded'`
- When the operator runs `alembic downgrade -1`
- Then the migration aborts with `RuntimeError` whose message names the row count and the recommended manual UPDATE.
- Example values:
  - Input: 3 rows with `status='superseded'`
  - Expected: `RuntimeError("Cannot downgrade 0023: 3 proposal row(s) with status='superseded'. Update them to 'rejected' first: UPDATE proposals SET status='rejected' WHERE status='superseded';")`

### AC-3: `bulk_mark_superseded` returns transitioned IDs (FR-3)

- Given three studies `S1`, `S2`, `S3` each with one `pending` proposal `P1`, `P2`, `P3`
- When `bulk_mark_superseded(db, study_ids=[S1, S2, S3])` runs
- Then the function returns the three proposal IDs in arbitrary order; all three rows now carry `status='superseded'`; the call is idempotent (re-running returns `[]`).

### AC-4: `bulk_mark_superseded` skips non-`pending` rows (FR-3, Q3)

- Given study `S1` with a `pr_opened` proposal, `S2` with a `rejected` proposal, `S3` with a `pending` proposal
- When `bulk_mark_superseded(db, study_ids=[S1, S2, S3])` runs
- Then only `S3`'s proposal transitions to `superseded`; the function returns `[S3's proposal id]`; `S1` and `S2` are untouched.

### AC-5: `reinstate_from_superseded` flips `superseded → pending` (FR-3)

- Given proposal `P1` with `status='superseded'`
- When `reinstate_from_superseded(db, proposal_id=P1.id)` runs
- Then the function returns the updated `Proposal` row with `status='pending'`; subsequent reads confirm; the second call raises `InvalidStateTransition`.

### AC-6: `mark_non_winning_chain_proposals_superseded` integration on a 3-link chain (FR-2, FR-4)

- Given an anchor study `A`, child `B` (completed, best metric 0.45), grandchild `C` (completed, best metric 0.52); each with one `pending` proposal `Pa`, `Pb`, `Pc`; the chain has terminated (`stop_reason='no_lift'`)
- When `mark_non_winning_chain_proposals_superseded(db, study_id=C.id)` runs and the caller commits
- Then `Pc` remains `pending` (the winner per `select_best_link`); `Pa` and `Pb` transition to `superseded`; `/api/v1/studies/A/chain` then returns `proposal_id_by_link_id = {C.id: Pc.id}` (Pa and Pb omitted per FR-4); structlog INFO `chain_proposals_superseded` fires once with `superseded_count=2`.

### AC-7: `_stop` invokes rollup inside its existing transaction (FR-5)

- Given a 2-link chain anchor `A` (completed, `pending` proposal `Pa`) and child `B` (running, no proposal yet) with `B.config.auto_followup_depth=1`
- When `B` completes and `_stop` runs
- Then in a single committed transaction: `B.status='completed'`, `Pb` exists with `status='pending'`, AND `Pa` transitions to `superseded` (assuming B's metric beats A's per `select_best_link`); structlog INFO `chain_proposals_superseded` fires.

### AC-8: `_stop` rollup skipped for anchors with no chain potential (FR-5 heuristic)

- Given a standalone study `S` with `parent_study_id is None` AND `config.auto_followup_depth = 0`
- When `S` completes via `_stop`
- Then no rollup helper call is made (zero extra DB SELECTs); existing `_stop` behavior unchanged byte-identical.

### AC-9: `_stop` rollup is atomic with the completion transaction (FR-5)

- Given a chain about to terminate, but a forced `study_state.InvalidStateTransition` raised mid-transaction (simulated via a test-only monkeypatch)
- When `_stop` runs
- Then both the `complete_study` UPDATE AND the rollup's loser UPDATE roll back together; no row transitions; existing `_stop` rollback path applies.

### AC-10: Late-arriving link re-rolls-up no-op (FR-2 idempotency)

- Given a 3-link chain where `_stop` already ran on link `C` and superseded `Pa` + `Pb`
- When a fourth-link `D` (late-arriving) completes and `_stop` runs again with `study_id=D.id`
- Then `Pd` is created `pending`; `Pa` + `Pb` remain `superseded` (already in that state); `Pc` may transition `pending → superseded` if `D` beats `C` per `select_best_link`, OR remain `pending` if `C` still wins; structlog INFO fires only if `superseded_count > 0`.

### AC-11: `POST /api/v1/proposals/{id}/reinstate` happy path (FR-6)

- Given proposal `P` with `status='superseded'`
- When the operator POSTs `/api/v1/proposals/P/reinstate` with body `{}`
- Then response is `200 OK` carrying the full `ProposalDetail` with `status='pending'`; structlog INFO `chain_proposal_reinstated` fires with `prior_status='superseded'`.

### AC-12: Reinstate 404 on unknown proposal (FR-6)

- Given no proposal with id `00000000-0000-0000-0000-000000000000`
- When the operator POSTs `/api/v1/proposals/00000000-0000-0000-0000-000000000000/reinstate`
- Then response is `404` with envelope `{ "detail": { "error_code": "PROPOSAL_NOT_FOUND", "message": "...", "retryable": false } }`.

### AC-13: Reinstate 409 on non-superseded proposal (FR-6)

- Given proposal `P` with `status='pending'`
- When the operator POSTs `/api/v1/proposals/P/reinstate`
- Then response is `409` with envelope `{ "detail": { "error_code": "INVALID_STATE_TRANSITION", "message": "proposal 'P' is in status 'pending'; only 'superseded' proposals can be reinstated", "retryable": false } }` (D-16 reuses the existing reject-endpoint code).

### AC-14: `/proposals` index URL contract round-trips with `?include_superseded=true` (FR-6, FR-8)

- Given the operator on `/proposals` with default URL (no `?include_superseded` param)
- When they activate the "Show superseded" filter chip
- Then the URL gains `?include_superseded=true`; the backend response now includes superseded rows; navigating with that URL directly renders the chip as active. Single-value `?status=` backward compat (D-15 revised): a manual `?status=pending` URL still returns only pending rows (explicit `?status=` beats implicit `include_superseded`).

### AC-15: StatusBadge renders the `superseded` variant (FR-8)

- Given a row whose `proposal.status === 'superseded'`
- When the row renders inside `<StatusBadge kind="proposal" value="superseded" />`
- Then the badge text reads "Superseded" with the `outline` Tailwind variant; the adjacent `<InfoTooltip glossaryKey="proposal.status.superseded">` mounts correctly.

### AC-16: Reinstate button visibility gating (FR-8)

- Given the operator on `/proposals/[id]` for a `superseded` proposal
- When the page renders
- Then the "Reinstate" button is visible alongside other action buttons; clicking it issues `POST /reinstate`; on success, the page invalidates `['proposals', id]` and the status flips to `pending` without a full page reload.

### AC-17: Reinstate button hidden for non-superseded statuses (FR-8)

- Given the operator on `/proposals/[id]` for a `pending` (or `pr_opened`, `pr_merged`, `rejected`) proposal
- When the page renders
- Then the "Reinstate" button is NOT in the DOM (asserted via `queryByRole('button', { name: /reinstate/i })` returning null).

### AC-18: Glossary keys lock (FR-8)

- Given the glossary file `ui/src/lib/glossary.ts`
- When the test `lib/glossary.test.ts` runs
- Then both `proposal.status.superseded` and `proposal.reinstate` keys exist with non-empty text values; the test fails if either key is removed (value-lock).

---

## 13) Non-functional requirements

- **Performance:** The rollup adds **one extra `get_chain_for_study` call + one conditional UPDATE** per chain-tail `_stop` invocation. `get_chain_for_study` is bounded at 6 links per the linear-chain invariant — its SELECTs are indexed; the UPDATE matches at most 5 rows. p99 < 50ms additional latency per `_stop` call. The reinstate endpoint is a single conditional UPDATE-RETURNING; p99 < 30ms.
- **Reliability:** The rollup MUST be exception-safe — any unexpected error (e.g., `repo.get_chain_for_study` raises) MUST propagate to the existing `_stop` exception handler (`study_state.InvalidStateTransition` triggers rollback). Chain-link completion reliability MUST NOT regress vs the legacy path; tests cover the rollback case.
- **Operability:** Two new structlog INFO event types (`chain_proposals_superseded`, `chain_proposal_reinstated`). Runbook section in `docs/03_runbooks/agent-debugging.md` explains how to grep + interpret. No new env vars, metrics, alerts.
- **Accessibility:** "Reinstate" button MUST carry `aria-label="Reinstate proposal"`. "Show superseded" toggle MUST be keyboard-accessible (standard checkbox) and labeled.

---

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/`):**
  - `services/test_chain_rollup_service.py` (new) — `mark_non_winning_chain_proposals_superseded` matrix: chain not found → `(0, [])`; single-link chain → `(0, [])`; in_flight stop_reason → `(0, [])`; no completed link → `(0, [])`; happy path returns `(count, ids)`. Mocks repo + select_best_link. Pure unit; no DB.
- **Integration tests (`backend/tests/integration/`):**
  - `db/test_proposal_supersession.py` (new) — `bulk_mark_superseded` + `reinstate_from_superseded` against the **real Postgres test DB** (D-20 — fixed from the Pass-1 unit-test placement). Tests the Postgres-specific CHECK constraint behavior and `UPDATE … RETURNING` semantics which an in-memory SQLite session cannot represent. Marked `@pytest.mark.integration`.
  - `workers/test_orchestrator_stop_supersedes_losers.py` (new) — DB-backed: seed 3-link chain, complete tail, assert atomic supersession (AC-6, AC-7, AC-9).
  - `workers/test_orchestrator_stop_skips_anchor.py` (new) — anchor-only study completion adds no rollup overhead (AC-8 — verify zero matching log records).
  - `db/test_chain_traversal_filter_widening.py` (new) — `get_chain_for_study` after Cap 2 — superseded proposals don't surface as `proposal_id_by_link_id` (FR-4).
  - `workers/test_orchestrator_late_link.py` (new) — late-arriving link re-rolls-up no-op (AC-10).
  - `services/test_chain_rollup_real_chain.py` (new) — real `_stop` integration with real chain (AC-6 end-to-end).
- **Contract tests (`backend/tests/contract/`):**
  - `test_proposals_reinstate_contract.py` (new) — happy path 200 (AC-11), 404 PROPOSAL_NOT_FOUND (AC-12), 409 INVALID_STATE_TRANSITION (AC-13 — reuses existing code per D-16).
  - `test_proposals_filter_contract.py` (extend) — `?status=superseded` accepted, `?status=pending&status=rejected` multi-value accepted (D-15), `ProposalStatusWire` allowlist literal regression-locked.
  - `test_error_codes.py` (extend if needed) — no new error code introduced (D-16); only verify `INVALID_STATE_TRANSITION` is still listed (existing).
- **Vitest (UI unit/component) (`ui/src/__tests__/`):**
  - `components/proposals/proposals-list-page.test.tsx` (extend) — default URL excludes `superseded`; toggle appends; round-trip (AC-14).
  - `components/proposals/proposal-detail-page.test.tsx` (extend) — Reinstate button visibility gating + click → mutation (AC-15, AC-16, AC-17).
  - `components/common/status-badge.test.tsx` (extend) — superseded variant renders (AC-15).
  - `lib/glossary.test.ts` (extend) — value-lock for both new keys (AC-18).
  - `lib/enums-proposal-status-discipline.test.ts` (new) — value-lock for `PROPOSAL_STATUS_VALUES` (mirrors the existing `enums-convergence-discipline.test.ts` pattern).
- **E2E (`ui/tests/e2e/`):**
  - `proposals-superseded-reinstate.spec.ts` (new) — seed via API helpers: anchor + child chain (depth=1, autopilot completed), assert losers transition to `superseded` in DB, navigate to `/proposals`, check "Show superseded" toggle, click into a superseded row, click "Reinstate," assert status flips to `pending` in the UI without page reload. Real backend — no `page.route()` mocking.

---

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md` — mention the additive `superseded` value on `ProposalStatusWire`; note the `?status=` query-param widening from singular to list (D-15). No new error code (D-16).
- `docs/01_architecture/data-model.md` — update the proposals-status state machine diagram + note (no schema diagram change beyond the CHECK constraint).
- `docs/03_runbooks/agent-debugging.md` — add a "Chain rollup events" subsection explaining `chain_proposals_superseded` + `chain_proposal_reinstated` grep + interpretation.
- `docs/03_runbooks/proposal-state-management.md` (new) — operator-facing explanation of the supersession model: what it means, why some proposals are hidden by default, how to reinstate, how `rejected` differs.
- `docs/08_guides/tutorial-first-study.md` — extend the overnight-chain section with a brief note: "Non-winning proposals are automatically marked superseded; check 'Show superseded' on /proposals to see them."

---

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The supersession behavior is opt-out at the UI level (the toggle); the underlying rollup runs unconditionally for multi-link chains.
- **Migration/backfill expectations:** Forward migration is a CHECK constraint extension (zero rows affected). Backfill: no existing proposals retroactively become `superseded` — only new chain terminations populate the new state. Pre-existing duplicated `pending` rows from chains that ran before Phase 3 stay `pending`; the operator can manually `UPDATE` them if desired, but no automated backfill ships.
- **Operational readiness gates:** Standard `pr.yml` suite (backend lint + typecheck + tests + coverage + frontend lint + tsc + vitest + Next.js build + docker buildx); CodeQL clean; the `generated-artifacts-fresh` gate green after running `scripts/regen-generated-artifacts.sh`.
- **Release gate:** All AC-1 through AC-18 pass; the chain-traversal regression test (FR-4) confirms superseded proposals are correctly hidden from `/chain`; the legacy proposals-list + status-badge tests continue passing unmodified.

---

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (schema + mirrors) | AC-1, AC-2 | Story 1 (migration + mirrors) | migration round-trip integration; `test_proposals_filter_contract.py`; `enums-proposal-status-discipline.test.ts` | `api-conventions.md`, `data-model.md` |
| FR-2 (service helper) | AC-6, AC-7, AC-9, AC-10 | Story 2 (service `chain_rollup.py`) | `test_chain_rollup_service.py`; `test_chain_rollup_real_chain.py` | — |
| FR-3 (repo helpers) | AC-3, AC-4, AC-5 | Story 3 (repo helpers) | `test_proposal_supersession.py` | — |
| FR-4 (chain-traversal filter widening) | AC-6, AC-10 | Story 2 (one-line widening, paired with FR-2) | `test_chain_traversal_filter_widening.py` | `data-model.md` |
| FR-5 (`_stop` wiring) | AC-7, AC-8, AC-9, AC-10 | Story 4 (`_stop` change) | `test_orchestrator_stop_supersedes_losers.py`; `test_orchestrator_stop_skips_anchor.py`; `test_orchestrator_late_link.py` | — |
| FR-6 (reinstate endpoint) | AC-11, AC-12, AC-13 | Story 5 (API endpoint) | `test_proposals_reinstate_contract.py`; `test_error_codes.py` | `api-conventions.md` |
| FR-7 (telemetry) | AC-6, AC-11 | inline with Stories 2 + 5 | log-event assertions in stories' integration tests | runbook |
| FR-8 (frontend) | AC-14, AC-15, AC-16, AC-17, AC-18 | Story 6 (UI) | `proposals-list-page.test.tsx`; `proposal-detail-page.test.tsx`; `status-badge.test.tsx`; `glossary.test.ts`; `proposals-superseded-reinstate.spec.ts` | `tutorial-first-study.md`, runbook |

---

## 18) Definition of feature done

- [ ] All acceptance criteria AC-1 through AC-18 pass in CI.
- [ ] Backend unit + integration + contract layers green; Alembic round-trips cleanly.
- [ ] UI vitest + Playwright E2E green; existing proposals tests pass unmodified.
- [ ] Coverage gate ≥ 80% holds.
- [ ] `scripts/regen-generated-artifacts.sh` re-run; `generated-artifacts-fresh` CI job green.
- [ ] `docs/01_architecture/api-conventions.md` + `data-model.md` + `docs/03_runbooks/agent-debugging.md` + new `proposal-state-management.md` runbook merged.
- [ ] `tutorial-first-study.md` overnight section updated.
- [ ] No open questions remain in §19.

---

## 19) Open questions and decision log

### Open questions

- **OQ-1 (Q2 from idea) — Reinstate UX placement.** Owner: maintainer. Due: before implementation plan.
  Recommended default (D-11): "Reinstate" button on `/proposals/[id]` detail page only, sitting alongside the existing "Open PR" / "Reject" affordances. Sub-question: should there also be a per-row "Reinstate" link on the `/proposals` index when the "Show superseded" toggle is on, or do we require the operator to click into the detail page first? **Recommendation:** detail-page only — keeps the action surface aligned with other status-mutating actions (Open PR, Reject); a per-row reinstate would dilute the deliberation invariant ("Reinstate is a positive operator decision, not a one-click impulse"). If operator feedback during MVP2 shows the click-through friction is unacceptable, add per-row link in a follow-up `chore_` idea.

### Decision log

- **2026-06-05 — D-1: Single-phase delivery.** Phase 3 is a single deliverable; no Phase 4 deferral planned. The idea's 4 Capabilities ship together in one PR.
- **2026-06-05 — D-2: Migration revision `0023_proposals_superseded_status`.** Follows the `infra_adapter_solr` Story A6 precedent (DROP + ADD CHECK constraint); revision id ≤ 32 chars; round-trip verified.
- **2026-06-05 — D-3 (Q4 locked): Downgrade refuses if `superseded` rows exist.** Option (a) — safest; forces operator to manually decide each row. Rejected (b) `DELETE` — destructive.
- **2026-06-05 — D-4 (Q5 locked): Service helper lands at `backend/app/services/chain_rollup.py`.** New file; not appended to `agent_proposals_dispatch.py` (scope mismatch — chat-agent surface) and not under `auto_followup_post_complete.py` (autopilot-coupled; chain rollup must also cover chat-agent-created chains).
- **2026-06-05 — D-5 (Q1 locked): Best-link flip re-supersedes losers.** Idempotent helper; re-running with a new winner reshuffles. `pr_opened`/`pr_merged` proposals never flip back (`WHERE status='superseded'` guard).
- **2026-06-05 — D-6 (Q3 locked): `rejected` precedence preserved.** Operator-rejected proposals never auto-flip to `superseded` (`WHERE status='pending'` clause in `bulk_mark_superseded`).
- **2026-06-05 — D-7: Phase 2's `<OvernightResultCard>` requires no code changes.** Its best-config CTA renders from `chainSummary.best_link_id` directly; the chain-traversal filter widening (FR-4) automatically prevents superseded proposals from being chosen as a link's "newest non-rejected."
- **2026-06-05 — D-8: `feat_overnight_studies_summary_card`'s `list_recent_completed_chains` requires no code changes.** Reuses `get_chain_for_study`; cascades the FR-4 filter widening automatically.
- **2026-06-05 — D-9: Single-purpose `POST /reinstate` endpoint, not `PATCH status=`.** Sidesteps the broader debate about whether arbitrary status PATCH should be allowed; produces a clear audit signal (one endpoint, one verb, one log event).
- **2026-06-05 — D-10: No periodic reconciler.** The rollup runs in `_stop`'s transaction; idempotent on late-arriving links. A reconciler would silently fix drift the operator should see, breaking the "what the system thinks ≡ what /proposals shows" invariant.
- **2026-06-05 — D-11 (resolves OQ-1 sub-question default): Reinstate button on detail page only.** No per-row link on `/proposals` index. Operator clicks into the detail page first — preserves deliberation surface; aligns with existing status-mutating actions (Open PR, Reject); easy to add a per-row link in a follow-up if friction surfaces.
- **2026-06-05 — D-12: `superseded` reuses the `outline` StatusBadge variant.** No new variant introduced — visual distinction comes from the badge label text and the row's lower visual weight in the list, not the variant. Avoids variant-map sprawl for a single value.
- **2026-06-05 — D-13: Chain panel does NOT surface superseded markers.** Cap 3 (ii) per idea — the chain panel renders only winning links' proposal CTAs. Operators inspect losers via the "Show superseded" toggle on `/proposals`. Simpler than adding a `superseded_proposal_id_by_link_id` companion field.
- **2026-06-05 — D-14: Pre-MVP3 telemetry via structlog INFO; MVP3+ via `audit_log`.** Two event types forward-declared in §6 matrix for the audit-log feature to pick up cleanly.
- **2026-06-05 — D-15 (revised after impl-plan-gen Pass 2): use a `?include_superseded=true` boolean URL flag, NOT a multi-value `?status=` widening.** Pass 2 grepped [`useDataTableUrlState`](../../../../ui/src/hooks/use-data-table-url-state.ts) at `ui/src/hooks/use-data-table-url-state.ts:63` and found `urlState.filters[<key>]` returns a single string per key — extending the hook to support repeated query params would refactor every consumer (studies, clusters, query-sets table surfaces) for one toggle on one page. Cheaper path: leave `?status=` exactly as it is (single-value `ProposalStatusWire | None`), add a new `?include_superseded: bool = False` query param. Backend default (no `?status=`, `include_superseded=false`) returns all four non-superseded statuses; `?include_superseded=true` adds the fifth; explicit `?status=superseded` still returns only superseded. Backward-compatible: every existing URL contract unchanged; net change is one new optional query param. Frontend "Show superseded" toggle mounts as a filter chip (matching the existing `CurrentlyLiveFilterChip` pattern) that flips `?include_superseded` in the URL.
- **2026-06-05 — D-16 (Pass-1 fix): Reuse existing `INVALID_STATE_TRANSITION` (409) code, do NOT introduce `PROPOSAL_NOT_SUPERSEDED`.** The `reject_proposal_endpoint` at [`backend/app/api/v1/proposals.py:463-500`](../../../../backend/app/api/v1/proposals.py#L463-L500) already raises `INVALID_STATE_TRANSITION` for any wrong-status write on a proposal. Reusing keeps the proposals router's error catalog tight (one wrong-status code, not two); frontends already branch on `INVALID_STATE_TRANSITION`; the message field disambiguates "expected superseded" vs "expected pending." Cost of introducing a specific code: zero benefit, doubled branching surface, regression on every future status transition adding a third code.
- **2026-06-05 — D-17 (GPT-5.5 cycle 1, finding #1): `reinstate_from_superseded` uses read-check-mutate, NOT conditional UPDATE.** A pure conditional UPDATE `WHERE id=:id AND status='superseded'` collapses 404 (unknown id) and 409 (wrong status) into a single zero-row signal — the endpoint then cannot drive the deterministic 404-vs-409 contract demanded by FR-6 + AC-12 + AC-13. Mirror the existing [`reject_proposal`](../../../../backend/app/db/repo/proposal.py#L249) precedent (SELECT, branch on None vs wrong-status, mutate via attribute assignment + flush). `bulk_mark_superseded` retains the conditional UPDATE-RETURNING pattern because it has no need to distinguish — losers are addressed by `study_id IN (...)` and silently skipping non-pending rows is the desired idempotency.
- **2026-06-05 — D-18 (GPT-5.5 cycle 1, finding #6): Reinstate-then-late-rollup re-supersedes; expected behavior, not a bug.** The rollup represents the system's current best understanding of "who's the winner." Mitigation surfaces (wait until chain terminates; open a PR for the reinstated proposal before another link completes) are documented in §11 Edge/error flows. A `protected` exemption flag is out of Phase 3 scope (separate feature surface).
- **2026-06-05 — D-19 (GPT-5.5 cycle 1, finding #4): Structlog INFO fires AFTER `db.commit()`, not before.** Pre-commit emission risks the transaction rolling back while the log claims a durable state change. `mark_non_winning_chain_proposals_superseded` returns `(count, ids)` to the caller; the caller (`_stop` for system path; the reinstate endpoint handler for operator path) emits the structlog event after its own commit succeeds.
- **2026-06-05 — D-20 (GPT-5.5 cycle 1, finding #5): Repo helper tests live in integration/, not unit/.** Postgres-specific `UPDATE ... RETURNING` semantics + CHECK constraint behavior cannot be accurately exercised against an in-memory SQLite session; integration tests with the real Postgres test DB are required.
