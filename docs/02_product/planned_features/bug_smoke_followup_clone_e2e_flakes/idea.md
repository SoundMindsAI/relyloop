# Smoke-lane Playwright flakes: `followup_run.spec.ts` + `study-clone.spec.ts`

**Date:** 2026-05-25
**Status:** Idea — surfaced during `infra_test_worktree_missing_integration_envs` PR #257 CI watch (and confirmed pre-existing by checking main run `9928d763`).
**Priority:** P2 — every PR's smoke job is currently red on these; degrades the signal of CI and forces operators to mentally subtract these from every red-job verdict before merge.
**Depends on:** none — self-contained Playwright test triage. May overlap with [`bug_dashboard_banner_dismiss_persistence_flake/`](../bug_dashboard_banner_dismiss_persistence_flake/idea.md) and [`bug_smoke_dashboard_demo_state_locator_missing/`](../bug_smoke_dashboard_demo_state_locator_missing/idea.md) — those cover the dashboard subset of smoke failures.

## Origin

During CI for [PR #257](https://github.com/SoundMindsAI/relyloop/pull/257) (`infra_test_worktree_missing_integration_envs`), the `smoke (operator-path tutorial flow)` job reported 6 Playwright failures. Cross-checked against `main` commit `9928d763`'s run (`gh run view 26424739002`) — same `smoke` job conclusion=`failure`, same set of failures. So the failures are not a regression introduced by PR #257.

Two of the failing tests are already captured as Idea-stage bugs:

- `dashboard.spec.ts:47` + `dashboard.spec.ts:63` — covered by [`bug_dashboard_banner_dismiss_persistence_flake/`](../bug_dashboard_banner_dismiss_persistence_flake/idea.md).
- `dashboard-reseed.spec.ts:77` — covered by [`bug_smoke_dashboard_demo_state_locator_missing/`](../bug_smoke_dashboard_demo_state_locator_missing/idea.md).

The remaining three failures don't appear in the existing planned-features backlog and this idea captures them so the next infra-sweep agent has a tracked target:

1. `ui/tests/e2e/followup_run.spec.ts:28` — `Run this followup → modal opens prefilled → submit creates lineage-linked study`. Failure: `Error: locator.click: Test timeout of 30000ms exceeded.`
2. `ui/tests/e2e/followup_run.spec.ts:111` — `swap_template followup → Run → modal opens with swap-target template + creates study with template_id=B (AC-12)`. Failure: `Error: expect(received).toBe(expected)` (assertion mismatch — likely related to the swap-template payload shape).
3. `ui/tests/e2e/study-clone.spec.ts:24` — `Clone study from study-detail → banner + parent_study_id round-trip`. (Failure cause not parsed from log — needs Playwright report download.)

## Problem

Every PR's `smoke` job is currently red on these tests. Operators (and PR reviewers) have to:

1. See the red ✗ on the smoke job in the PR's checks panel.
2. Manually open the job log.
3. Recognize the failure set as the known pre-existing flakes (or be unsure and waste time investigating).
4. Mentally subtract the flakes from the verdict and only THEN decide whether the PR's actual contribution to CI is green.

This degrades the value of the smoke job as a merge gate: a contributor who hasn't been told about the flakes will either (a) panic and try to fix tests that aren't theirs to fix, or (b) merge anyway and risk introducing a real regression that's invisible inside the noise.

## Why deferred (and why this is a separate idea from the dashboard flakes)

The dashboard subset has its own idea files and may have its own root cause (dashboard demo-banner localStorage/seed-state interaction). The `followup_run` and `study-clone` failures are about different UI surfaces and likely different root causes:

- `followup_run.spec.ts:28` timing out on a `locator.click` suggests a seed-data setup race (the "Run followup" affordance is not yet rendered when the click fires).
- `followup_run.spec.ts:111` failing an equality assertion on the created study's `template_id` suggests a payload-shape regression (the swap_template followup may be serializing the template_id differently than the test expects).
- `study-clone.spec.ts:24` — needs deeper investigation; likely banner-render timing.

Mixing all six failures into one bug-fix PR would conflate distinct root causes and slow down each fix. Better to have separate ideas so the next infra-sweep agent can pick a single failing test, trace its root cause, and ship a focused fix.

## Proposed capabilities

1. **Triage each failing test individually** — download the Playwright report artifact from a CI run (`gh run download <run_id> --name playwright-report`), open `playwright-report/index.html`, inspect the trace + screenshot for each failure.
2. **Identify the root cause per test:**
   - For `followup_run.spec.ts:28` — does the "Run followup" button render before the test clicks it? Add an explicit `expect(button).toBeVisible()` before the click, OR add a seed-state wait. (Pattern: `signup_flow.spec.ts` for canonical seed → assert → interact.)
   - For `followup_run.spec.ts:111` — what is the actual `template_id` returned vs. what the test expects? May be a payload-shape regression in the `swap_template` followup serialization that needs a fix in `backend/app/services/digest_followup.py` or wherever the followup → study conversion lives.
   - For `study-clone.spec.ts:24` — what's the actual rendered DOM after the clone? Banner may not be rendering, or its locator is stale.
3. **Fix the smallest reproducible problem per test** — at most one bug fix per failing test (or merge fixes into one PR only if they share the same root cause).
4. **Verify locally** before push: `cd ui && npx playwright test tests/e2e/followup_run.spec.ts tests/e2e/study-clone.spec.ts --reporter=line --workers=1` against a live `make up` stack.

## Scope signals

- **Backend:** possibly, if `followup_run.spec.ts:111` is a payload-shape regression in the followup → study conversion (digest_followup service).
- **Frontend:** likely, if `followup_run.spec.ts:28` is a seed-state timing issue in the modal-open path; likely also for `study-clone.spec.ts:24` if the banner-render path has a regression.
- **Infra:** none directly. The smoke job's docker-compose stack composition is fine.
- **Migration:** none.

## Coordinates with

- **[`bug_dashboard_banner_dismiss_persistence_flake/`](../bug_dashboard_banner_dismiss_persistence_flake/idea.md)** — same smoke job, different test files, possibly different root causes.
- **[`bug_smoke_dashboard_demo_state_locator_missing/`](../bug_smoke_dashboard_demo_state_locator_missing/idea.md)** — same smoke job, possibly the same `demo-data-banner` testID resolution issue affecting `dashboard-reseed.spec.ts:77`.
- **[`feat_auto_followup_studies`](../../00_overview/implemented_features/2026_05_24_feat_auto_followup_studies/)** — the feature whose followup-related E2E coverage `followup_run.spec.ts` exercises.
- **[`feat_study_clone_from_previous`](../../00_overview/implemented_features/2026_05_25_feat_study_clone_from_previous/)** — the feature whose `study-clone.spec.ts` exercises; recent merge that may have introduced the regression.
