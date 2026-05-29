# Idea — Home reseed button's Arq job fails silently (JobExecutionFailed without a log line)

**Date:** 2026-05-27
**Status:** Idea — bug captured during PR #286 first-run testing
**Type:** `bug_`
**Priority:** P1 (the home-button reseed is broken end-to-end even though `make seed-demo` works)
**Depends on:** — (no blocking deps)
**Coordinate with:** [[chore_demo_seeding_integration_tests_rewrite]] — the async-flow integration harness this chore ships would catch the regression in CI, but the bug fix can land first with a unit-level regression test (see "Proposed capabilities" §4).

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

There is at least one untrapped exception path in `backend/workers/demo_reseed.py:run_demo_reseed` that:

1. Crashes the function before `logger.info("demo_reseed_worker_started")` (currently at [`demo_reseed.py:134`](../../../../backend/workers/demo_reseed.py#L134)) runs.
2. Bypasses both existing exception handlers (the lock-contention path at lines 102-116 and the `reseed_demo_state` exception handler at lines 150-173), neither of which catches errors in the regions below.
3. Leaves the operator with a status indicator that says "running" forever, blocking the next 409-gated POST.

**Two distinct gap regions** where an exception escapes Redis-status writing:

- **Lines 76-88** (settings load, session-factory init, Redis acquisition) — sits **outside the outer `try`** at line 90. Any exception here propagates straight to Arq's machinery without writing a `failed` payload.
- **Lines 91-133** (`get_engine()`, `engine.connect()`, advisory-lock query, `factory()` session, `httpx.AsyncClient(...)` constructors) — inside the outer `try` at line 90, but that block has no `except`, only a `finally` to close Redis (line 181). Exceptions in this region unwind through both `finally` blocks and escape to Arq.

The inner `except (DemoSeedingError, httpx.HTTPError, Exception)` at line 150 only catches errors raised inside the `reseed_demo_state` call (line 140), so it doesn't cover either gap region.

## Candidate root causes

Things to investigate, ordered by likelihood:

1. **`get_settings()` or `get_session_factory()` raises at module-init.** The worker's `on_startup` already constructs Optuna's RDBStorage + an Arq pool — those imports succeed (the function-list registration log proves it). But the *invocation* of `get_settings()` inside `run_demo_reseed` may trip on a missing env var that only matters under that specific code path. Worth catching with a top-level try/except that writes a fail-status to Redis.

2. **`get_engine()` raises on first call inside the worker container.** The worker's `on_startup` doesn't call `get_engine()` — it constructs Optuna storage from `Settings.database_url` directly. So `get_engine()` inside the job may be a cold-path call that hits a misconfig. Same fix.

3. **`engine.connect()` immediately fails because the worker's DB pool is exhausted or in a bad state from a prior crash.** Less likely — other in-process workers are using the same engine successfully.

4. **Structlog buffering / processor-chain swallowing.** Lower likelihood given other workers log fine through the same chain, but worth ruling out by adding a top-level `print("run_demo_reseed: entered", flush=True)` at the very first line of the function and verifying it appears in `docker logs relyloop-worker-1`. If `print` appears but `logger.info` doesn't, structlog config is the culprit; if neither appears, the failure is at the module-load level (import error) and Arq's job picker is crashing before it ever invokes the function body.

## Why deferred

PR #286 ships the bug fix at the data layer — the CLI path (`make seed-demo`) works end-to-end. The home-button path's silent failure is a UX-only regression: the operator can fall back to the CLI.

Investigating further requires either:
- Adding a top-level `try/except BaseException` around the entire worker function body that writes `status="failed"` with the exception class+message to Redis (defensive, ships independently).
- Or reproducing locally with extra `print()` debugging to find the exception origin.

Both are >30 min of focused work and were out of scope for the merge cycle the operator was driving.

## Proposed capabilities (when this is picked up)

1. **Top-level exception barrier** in `run_demo_reseed` — wraps the entire function body, including the Redis acquisition itself, while preserving the **Gemini PR #286 finding #7** pool-reuse pattern at the current `demo_reseed.py:82-88`:

   ```python
   async def run_demo_reseed(ctx: dict[str, Any]) -> None:
       # Acquire Redis FIRST so the exception barrier can write status even
       # when settings/factory/engine init explodes. Preserves Gemini #7:
       # reuse the Arq-managed pool when available, fall back otherwise.
       arq_redis = ctx.get("redis") if isinstance(ctx, dict) else None
       created_redis = arq_redis is None
       redis: Redis | None = None
       try:
           if arq_redis is not None:
               redis = arq_redis
           else:
               # If get_settings() itself raises, we drop into the outer
               # except without a Redis handle — that's the one case the
               # operator still has to read worker logs for. Acceptable
               # because get_settings() failure means the worker can't
               # start ANY job, which is loud at a different layer.
               redis = Redis.from_url(get_settings().redis_url, decode_responses=False)

           # ... existing body (settings, factory, engine, lock, httpx
           # clients, reseed_demo_state) lives here ...

       except BaseException as exc:
           if redis is not None:
               try:
                   await status_set(redis, ReseedStatusResponse(
                       status="failed",
                       started_at=_now_iso(),
                       finished_at=_now_iso(),
                       failed_reason=f"{type(exc).__name__}: {str(exc)[:200]}",
                   ))
               except Exception:
                   pass  # best-effort — never mask the original exc
           raise  # let Arq still record JobExecutionFailed for ops visibility
       finally:
           if created_redis and redis is not None:
               await redis.aclose()
   ```

   Spec-gen should lock the **re-raise after status-write** choice — re-raising preserves Arq's `JobExecutionFailed` record AND emits a worker-log traceback the operator can read, while still ensuring Redis flips to `failed` for the polling endpoint. The inner exception handler at lines 150-173 keeps its `return` (no re-raise) because it specifically does NOT want Arq retries for `reseed_demo_state` failures (the destructive wipe shouldn't replay).

2. **Stale-status auto-recovery in POST handler.** If the GET status is `running` but `started_at` is older than `DEMO_RESEED_JOB_TIMEOUT_S` (currently 1200s = 20min), treat it as `failed` and let the new POST proceed. Prevents the "stuck forever" state from a silent worker crash. This is independent of capability #1 — a defense-in-depth layer for cases where the worker process itself dies (OOM, container restart) before any exception handler runs.

3. **Diagnostic `print()` (temporary, behind the fix).** Add `print("run_demo_reseed: entered", flush=True)` at the very first line of the function as part of the investigation step. Remove once the root cause is identified — the top-level exception barrier in capability #1 makes the diagnostic unnecessary in steady state.

4. **Regression test (preferred — unit, no chore dependency):** in `backend/tests/unit/workers/test_demo_reseed.py` (new file), monkeypatch `backend.app.core.settings.get_settings` (or `get_session_factory`, or `get_engine`) to raise `RuntimeError("boom")`, invoke `run_demo_reseed({"redis": <fake_redis>})` directly, and assert:
   - The exception re-raises (caller-visible).
   - The fake Redis received a `status_set` call with `status="failed"` and `failed_reason` containing `"RuntimeError"`.

   This path does NOT depend on `chore_demo_seeding_integration_tests_rewrite` shipping the real-worker harness — the ctx pool fallback at `demo_reseed.py:82-88` already supports passing a synthetic `redis` in `ctx`. The chore's integration test, when it lands, would supplement this with a real-Postgres-misconfig variant.

## Scope signals

- Backend-only (worker + maybe POST handler).
- ~40 LOC for the exception barrier; ~30 LOC for the stale-status recovery; integration test is +50 LOC.

## Related ideas

- The parent fix [`bug_demo_reseed_fake_metric_regression`](../../../implemented_features/2026_05_27_bug_demo_reseed_fake_metric_regression/bug_fix.md) (PR #286) — closed at the data layer, this is the UX-layer follow-up.
- [[chore_demo_seeding_integration_tests_rewrite]] — the integration suite at `backend/tests/integration/test_demo_seeding.py` is currently skipped; rewriting it would have caught this regression in CI.
