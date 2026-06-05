# Idea — replace deprecated `arq_pool.close()` with `aclose()`

**Date:** 2026-05-31
**Status:** Idea — tangential discovery during `feat_overnight_autopilot` (Epic 1 integration tests, PR forthcoming)
**Type:** `chore_`
**Priority:** P2 — deprecation warning only; works today, will break on a future arq major.

## Origin

Every integration-test teardown during `feat_overnight_autopilot` Epic 1 emitted a `DeprecationWarning` from the API shutdown path: `arq_pool.close()` is deprecated in favor of `aclose()`. (The installed arq is **0.28.0** — arq is still pre-1.0 / 0.x; the deprecation was introduced on the `ArqRedis.close()` method in a recent 0.x release. Verified 2026-06-01: `arq.connections.ArqRedis` exposes both `close` and `aclose` in 0.28.0, with `aclose()` the non-deprecated coroutine.)

## Problem

There are **two** deprecated `arq_pool.close()` call sites, not one (preflight 2026-06-01):

1. [`backend/app/main.py:144`](../../../../backend/app/main.py) — the FastAPI lifespan `finally` block that closes the API's Arq Redis pool on shutdown.
2. [`backend/workers/all.py:225`](../../../../backend/workers/all.py) — the Arq worker's `on_shutdown` hook that closes the shared pool cached in `ctx["arq_pool"]`.

Both call `await arq_pool.close()`. arq deprecated the sync-named `close()` in favor of the `aclose()` coroutine. The warning fires on every shutdown (and floods integration-test teardown logs). When arq removes `close()` in a future release, both shutdown paths will raise.

The same-file precedent already uses the correct form: `backend/app/main.py:177` calls `await redis_client.aclose()`, and `backend/workers/demo_reseed.py:254` / `seed_clusters.py:98` call `await redis.aclose()` on raw Redis clients.

## Proposed capability

Replace both `await arq_pool.close()` calls with `await arq_pool.aclose()` — `backend/app/main.py:144` and `backend/workers/all.py:225`. Add nothing else — purely a deprecation fix.

## Scope signals

- **Backend:** trivial — two call sites (`main.py:144`, `workers/all.py:225`).
- **Test coupling:** [`backend/tests/unit/test_main_lifespan.py:86`](../../../../backend/tests/unit/test_main_lifespan.py) stubs `fake_pool.close = AsyncMock(...)`. Because `fake_pool` is a bare `MagicMock`, calling the new `await fake_pool.aclose()` on it would await a non-awaitable MagicMock and raise — so this stub must flip to `fake_pool.aclose = AsyncMock(...)`. The worker `on_shutdown` (`all.py`) has no equivalent unit lifespan test today; add a focused unit/integration assertion that `aclose` (not `close`) is awaited on both shutdown paths so the regression is caught if a future edit reintroduces `close()`.
- **Frontend / migration / config:** none.
- **Audit events:** N/A — pure lifecycle cleanup, no tenant-visible state mutation.

## Why deferred (not fixed inline)

`main.py` and `workers/all.py` are app/worker-lifecycle entry points, untouched by `feat_overnight_autopilot` (a read-only chain endpoint). Editing them in the feature PR would mix an unrelated lifecycle change into a studies-feature diff. The fix is two one-liners but belongs in its own small chore so the blame/scope stays clean. (Preflight 2026-06-01 already swept for other Redis/arq pool `.close()` sites: the only two are `main.py:144` and `workers/all.py:225`; every other shutdown path — `redis_client.aclose()`, `adapter.aclose()`, `openai_client.close()` — is either already async-correct or a non-arq client out of scope.)

## Relationship to other work

- Pure maintenance; no feature dependency. Pick up with any other `backend/app/main.py` touch.
- **Surfaced a CI-policy gap:** this fix shipped via [PR #387](https://github.com/SoundMindsAI/relyloop/pull/387) (merged 2026-06-02 as `2e49ac99`), submitted by an external contributor. Its first run exposed that the `smoke` job hard-fails on every external-fork PR because forked PRs can't read `OPENAI_API_KEY_TEST` — captured as [`infra_smoke_fork_pr_secret_skip`](../infra_smoke_fork_pr_secret_skip/idea.md).

## Postscript — shipped

Shipped via PR #387 (squash commit `2e49ac99`, 2026-06-02). Both call sites converted to `aclose()`; regression tests added at both shutdown paths. The `fake_pool.close = AsyncMock(...)` stub flip predicted in "Scope signals" was applied, and `fake_pool.close` was additionally retained as an `AsyncMock` so the `close.assert_not_called()` negative assertion fails cleanly rather than crashing on a non-awaitable mock — a Gemini review point the contributor addressed before merge.
