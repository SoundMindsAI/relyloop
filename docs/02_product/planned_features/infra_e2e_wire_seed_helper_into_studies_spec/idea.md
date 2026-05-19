# infra — wire `seedStudyCompletedWithDigest` into Playwright E2E

**Date:** 2026-05-17
**Status:** Idea — deferred from `infra_e2e_seed_completed_study` PR #130. The endpoint + helper landed cleanly; the 2 Playwright E2E tests that consume them caused the smoke CI lane to fail (root cause undiagnosed — agent environment had no access to GitHub Actions logs to debug the Playwright report).
**Origin:** PR #130 commit `2615aae` smoke-job failure. The 2 new E2E tests + the `seedStudyCompletedWithDigest` import were reverted on the PR branch in pre-squash commit `3203787` ("fix(e2e): drop 2 digest-panel tests that broke the smoke lane"); after merge, the revert is folded into PR #130's squash commit `13b3383`. The endpoint, service helper, contract tests, and integration smoke test all stayed.
**Depends on:** PR #130 merged.

## Problem

`infra_e2e_seed_completed_study` shipped `POST /api/v1/_test/studies/seed-completed` and the `seedStudyCompletedWithDigest` TypeScript helper. The two consuming E2E tests in `ui/tests/e2e/studies.spec.ts` —

1. `contextual help — digest-panel triggers + AC-7 body + AC-11 Open PR enabled`
2. `contextual help — Open PR aria-disabled branch surfaces tooltip (AC-11)`

— caused the smoke CI lane to fail when first pushed (PR #130 run `26000549177`). The backend lane (lint + typecheck + tests + coverage) was green; the failure was in the Playwright lane that runs against `make up`. Without log access (the agent execution environment is rate-limited on the public GitHub API and authenticated WebFetch is unavailable), the root cause could not be diagnosed live.

Both tests were removed from PR #130 to land a green pipeline. The infrastructure to add them back is fully in place:

- `seedStudyCompletedWithDigest` helper at [`ui/tests/e2e/helpers/seed.ts:345-368`](../../../../ui/tests/e2e/helpers/seed.ts)
- `POST /api/v1/_test/studies/seed-completed` endpoint at `backend/app/api/v1/_test.py`
- Backing service at `backend/app/services/test_seeding.py`
- Contract + integration coverage at `backend/tests/contract/test_test_endpoint_guard.py` + `backend/tests/integration/test_test_seeding.py`

## Hypothesized failure modes (in priority order)

1. **Page render timing.** The 10-second wait for `digest-narrative` may be insufficient when the smoke runner is under load; the digest panel renders only when `study.status === 'completed' && digestQ.data` resolves, and a slow TanStack Query refetch could push past the window.
2. **`narrative` markdown rendering.** The seeded narrative wraps `title.boost` in backticks. ReactMarkdown converts those to `<code>` elements. Playwright's `toContainText('title.boost')` should match, but if the markdown plugin produces unexpected character-class wrapping (e.g., `<code>title<wbr>.boost</code>`), the substring match fails.
3. **Container environment.** The smoke compose stack doesn't set `ENVIRONMENT` explicitly, so `Settings.environment` falls back to `"development"`. If the smoke job's seed step somehow normalizes that to a different value (it shouldn't — Pydantic-settings reads from env vars only), the endpoint returns 404 and the helper throws.
4. **Concurrent E2E tests.** Playwright runs single-worker per `playwright.config.ts`, so this is unlikely — but worth double-checking the test isolates from sibling tests that might wipe `studies` rows.

## Proposed work

When picked up:

1. Restore the 2 tests in `ui/tests/e2e/studies.spec.ts` and the `seedStudyCompletedWithDigest` import.
2. Run the smoke lane locally (`docker compose up -d && pnpm --dir ui test:e2e`) to reproduce the failure.
3. If the failure isn't reproducible, push the restored tests and rely on the smoke job's `playwright-report` artifact upload (already configured at [`.github/workflows/pr.yml:404-405`](../../../../.github/workflows/pr.yml)) to surface the failure trace.
4. Adjust timeouts, narrative content, or test isolation as needed.
5. Verify against both `withPendingProposal=true` (enabled Open PR branch) and `=false` (aria-disabled branch).

## Scope signals

- **Backend:** none — the endpoint + helper already ship.
- **Frontend:** ~60 LOC restoring the 2 test bodies + the import.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none.

## Why deferred

The endpoint's primary value (real-backend seeding for any future E2E coverage of completed studies) is fully delivered by PR #130. The 2 E2E tests were additive coverage that would have lifted digest-panel testing from vitest component layer (mocked completed-study data) to real-backend assertions. Without the ability to read the Playwright report from the failed smoke run, debugging the failure live would have required iterating on CI — a costly flight pattern given the issue is most likely a timing or rendering nit.

## Open questions for /spec-gen

- **Q1 — Per-test cleanup.** Should the restored tests delete the seeded study after they run, or rely on the existing pattern (no cleanup; `make reset` between full E2E runs)? Recommended default: **no per-test cleanup.** Matches every other seed-* helper in [`seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts) — none of them clean up. Adding cleanup just for this pair would introduce a precedent the codebase doesn't currently want.
- **Q2 — Spec scope: full /pipeline or /impl-execute ad-hoc?** This is ~60 LOC of E2E test code + possibly a small Playwright wait/selector adjustment. Recommended default: **/impl-execute ad-hoc**, not full /pipeline. Comparable in size to the chore_data_table_primitive_followups ship in PR #132 (which also went /impl-execute ad-hoc per state.md). Cuts the spec + plan stages that would otherwise pad a small E2E restore.

## Relationship to other work

- **Parent:** `infra_e2e_seed_completed_study` (PR #130).
- **Adjacent:** `feat_contextual_help` Phase 1 — the tooltips this E2E aims to cover already have vitest component coverage at [`ui/src/__tests__/components/common/info-tooltip.test.tsx`](../../../../ui/src/__tests__/components/common/info-tooltip.test.tsx) + the page-level integration test at [`ui/src/__tests__/app/studies/[id]/page.test.tsx`](../../../../ui/src/__tests__/app/studies/[id]/page.test.tsx). The real-backend E2E layer is the gap this idea closes.
- **Sibling check (clean):** no overlapping planned features. The 7 other items under `planned_features/` touch different surfaces (DataTable follow-ups, detail-page shell, test mocks, walkthrough screenshots, MVP2-deferred items).
