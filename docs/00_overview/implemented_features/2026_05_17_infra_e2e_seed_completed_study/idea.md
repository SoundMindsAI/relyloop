# infra — `seedStudyCompletedWithDigest` E2E helper for digest-panel coverage

**Date:** 2026-05-14
**Status:** Idea — deferred from `feat_contextual_help` Phase 1 Story 3.1
**Origin:** Surfaced while writing Story 3.1's E2E coverage. The plan called for asserting all 26 Phase 1 tooltip triggers in `ui/tests/e2e/studies.spec.ts`; 19 of those (modal + study-header + trials-table) are covered, but the 7 digest-panel triggers (Narrative, Parameter importance, Metric delta, Recommended config, Suggested follow-ups, Open PR enabled, Open PR disabled) only render when `study.status === 'completed' && digestQ.data`. The existing [`seedFullChain` + `seedStudy`](../../../../ui/tests/e2e/helpers/seed.ts) helpers create a queued study; they don't drive it through the orchestrator + digest worker to completion.
**Depends on:** None (helper is additive to `ui/tests/e2e/helpers/seed.ts`).

## Problem

`feat_contextual_help` Phase 1 ships 7 InfoTooltip placements on the digest panel ([`ui/src/components/studies/digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx)) — five section labels plus two Open PR variants (enabled link + `aria-disabled` button). The Phase 1 vitest component tests at [`ui/src/__tests__/components/common/info-tooltip.test.tsx`](../../../../ui/src/__tests__/components/common/info-tooltip.test.tsx) exercise the wrapper itself; the [`studies/[id]/page.test.tsx`](../../../../ui/src/__tests__/app/studies/[id]/page.test.tsx) integration test renders the digest panel when a completed study is mocked. But the **real-backend** E2E suite at [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) cannot easily reach the `status === 'completed'` state because:

1. `seedStudy` creates a study and returns immediately; it does not wait for the orchestrator + Optuna workers to finish trials.
2. Even if the worker is given time to complete, the result is non-deterministic — flaky in CI without a polling-with-timeout strategy.
3. The digest worker runs separately (consuming `study.completed_at`) and adds its own latency.

Without a helper that produces a deterministic completed-study + digest + proposal triple, the E2E suite skips the digest-panel surface entirely. Story 3.1 ships with 19 of 26 trigger assertions; the missing 7 + the AC-7 status-completed-body-content assertion are the gap.

## Proposed capability

Add a new E2E seed helper:

```typescript
export async function seedStudyCompletedWithDigest(args: {
  clusterId: string;
  querySetId: string;
  templateId: string;
  judgmentListId: string;
  withPendingProposal?: boolean;  // default: true (for AC-1 enabled-button trigger)
}): Promise<{
  studyId: string;
  digestId: string;
  proposalId: string | null;
}>;
```

Implementation options (pick one in the spec):

1. **API-direct insertion path.** Add a backend test-only endpoint (`POST /api/v1/_test/studies/seed-completed`) that creates the study + 2 trials + digest + proposal records via the repo layer in one request, bypassing the orchestrator. Guarded by an `ENVIRONMENT=development` check.
2. **Orchestrator drive-to-completion with timeout.** Call the existing `seedStudy` with `maxTrials=1`, then `await pollUntilCompleted(studyId, { timeoutMs: 30_000 })`. Slower (~15-30s per test) but exercises the real worker path.
3. **Database fixture loader.** Ship a SQL fixture under `backend/tests/fixtures/completed_study.sql` and a helper to `psql` it into the test database. Fastest, most brittle (schema-version sensitive).

Recommended: **option 1**. Test-only endpoint is fast (~50ms), deterministic, and surfaces in the OpenAPI schema (developers can find it). The `ENVIRONMENT` guard prevents accidental production exposure.

## Scope signals

- **Backend:** ~50 LOC. Add `/api/v1/_test/studies/seed-completed` router endpoint guarded by `Settings.environment != "production"`. Service-layer helper that inserts study + trials + digest + proposal in one transaction. Contract test that asserts the endpoint returns 404 in production mode.
- **Frontend:** ~30 LOC. Add `seedStudyCompletedWithDigest` to `ui/tests/e2e/helpers/seed.ts`. Update `ui/tests/e2e/studies.spec.ts` to add the 7 digest-panel triggers + AC-7 body-content assertion using this helper.
- **Migration:** none.
- **Config:** none (the `ENVIRONMENT` env var already exists).
- **Audit events:** N/A — test-only path. Optional: emit an `INTERNAL_TEST_SEED` audit event so the seeded records are flagged as test data even in dev.
- **CLAUDE.md absolute-rules walked:** no engine adapter use, no LLM call, no production state mutation (gated by environment check), no `<select>` enum drift.

## Why deferred

- Phase 1 of `feat_contextual_help` is unblocked without it — 19 of 26 triggers are covered by E2E and the remaining 7 are covered by vitest component tests at the appropriate isolation level.
- The helper is genuinely cross-cutting (any future E2E needing a completed study benefits), so designing it during the Phase 1 implementation would be scope creep.
- Test-only endpoints need a separate spec review (the `ENVIRONMENT` guard pattern is the cleanest approach but warrants explicit decision).

## Relationship to other work

- [`feat_contextual_help` Phase 1](../feat_contextual_help/feature_spec.md) — the immediate consumer. Story 3.1's E2E suite has a "NOTE: digest-panel triggers covered by vitest" comment that this idea retires when implemented.
- [`feat_studies_ui` (PR #50)](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/) and [`feat_digest_proposal` (PR #41)](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/) — the underlying data flow this helper reproduces deterministically.
- Future MVP2 chat / proposals E2E coverage will benefit from this helper too.
