# Bug fix — bug_seed_meaningful_demos_silent_bulk_errors

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/seed-meaningful-demos-silent-bulk-errors`
**Type:** bug fix — medium (this skill's scope)
**Date:** 2026-06-05

## Problem

The ESCI rich-scenario bulk loop in `scripts/seed_meaningful_demos.py` read and **discarded** the `/_bulk` response. ES bulk semantics return HTTP 200 even when the primary shard is still INITIALIZING (the error rides in the JSON body under `items[*].<action>.error`), so an `unavailable_shards_exception` on a cold ES — or any mapping bug — silently produced a partial/empty index while `make seed-demo` reported success. Operators then see zero/short results from studies against the demo cluster and chase a phantom config problem. Latent today because CI no longer runs the demo seed (`chore_drop_demo_seed_from_ci`); local-dev operators still hit it.

## Reproduction

Unit reproducer (no real ES) — the new test fails on `main` (no parse/retry exists) and passes on the branch:

```bash
.venv/bin/python -m pytest backend/tests/unit/scripts/test_seed_meaningful_demos_bulk_retry.py -q --no-cov
```

Verified load-bearing: mutating the helper to `return` instead of `raise` (the old silent behavior) fails `test_raises_after_exhausting_retries` + `test_non_retryable_error_fails_immediately`.

## Root cause

- Owning layer: script — [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) `seed_rich_scenario`, the NDJSON `/_bulk` chunk loop (`with urllib.request.urlopen(req…) as resp: resp.read()` — body parsed nowhere).

## Fix design (locked decisions)

1. **Option A (parse + retry), not Option B (parse + fail only).** Mirror the retry posture shipped for the sibling race in `backend/app/scripts/seed_es.py` (`bug_smoke_seed_es_unavailable_shards_race`): parse the body, retry ONLY `unavailable_shards_exception` (3 attempts × 2s), raise loud on any other error or exhausted retries. Cites: precedent `implemented_features/2026_05_29_bug_smoke_seed_es_unavailable_shards_race/`.
2. **Standalone urllib helper, NOT a shared `scripts/_es_bulk.py` extraction.** `seed_es.py` is async/httpx; `seed_meaningful_demos.py` is sync/urllib and is a standalone repo-root script (importing `backend.app.scripts` would couple it + risk a cycle, since `backend` imports `SCENARIOS` *from* this script). The helper duplicates ~25 LOC of parse/retry rather than unify the HTTP client. Cites: idea Option A "standalone (~30 LOC)".
3. **Injectable `send` / `sleep`.** `_bulk_index_with_retry(body, *, send=_post_bulk_ndjson, sleep=time.sleep)` so the retry logic is unit-testable with no real ES (mirrors how `test_seed_es_retry.py` mocks the client). `_first_bulk_error(payload)` is HTTP-lib-agnostic (operates on parsed JSON).

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/scripts/test_seed_meaningful_demos_bulk_retry.py` | retryable error clears mid-budget → no raise (send N×, sleep N-1×); retryable persists → raises after `_BULK_RETRY_ATTEMPTS`; non-retryable → raises on attempt 1, no sleep; clean success → 1 send, no sleep; `_first_bulk_error` extracts the error dict / returns None. |

## Rollout

None — affects only `make seed-demo` / the home-page "Reset to demo state" path. No migration, no API change. `scripts/` is not in the mypy gate; the new test (under `backend/tests/`) is mypy/ruff-clean.

## Tangential observations

None. (The "extract a shared `_es_bulk.py`" idea was evaluated and rejected — see Fix design #2 — because the two scripts use different HTTP libraries.)
