# Webhook concurrent-merge row-lock race is timing-sensitive (test_ac7 deterministically fails under lifespan-spawned background tasks)

**Date:** 2026-05-24
**Status:** Idea — surfaced during `bug_demo_clusters_unreachable_in_healthz` PR #236 CI.
**Priority:** P2 — currently undetectable on `main` because no other lifespan-spawned background task exists yet at the timing that triggers the race; deterministically reproducible the moment a second startup task is added.
**Origin:** Surfaced during PR #236 (`bug_demo_clusters_unreachable_in_healthz`) round-1 + round-2 CI. The new `run_cluster_health_warmup_background` task added to the FastAPI lifespan hook deterministically causes `backend/tests/integration/test_webhook_config_repo_pointer.py::test_ac7_concurrent_merges_serialize_via_row_lock` to fail with the older proposal winning the row-lock when the newer-timestamp proposal should win.

## Reproducing

1. Check out `bug/demo-clusters-unreachable-in-healthz` at commit `a04b5d3a` (post-final-review per-page refactor).
2. Run `make test-integration` against a real Postgres + Redis service container.
3. `test_ac7_concurrent_merges_serialize_via_row_lock` fails 100% with `AssertionError: assert '<pid_a>' == '<pid_b>'` (older PID won the row-lock).

The test passes 100% on `main` (verified — backend job is green on the last 4 `main` runs). Adding ANY second `asyncio.create_task` to the lifespan hook reproduces this failure.

## Hypothesis (root cause)

The webhook merge handler's row-lock logic at `backend/app/api/webhooks/github.py` (and the underlying service that updates `config_repos.last_merged_proposal_id`) has a timing-sensitive race in the timestamp-comparison step. The intended behavior:

1. Webhook A (older timestamp) arrives.
2. Webhook B (newer timestamp) arrives.
3. Whichever acquires the row lock first does its `UPDATE config_repos SET last_merged_proposal_id = ...`.
4. The other waits on the lock, then re-reads the timestamp, compares, and either updates or skips.

The observed bug suggests step 4's compare-and-skip is racing with step 3 in a way that allows the older webhook to win when it's the SECOND to acquire the lock — i.e., the lock-holder isn't reading the freshest state OR the timestamp comparison isn't using the row's currently-stored last-update timestamp.

When tested in isolation (no concurrent lifespan tasks), the race window is small enough that pytest's asyncio scheduling happens to favor the correct winner. When another background task (my warmup) is interleaving on the same event loop, the race window opens up.

## Why this matters

This is a real data-correctness bug in the production webhook merge handler — the row-lock claims to serialize concurrent merges but doesn't actually guarantee the newer-timestamp winner. It just happens to test green in the current CI environment because of how the asyncio scheduler ranks the bare ASGI test client's coroutines.

The moment ANY second startup task lands (the cluster health warmup, a future Prometheus exporter, a future cron scheduler, etc.), this bug will trip.

## Suggested fix path

1. **Reproduce locally** by adding any `asyncio.create_task(asyncio.sleep(0.001))` to `main.py:lifespan` after `cap_task` — observe `test_ac7` fail.
2. **Read the merge handler at `backend/app/api/webhooks/github.py`** (and the underlying service in `backend/app/services/pr_reconciler.py` or similar) to find the row-lock + timestamp-compare logic.
3. **Audit the SQL:** is the lock acquired with `SELECT ... FOR UPDATE`? Does the compare-and-update use `WHERE last_updated_at < :new_timestamp` to be race-free? Or is the comparison Python-side (read row → compare in Python → UPDATE) which is broken under concurrency?
4. **Add a regression test** that asserts row-lock serialization with the warmup spawned BEFORE the test body runs (using a `wait_for_warmup_completed` helper that the integration test waits on before starting concurrent webhooks).

## Why deferred

Out of scope for PR #236 (`bug_demo_clusters_unreachable_in_healthz`). PR #236's intended scope was the `/healthz` cluster-aggregate observability gap, NOT the webhook merge handler's row-lock correctness. Capturing here so the bug is properly tracked.

PR #236's workaround (the env-var gate `RELYLOOP_DISABLE_STARTUP_WARMUP=1` set in integration test conftest) lets the warmup ship without re-exposing the race in `test_ac7` — but it does NOT fix the underlying merge handler. The first feature that requires the warmup to be active during integration tests (or any other lifespan task) will hit this bug again.

## Relationship to other work

- **PR #236 sibling:** `bug_demo_clusters_unreachable_in_healthz` (the originating PR that exposed this race).
- **`bug_pr_reconciler_blocked_by_closed_fallback`** (shipped 2026-05-23 as PR #204): touched the proposal-reconciler logic but did NOT touch the merge handler's row-lock. Worth re-reading for context on how proposals are mutated.
- **`feat_config_repo_baseline_tracking`** (PR #202, merged 2026-05-23): added `last_merged_proposal_id` + the row-lock-protected update path. This is the surface that's racy.
