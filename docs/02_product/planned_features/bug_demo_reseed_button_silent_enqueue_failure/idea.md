# Idea — Home reseed button's Arq job fails silently (JobExecutionFailed without a log line)

**Date:** 2026-05-27
**Status:** Idea — bug captured during PR #286 first-run testing
**Type:** `bug_`
**Priority:** P1 (the home-button reseed is broken end-to-end even though `make seed-demo` works)

## Origin

Surfaced during PR #286 (`bug_demo_reseed_fake_metric_regression`) verification. The operator clicked "Reset to demo state" on `/`; the dialog showed "Scenario 0 of 5 (0%)" but never advanced. Status stayed `"running"` with `current_step="enqueued — waiting for worker"` indefinitely until manually cleared from Redis.

Diagnostics:
- `docker exec relyloop-worker-1 docker logs --tail 30` showed the worker registered `run_demo_reseed` at startup ("Starting worker for 12 functions: ..., run_demo_reseed, ...").
- Worker had no other in-flight job — was idle when the POST landed.
- The Arq queue ZSET (`arq:queue`) was empty at observation time.
- `arq:result:demo_reseed:singleton` Redis key existed with pickled value `JobExecutionFailed("max 1 retries exceeded")`.
- **The worker process log shows ZERO lines** between the dashboard's POST timestamp and the moment the job result appeared. No `demo_reseed_worker_started`, no exception traceback, nothing.

Net: the worker picked up the job, hit some error before the first `logger.info` could fire, and Arq immediately marked it failed (`max_tries=1` per WorkerSettings registration). The Redis status stays stuck at the POST-handler's initial `"running"` payload because the worker's exception handler — which writes `status="failed"` — never executed.

## Problem

There is at least one untrapped exception path in `backend/workers/demo_reseed.py:run_demo_reseed`'s pre-main-body initialization that:

1. Crashes the function before `logger.info("demo_reseed_worker_started")` runs.
2. Bypasses the inner `try/except` that flips Redis status to `failed`.
3. Leaves the operator with a status indicator that says "running" forever, blocking the next 409-gated POST.

## Candidate root causes

Things to investigate, ordered by likelihood:

1. **`get_settings()` or `get_session_factory()` raises at module-init.** The worker's `on_startup` already constructs Optuna's RDBStorage + an Arq pool — those imports succeed (the function-list registration log proves it). But the *invocation* of `get_settings()` inside `run_demo_reseed` may trip on a missing env var that only matters under that specific code path. Worth catching with a top-level try/except that writes a fail-status to Redis.

2. **`get_engine()` raises on first call inside the worker container.** The worker's `on_startup` doesn't call `get_engine()` — it constructs Optuna storage from `Settings.database_url` directly. So `get_engine()` inside the job may be a cold-path call that hits a misconfig. Same fix.

3. **`engine.connect()` immediately fails because the worker's DB pool is exhausted or in a bad state from a prior crash.** Less likely — other in-process workers are using the same engine successfully.

4. **PostToolUse-hook-style silent stdout swallowing.** Some Arq configuration or `ctx`-level wrapping intercepts stderr/stdout before `logger.info` can emit. Lower likelihood but worth ruling out by adding a `print()` at the very top of `run_demo_reseed` and verifying it appears in `docker logs`.

## Why deferred

PR #286 ships the bug fix at the data layer — the CLI path (`make seed-demo`) works end-to-end. The home-button path's silent failure is a UX-only regression: the operator can fall back to the CLI.

Investigating further requires either:
- Adding a top-level `try/except BaseException` around the entire worker function body that writes `status="failed"` with the exception class+message to Redis (defensive, ships independently).
- Or reproducing locally with extra `print()` debugging to find the exception origin.

Both are >30 min of focused work and were out of scope for the merge cycle the operator was driving.

## Proposed capabilities (when this is picked up)

1. **Top-level exception barrier** in `run_demo_reseed`:

   ```python
   async def run_demo_reseed(ctx: dict[str, Any]) -> None:
       redis = None
       try:
           redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
           # … existing body …
       except BaseException as exc:
           if redis is not None:
               try:
                   await status_set(redis, ReseedStatusResponse(
                       status="failed",
                       failed_reason=f"{type(exc).__name__}: {str(exc)[:200]}",
                       finished_at=_now_iso(),
                   ))
               except Exception:
                   pass
           raise
   ```

2. **Stale-status auto-recovery in POST handler.** If the GET status is `running` but `started_at` is older than `DEMO_RESEED_JOB_TIMEOUT_S`, treat it as `failed` and let the new POST proceed. Prevents the "stuck forever" state from a silent worker crash.

3. **Add a `print("run_demo_reseed: entered")` at the top of the function.** If it appears in the worker logs but `logger.info` doesn't, we know structlog is the culprit. If neither appears, the failure is at the module-load level (import error) and Arq's job picker is crashing.

4. **Regression test:** spin up a real worker + real Redis + intentionally misconfigure something (e.g., bad `database_url`) and assert the GET status flips to `failed` with the exception class name within 30s of the POST.

## Scope signals

- Backend-only (worker + maybe POST handler).
- ~40 LOC for the exception barrier; ~30 LOC for the stale-status recovery; integration test is +50 LOC.

## Related ideas

- The parent fix [`bug_demo_reseed_fake_metric_regression`](../../00_overview/implemented_features/2026_05_27_bug_demo_reseed_fake_metric_regression/bug_fix.md) (PR #286) — closed at the data layer, this is the UX-layer follow-up.
- [[chore_demo_seeding_integration_tests_rewrite]] — the integration suite at `backend/tests/integration/test_demo_seeding.py` is currently skipped; rewriting it would have caught this regression in CI.
