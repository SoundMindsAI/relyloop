# Arq enqueue/no-enqueue spy fixture for POST /api/v1/studies tests

**Date:** 2026-05-22
**Status:** Idea (preflighted 2026-06-02) — surfaced during `feat_study_preflight_overlap_probe` phase-gate review (now shipped)
**Priority:** P2 — useful infra for tightening "no side effect on rejection" assertions across the studies POST surface; not blocking any single feature.

**Origin:** GPT-5.5 phase-gate code review on `feat_study_preflight_overlap_probe` flagged that the new integration tests assert the `studies` row count (via `_count_studies()`) before/after on rejection paths (proves no DB write) but do NOT assert "no Arq job enqueued." This same gap exists in the pre-existing Tier 1 tests (`test_post_study_rejects_target_mismatch` at [`backend/tests/integration/test_studies_api.py:246-273`](../../../../../backend/tests/integration/test_studies_api.py#L246-L273), `test_post_study_rejects_cluster_mismatch` at [`:276-341`](../../../../../backend/tests/integration/test_studies_api.py#L276-L341), etc.) and in every other rejection-path test on the studies POST. The Tier-1 docstrings already _claim_ "no Arq job enqueued" (e.g. `test_studies_api.py:248`) but no assertion backs the claim.

## Problem

The studies POST handler enqueues `start_study` after a successful create — `await _enqueue_start_study(request, study_id)` at [`backend/app/api/v1/studies.py:456`](../../../../../backend/app/api/v1/studies.py#L456). The helper `_enqueue_start_study` at [`studies.py:189-202`](../../../../../backend/app/api/v1/studies.py#L189-L202) reads `getattr(request.app.state, "arq_pool", None)` — if the pool is `None`, the enqueue is a silent no-op; otherwise it calls `await arq_pool.enqueue_job("start_study", study_id)` (studies.py:202).

The rejection-path tests cannot positively assert "no enqueue happened" because there is nothing to spy on. A regression where the handler's rejection path accidentally enqueued a job before raising would not be caught by integration tests.

**Stale-claim correction (verified 2026-06-02):** The `async_client` integration fixture at [`backend/tests/integration/conftest.py:138-160`](../../../../../backend/tests/integration/conftest.py#L138-L160) mounts the app via `LifespanManager`, which **does build a real Arq pool** against the CI Redis service container — the original idea's "every studies-POST integration test today runs without a real Arq pool" was inaccurate. The pool is live; the enqueued jobs simply sit in the queue with no worker to pick them up (conftest docstring lines 142-148). So the spy fixture's job is **not** to supply a missing pool — it is to **replace** `app.state.arq_pool` with a recording double **after** the lifespan has built the real one, so `enqueue_job` calls are captured instead of dispatched to Redis. This ordering constraint (override after lifespan) is the central design point and must be carried into the spec.

## Proposed capabilities

1. Add an `arq_pool_spy` fixture in [`backend/tests/integration/conftest.py`](../../../../../backend/tests/integration/conftest.py) (or a sibling helper module) that:
   - Defines a `SpyArqPool` class with an async `enqueue_job(self, name, *args, **kwargs)` method that records every call as a `(name, args)` tuple (a `.calls` list) and returns a truthy sentinel (matching the real `ArqRedis.enqueue_job` return-a-Job contract so the handler's `await` resolves normally).
   - Depends on `async_client` so the override is installed **after** `LifespanManager` builds the real pool, then sets `app.state.arq_pool = SpyArqPool()` (capturing the prior value).
   - Restores the captured prior `app.state.arq_pool` value on teardown so the spy doesn't leak into other tests sharing the module-level `app` singleton.
2. Update the studies-POST integration tests (existing Tier 1 mismatch/FK rejections + Tier 2 `INSUFFICIENT_JUDGMENT_OVERLAP` cases + at least one happy path) to:
   - Assert `spy.calls == []` on rejection paths (no enqueue)
   - Assert `spy.calls == [("start_study", study_id)]` on the success path (job name + arg shape verified at studies.py:202)
3. Apply the same pattern to other POST endpoints that enqueue Arq jobs (`/api/v1/judgments/generate`, `/api/v1/proposals/{id}/open_pr`, etc. — confirmed live enqueue sites in `backend/app/api/v1/judgments.py` + `proposals.py`) — **out of scope for the initial idea** but a natural extension once the studies-POST pattern is proven.

## Why now (deferral rationale retired 2026-06-02)

The original "why deferred" was: (a) Tier-1 tests work without the assertion, and (b) the fixture is independent infra that pre-dates the probe. Both are still true, but **both features the deferral coordinated with have now shipped**:

- `feat_study_preflight_overlap_probe` shipped → [`docs/00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/`](../../../implemented_features/2026_05_22_feat_study_preflight_overlap_probe/), adding the Tier-2 `INSUFFICIENT_JUDGMENT_OVERLAP` rejection paths (`test_post_study_insufficient_overlap_returns_422` at `test_studies_api.py:817`, `test_post_study_overlap_one_below_threshold_returns_422` at `:936`) — more rejection paths now carry the unbacked "no enqueue" gap.
- `infra_study_preflight_real_engine_integration` shipped → [`docs/00_overview/implemented_features/2026_05_25_infra_study_preflight_real_engine_integration/`](../../../implemented_features/2026_05_25_infra_study_preflight_real_engine_integration/).

The infra-sweep moment the deferral was waiting on has arrived; this is the low-risk test-hardening follow-up that closes the gap across the now-larger rejection-path surface.

## Coordinates with

- [`infra_study_preflight_real_engine_integration`](../../../implemented_features/2026_05_25_infra_study_preflight_real_engine_integration/) — **shipped 2026-05-25**; the co-deferral that motivated an "infra-sweep PR" is no longer pending.

## Absolute-rules check (idea-preflight Step 7)

- **No migration** — test-infra only; no schema change, no Alembic revision.
- **No new endpoint / dropdown / enum** — no enumerated-value-contract surface; no API-conventions surface.
- **No LLM call** — N/A.
- **No secret** — N/A.
- **Audit-event emission** — N/A; this is test code, not a state-mutating endpoint/service.
- **Integration-test mocking policy (CLAUDE.md):** the spy replaces an _external_ side-effect sink (the Arq/Redis enqueue), not internal code — DB, repos, services, domain logic still run for real. Compliant.
