# Arq enqueue/no-enqueue spy fixture for POST /api/v1/studies tests

**Date:** 2026-05-22
**Status:** Idea — surfaced during `feat_study_preflight_overlap_probe` (PR ___) phase-gate review
**Priority:** P2 — useful infra for tightening "no side effect on rejection" assertions across the studies POST surface; not blocking any single feature.

**Origin:** GPT-5.5 phase-gate code review on `feat_study_preflight_overlap_probe` flagged that the new integration tests assert `SELECT COUNT(*) FROM studies` before/after on rejection paths (proves no DB write) but do NOT assert "no Arq job enqueued." This same gap exists in the pre-existing Tier 1 tests (`test_post_study_rejects_target_mismatch`, etc. at [`backend/tests/integration/test_studies_api.py:207-430`](../../../../backend/tests/integration/test_studies_api.py#L207-L430)) and in every other rejection-path test on the studies POST.

## Problem

The studies POST handler at [`backend/app/api/v1/studies.py:307`](../../../../backend/app/api/v1/studies.py#L307) calls `await _enqueue_start_study(request, study_id)` after a successful create. The helper at `studies.py:166-179` reads `request.app.state.arq_pool` — if the pool is `None` (the test-boot path that skips lifespan), the enqueue is a silent no-op.

This means every studies-POST integration test today runs without a real Arq pool, and the rejection-path tests cannot positively assert "no enqueue happened" because there's nothing to spy on. A regression where the handler's rejection path accidentally enqueued a job before raising would not be caught by integration tests.

## Proposed capabilities

1. Add an `arq_pool_spy` fixture in [`backend/tests/integration/conftest.py`](../../../../backend/tests/integration/conftest.py) (or a sibling helper module) that:
   - Installs a `SpyArqPool` class with an async `enqueue_job(name, *args)` method into `app.state.arq_pool` before each test
   - Records every `enqueue_job` call as a list of `(name, args)` tuples
   - Cleans up after the test
2. Update the studies-POST integration tests (existing Tier 1 + new Tier 2 `INSUFFICIENT_JUDGMENT_OVERLAP` cases + happy path) to:
   - Assert `spy.calls == []` on rejection paths (no enqueue)
   - Assert `spy.calls == [("start_study", study_id)]` on success paths
3. Apply the same pattern to other POST endpoints that enqueue Arq jobs (`/api/v1/judgments/generate`, `/api/v1/proposals/{id}/open_pr`, etc.) — out of scope for the initial idea but a natural extension.

## Why deferred

- The pre-existing Tier 1 tests work today without this assertion; the missing assertion is symmetric across all rejection paths, not specific to the new probe.
- Adding the fixture is independent infra work and pre-dates the probe feature.

## Coordinates with

- [`infra_study_preflight_real_engine_integration`](../infra_study_preflight_real_engine_integration/idea.md) — also deferred from the same phase-gate review; both could be picked up together in an infra-sweep PR.
