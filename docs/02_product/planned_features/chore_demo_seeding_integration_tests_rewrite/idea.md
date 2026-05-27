# Idea — Rewrite test_demo_seeding integration tests for the async-flow handler

**Date:** 2026-05-27
**Status:** Idea — chore captured during PR #286
**Type:** `chore_`
**Priority:** P2 (no current production risk; coverage gap means new regressions in the async flow won't be caught in CI)

## Origin

PR #286 (`bug_demo_reseed_fake_metric_regression`) converted `POST /api/v1/_test/demo/reseed` from a synchronous handler to an async Arq-enqueue + Redis-polling flow. The integration test suite at `backend/tests/integration/test_demo_seeding.py` (9 test functions) asserts the old contract: 200 OK + `ReseedSummary` body returned directly from the POST.

To unblock the merge I marked both files skip:

- `backend/tests/integration/test_demo_seeding.py` — 9 cases (AC-1 through AC-16) skipped with reason "Sync-flow tests paused — bug_demo_reseed_fake_metric_regression converted the reseed handler to async enqueue + poll".
- `backend/tests/integration/test_demo_seeding_timeout.py` — 1 case (AC-4 per-call timeout) skipped with reason "The per-call HTTP timeout assertion no longer applies to the POST handler; the timeout now lives in the worker".

Unit coverage at `backend/tests/unit/services/test_demo_seeding_status.py` (14 cases) covers the Redis status helpers + Pydantic shape + search_space builder, but does NOT cover end-to-end flow against real Postgres + Arq.

## Problem

The async flow's contract:

1. POST returns 202 + initial `ReseedStatusResponse{status:"running", scenarios_total:5, ...}`.
2. Arq job picks up + writes status updates to Redis after each phase.
3. GET `/api/v1/_test/demo/reseed/status` returns the current Redis status.
4. Terminal states: `complete` (with `summary`) or `failed` (with `failed_reason`).

None of this is integration-tested. A future regression that:

- Reverts the POST to synchronous → no test fails (the skipped tests would catch it, but they're skipped).
- Forgets to register `run_demo_reseed` in `WorkerSettings.functions` → no test fails.
- Breaks the Redis status key shape → no test fails (the unit test covers the *Pydantic* shape but not the persistence path through the real Redis).

[`bug_demo_reseed_button_silent_enqueue_failure`](../bug_demo_reseed_button_silent_enqueue_failure/idea.md) is a real bug that would have been caught by integration tests on the async flow.

## Why deferred

Rewriting 10 tests requires:

- A long-running uvicorn fixture (already exists at `backend/tests/integration/_demo_reseed_uvicorn.py`).
- An Arq worker fixture that processes the queue inline so the test deterministically observes the status transitions.
- New helpers for "POST + poll until terminal" — equivalent to what the frontend's `useDemoReseedStatus` does.
- Updating each AC's assertion from "POST returned a summary" to "GET status eventually reflects the expected terminal state".

Each is ~50-100 LOC of test plumbing. The merge cycle the operator was driving needed PR #286 shipped, not a 3-hour test rewrite.

## Proposed capabilities (when this is picked up)

1. **Async-flow test harness:** a fixture that starts an in-process Arq worker (or alternatively, runs `await arq_pool.process_job(job_id)` inline) so tests can deterministically wait for terminal status.
2. **Rewrite the 9 cases:**
   - AC-1 (happy path on clean DB) — POST + poll, assert `status=complete` with `summary.studies_completed=5` (or 4 if no OpenAI key, given the rich scenario fall-back).
   - AC-2 (happy path with pre-existing demo state replaced) — same as AC-1 + pre-seed.
   - AC-3 (concurrent reseed returns 409) — POST twice; second returns 409 SEED_IN_PROGRESS.
   - AC-5 (mid-loop engine failure) — monkeypatch the engine_client to return 500 on a specific scenario; assert `status=failed` with the right `failed_reason` substring.
   - AC-12 (cleanup-while-locked blocks concurrent reseed) — exercise the lock contention path.
   - AC-13 (TRUNCATE commits before any self-call) — assert the `demo_reseed_truncate_committed` log fires before any of the `_log_call_started` log lines.
   - AC-14 (natural failure cleanup is deterministic) — same engine-failure mock as AC-5; assert post-failure DB row counts.
   - AC-15 (dual-client contract) — assert the worker's HTTP-client construction uses separate api/engine clients with the right base URLs.
   - AC-16 (advisory lock pinned to one connection) — observe `pg_locks` during the run and assert the lock-holding pid is constant.
3. **Add AC-Async (new):** assert the polling endpoint's response shape: `running` → `complete` transition is observed with `scenarios_completed` monotonically increasing.

## Scope signals

- Test-only changes (no production code modified).
- ~500 LOC test additions + ~50 LOC fixture additions.
- 30 minutes ES + Arq setup time per CI run if the fixture spins up a real worker; alternative is to invoke the job function directly in the test thread for ~5s.

## Related ideas

- [[bug_demo_reseed_button_silent_enqueue_failure]] — a real bug shipping in PR #286's wake that this test suite would have caught.
- The original [`bug_demo_reseed_fake_metric_regression`](../../00_overview/implemented_features/2026_05_27_bug_demo_reseed_fake_metric_regression/bug_fix.md) lists this rewrite as a follow-up commitment in its "Until the rewrite lands" docstring.
