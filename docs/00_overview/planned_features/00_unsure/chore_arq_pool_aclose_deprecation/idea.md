# Idea — replace deprecated `arq_pool.close()` with `aclose()`

**Date:** 2026-05-31
**Status:** Idea — tangential discovery during `feat_overnight_autopilot` (Epic 1 integration tests, PR forthcoming)
**Type:** `chore_`
**Priority:** P2 — deprecation warning only; works today, will break on a future arq major.

## Origin

Every integration-test teardown during `feat_overnight_autopilot` Epic 1 emitted a `DeprecationWarning` from the API shutdown path: `arq_pool.close()` is deprecated in favor of `aclose()` (arq ≥ 5.0.1).

## Problem

[`backend/app/main.py`](../../../../backend/app/main.py) (~line 144, the FastAPI lifespan/shutdown that closes the Arq Redis pool) calls `arq_pool.close()`. arq deprecated the sync-named `close()` in favor of `aclose()`. The warning fires on every shutdown (and floods integration-test teardown logs). When arq removes `close()` in a future major, the shutdown will raise.

## Proposed capability

Replace the `arq_pool.close()` call with `await arq_pool.aclose()` (verify the exact symbol against the installed arq version + its current API). Add nothing else — purely a deprecation fix.

## Scope signals

- **Backend:** trivial — one call site in `main.py`.
- **Frontend / migration / config:** none.
- **Audit events:** N/A.

## Why deferred (not fixed inline)

`main.py` is the app-lifecycle entry point, untouched by `feat_overnight_autopilot` (a read-only chain endpoint). Editing it in the feature PR would mix an unrelated lifecycle change into a studies-feature diff. The fix is a one-liner but belongs in its own small chore so the blame/scope stays clean. Verify there are no other `.close()` call sites on Redis/arq pools while you're in there.

## Relationship to other work

- Pure maintenance; no feature dependency. Pick up with any other `backend/app/main.py` touch.
