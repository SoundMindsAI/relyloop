# Bug fix — bug_demo_reseed_button_silent_enqueue_failure

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/demo-reseed-button-silent-enqueue-failure`
**Type:** bug fix — medium
**Date:** 2026-05-28

## Problem

The home page's "Reset to demo state" button enqueues the `run_demo_reseed` Arq job, but if the worker function raises during pre-main-body initialization (settings load, session-factory init, `get_engine()`, `engine.connect()`), the exception propagates straight to Arq without writing a `failed` status to Redis. The polling endpoint stays stuck at `running` indefinitely (the POST handler's initial payload), blocking the next 409-gated POST. The operator sees "Scenario 0 of 5 (0%)" forever and must manually clear `arq:result:demo_reseed:singleton` from Redis to recover.

## Reproduction

```bash
# Unit-level reproducer (the regression test ships in this PR):
pytest backend/tests/unit/workers/test_demo_reseed_exception_barrier.py -v
```

The test monkeypatches `get_settings` to raise `RuntimeError("boom")`, invokes `run_demo_reseed({"redis": fake_redis})` directly, asserts the exception re-raises, AND asserts the fake Redis received a `status_set` write with `status="failed"` and `failed_reason` containing `"RuntimeError"`. On `main` the test fails because no `failed` status is written; on this branch it passes.

## Root cause

Two distinct gap regions in [backend/workers/demo_reseed.py:76-133](../../../../backend/workers/demo_reseed.py#L76-L133) where an exception escapes Redis-status writing:

- **Lines 76-88** (settings load, session-factory init, Redis acquisition) — sits **outside** the outer `try` at line 90.
- **Lines 91-133** (`get_engine()`, `engine.connect()`, advisory-lock query, `factory()` session, `httpx.AsyncClient(...)` constructors) — inside the outer `try` but the block has no `except`, only a `finally` to close Redis (line 181).

The inner `except (DemoSeedingError, httpx.HTTPError, Exception)` at line 150 only catches errors raised inside the `reseed_demo_state` call (line 140), so it doesn't cover either gap region.

- Owning layer: worker (`backend/workers/demo_reseed.py`) — primary fix. Defense-in-depth at API layer (`backend/app/api/v1/_test.py`) for the worker-crash case.
- Origin: [backend/workers/demo_reseed.py:76-133](../../../../backend/workers/demo_reseed.py#L76-L133)
- Propagation: status stays "running" → polling endpoint never flips → POST gate at [backend/app/api/v1/_test.py:633-642](../../../../backend/app/api/v1/_test.py#L633-L642) blocks 409 forever

## Fix design (locked decisions)

1. **Top-level `try/except Exception` barrier** wraps the entire `run_demo_reseed` body. On exception, writes `status="failed"` with `started_at` + `finished_at` + `failed_reason=f"{type(exc).__name__}: {str(exc)[:200]}"` to Redis, then **re-raises**. Cites: idea.md §"Proposed capabilities" #1 (locks re-raise-after-status-write — preserves Arq's `JobExecutionFailed` ops record AND worker-log traceback). **`Exception`, not `BaseException`** (per Gemini PR #299 review): Arq uses `asyncio.CancelledError` (a `BaseException` subclass) for job-timeout cancellation, and `SystemExit`/`KeyboardInterrupt` signal worker shutdown — awaiting `status_set` from a handler that caught one of those would re-raise `CancelledError` (masking the original) or hang shutdown with network I/O. The documented bug (init-region exceptions: settings/factory/engine/httpx) is fully covered by `Exception`. The existing inner handler at lines 150-173 keeps its `return` (no re-raise) because retrying the destructive wipe is the wrong behavior for `reseed_demo_state` failures.

2. **Redis acquisition stays first** (current lines 82-88) so the barrier can write status even when settings/factory/engine init explodes. Preserves Gemini PR #286 finding #7 (reuse Arq's managed pool when `ctx["redis"]` is present, fall back to fresh `Redis.from_url` otherwise) and finding #8 (only close the Redis client when we created it). Cites: idea.md §"Proposed capabilities" #1 inline comment.

3. **`get_settings()` failure remains uncovered** — if the very first call raises, we drop into the barrier without a Redis handle, and the operator still has to read worker logs. This is acceptable because `get_settings()` failure means the worker can't start ANY job, which is loud at a different layer. Cites: idea.md §"Proposed capabilities" #1 inline rationale.

4. **Stale-status auto-recovery in POST handler** — if the GET status is `running` AND `started_at` is older than `DEMO_RESEED_JOB_TIMEOUT_S` (1200s = 20min), the POST treats it as `failed` and proceeds with a new enqueue instead of 409'ing. Independent of #1 — defense-in-depth for cases where the worker process itself dies (OOM, container restart) before any exception handler runs. Cites: idea.md §"Proposed capabilities" #2.

5. **No diagnostic `print()` ships in steady state.** Capability #3 in the idea was an investigation-only probe; the exception barrier in #1 makes it unnecessary. Cites: idea.md §"Proposed capabilities" #3.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/workers/test_demo_reseed_exception_barrier.py` | `get_settings`/`get_engine`/`get_session_factory` raising → barrier writes `failed` status to Redis AND re-raises |
| unit | `backend/tests/unit/api/test_demo_reseed_stale_status_recovery.py` | POST with stale `running` status (started_at > `DEMO_RESEED_JOB_TIMEOUT_S` ago) proceeds instead of 409'ing |

Coverage check: `pytest --cov=backend.workers.demo_reseed --cov=backend.app.api.v1._test --cov-report=term-missing` should show the new tests hitting the exception-barrier branch and the stale-status branch.

## Rollout

None — code-only change. The exception barrier is purely additive (existing happy path unchanged); the stale-status check is additive in the POST handler (only fires when `current.status == "running"` AND `started_at` parseable AND > 1200s ago). No DB migration, no env var, no operator action.

## Tangential observations

None — the trace was tight to the worker init region.
