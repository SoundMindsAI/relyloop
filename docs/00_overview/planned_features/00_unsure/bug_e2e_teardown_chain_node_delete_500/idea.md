# Idea — E2E teardown 500s on chain-node DELETE, leaves orphan rows

**Date:** 2026-05-31
**Status:** Idea — tangential discovery during `feat_overnight_autopilot` (Story 4.2 E2E, PR forthcoming)
**Type:** `bug_`
**Priority:** P2 — pre-existing test-infra flakiness; pollutes the dev DB with orphan rows, doesn't fail the spec under test but erodes teardown reliability.

## Origin

Authoring + running the Story 4.2 E2E (`ui/tests/e2e/overnight-chain.spec.ts`), which seeds an auto-followup chain via `seedAutoFollowupChain` (`POST /api/v1/_test/auto-followup/seed-chain`), the global-teardown emitted `500` on `DELETE /api/v1/_test/studies/{id}` for chain nodes and cascading `409`s on the dependent judgment-lists / query-sets / templates. The same failure shape reproduces with `auto-followup.spec.ts` (which seeds the identical chain shape) — i.e. **not introduced by the new spec**.

## Problem

The E2E global-teardown deletes seeded rows in a fixed order (per `chore_e2e_test_rows_isolation` Story 1.2 cleanup registration). For auto-followup **chains**, the seeded nodes are `queued` studies carrying winner trials + parent/child FK links that the teardown's delete ordering doesn't drain cleanly:
- `DELETE /api/v1/_test/studies/{id}` returns `500` for a chain node (likely an undeleted dependent trial/child FK), leaving the study row.
- The orphaned study then blocks deletion of its judgment-list / query-set / template → cascading `409`s.

Net effect: every chain-seeding E2E run leaks orphan rows into the dev/CI DB. Over many runs this accumulates and can cause unique-constraint collisions on later seeds.

## Proposed capability

1. Reproduce: run `overnight-chain.spec.ts` (or `auto-followup.spec.ts`) and capture the teardown 500 body + the failing study id's dependent rows.
2. Root-cause the delete ordering: the `_test` study-delete endpoint likely needs to cascade child studies + trials before the parent, or the teardown registration order needs FK-safe reversal for chain shapes specifically.
3. Fix at the right layer — either the `_test` delete endpoint cascades chain descendants + trials, or the teardown deletes leaf→root for chains.
4. Add a regression assertion that a chain-seeded test leaves zero orphan study rows after teardown.

## Scope signals

- **Backend:** small — the `/api/v1/_test/studies/{id}` delete path and/or the auto-followup seed-chain teardown.
- **Frontend / E2E:** the teardown helper (`ui/tests/e2e/helpers/` cleanup) + a regression check.
- **Migration / config:** none.
- **Audit events:** N/A (test-only path).

## Why deferred (not fixed inline)

Pre-existing (reproduces on `auto-followup.spec.ts`), test-infra subsystem, not caused by the overnight-autopilot feature. The Story 4.2 spec passes cleanly under it; fixing teardown ordering is a separate, bounded test-infra task.

## Relationship to other work

- Teardown framework: `chore_e2e_test_rows_isolation` (shipped — Story 1.2 established the cleanup registration + FK-safe ordering this chain shape evidently slips through).
- Seeder: `seedAutoFollowupChain` (`ui/tests/e2e/helpers/seed.ts:868`).
