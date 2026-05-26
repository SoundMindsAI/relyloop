# chore_auto_followup_e2e_chain_seed_helper

**Status:** Closed 2026-05-26 — shipped `POST /api/v1/_test/auto-followup/seed-chain` + `seedAutoFollowupChain()` E2E helper + 3 new tests in `ui/tests/e2e/auto-followup.spec.ts` (chain-panel-parent-link, cascade-radio-default-true, cascade-radio-false). Endpoint design adds an `in_flight_middle` flag (default True) so the immediate parent of the leaf is `status='queued'` and therefore cancellable — required for the cascade-radio test because `canCancel = running || queued`. Backend coverage: 1 new guard test + 4 new integration tests at `backend/tests/integration/test_test_seeding.py`.
**Origin:** `feat_auto_followup_studies` final-review F1 follow-up (PR #223, 2026-05-23).
**Priority:** P3 (test infrastructure; coverage gap not behavior gap).

## Problem

`feat_auto_followup_studies` Story 3.3 specified a Playwright E2E spec that
seeds a 3-node chain (root R → middle M → leaf L) and asserts:

1. Wizard creates a study with `config.auto_followup_depth=2`.
2. Chain panel on **middle node M** renders the parent-link, remaining-depth
   indicator, and direct-children table.
3. Cancel modal cascade radio shows when `M` has an in-flight child.

What shipped in PR #223 ([`ui/tests/e2e/auto-followup.spec.ts`](../../../../ui/tests/e2e/auto-followup.spec.ts)):
test 1 (wizard) + a degenerate test 2 (remaining-depth indicator on a single
root study, no children).

What's missing: tests of the **parent-link** branch, **children-table** branch,
and **cascade radio** — all of which require a study with `parent_study_id`
populated. The public `POST /api/v1/studies` endpoint does NOT accept
`parent_study_id` (it's set only by the worker via `repo.create_study(parent_study_id=...)`
in `backend/workers/auto_followup.py` after a parent's digest fires).

## Why deferred

Driving the production chain end-to-end in a Playwright test would require:
- Wait for a parent study to run trials to completion (~30s minimum)
- Wait for the digest worker to fire
- Wait for the chain worker to enqueue the child
- Wait for the child's `start_study` job to flip status to `queued`/`running`

This is too slow + too flaky for an E2E test that runs in CI smoke. The
canonical solution is a test-only seed endpoint, but adding one to fix a
test gap during a final-review push would have been substantial out-of-scope
work for PR #223.

## Implementation path (estimate: ~60–90 minutes)

1. Add `POST /api/v1/_test/auto-followup/seed-chain` to
   [`backend/app/api/v1/_test.py`](../../../../backend/app/api/v1/_test.py)
   following the pattern of `seed-completed`. Request body:
   ```python
   class SeedChainRequest(BaseModel):
       cluster_id: str
       query_set_id: str
       template_id: str
       judgment_list_id: str
       depth: int = Field(ge=1, le=5)  # number of chain hops to seed
       in_flight_leaf: bool = True  # whether the deepest node is queued/running
   ```
   Implementation: loop `depth+1` times, each iteration calls `repo.create_study`
   with the prior node's `id` as `parent_study_id`. Intermediate nodes get
   `status='completed'` + a stub completed-state. Deepest node gets
   `status='queued'` if `in_flight_leaf=True` else `'completed'`.
   Response: `{root_id, middle_ids: [...], leaf_id}`.

2. Add `seedAutoFollowupChain(args)` helper to
   [`ui/tests/e2e/helpers/seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts)
   that wraps the new endpoint. Register all returned IDs for cleanup.

3. Extend [`ui/tests/e2e/auto-followup.spec.ts`](../../../../ui/tests/e2e/auto-followup.spec.ts)
   with three new tests against a `depth=2, in_flight_leaf=true` chain:
   - **Chain panel on middle node M:** assert parent-link href resolves to
     R, remaining-depth shows N, children-table has one row pointing at L.
   - **Cascade radio on M:** open cancel modal, assert radio is visible
     and defaults to cascade=true; submit, assert POST `?cascade=true` fires.
   - **Cascade radio on M with cascade=false:** click cascade=false radio,
     submit, assert POST `?cascade=false` fires.

## Acceptance criteria

- New test-only endpoint deletes its created rows on teardown via the
  existing cleanup-tag mechanism (no test pollution).
- All three new tests pass in CI smoke + locally.
- The endpoint returns 404 in `ENVIRONMENT=production` (matches
  `_require_development_env` pattern at `backend/app/api/v1/_test.py:56`).

## Workaround for now

Component-layer vitest coverage already exercises parent-link, children-table,
and cascade-radio logic via mocked data at:
- [`ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx`](../../../../ui/src/__tests__/components/studies/auto-followup-chain-panel.test.tsx)
- [`ui/src/__tests__/components/studies/study-action-bar-cascade.test.tsx`](../../../../ui/src/__tests__/components/studies/study-action-bar-cascade.test.tsx)

Real-backend coverage of the wire contract (cascade query param) is asserted
in `backend/tests/unit/api/test_studies_router_chain_endpoints.py` and the
integration tests in `backend/tests/integration/test_auto_followup.py`.

The remaining gap is purely the **integration of UI + real backend** for the
chain-context render paths — which is exactly what an E2E test would catch
and what vitest cannot.
