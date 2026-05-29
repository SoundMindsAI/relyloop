# Bug fix — bug_smoke_seed_es_unavailable_shards_race

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/smoke-seed-es-unavailable-shards-race`
**Type:** bug fix — medium (~30 LOC backend + 11 unit tests)
**Date:** 2026-05-28

## Problem

The smoke job (`smoke (operator-path tutorial flow)` in [`pr.yml`](../../../../../.github/workflows/pr.yml)) has been chronically red on every PR since PR #291 landed CI-perf optimizations on 2026-05-28. The `Seed sample ES index` step fails intermittently with `unavailable_shards_exception: [products][0] primary shard is not active Timeout: [1m]`. PR #291's compose-up speedup (10m → 21–90s) removed the implicit 5-minute ES warmup window that previously masked the race; now `seed-es` runs immediately after `make up` returns, and on cold GHA runners the ES 9.4.1 primary shard hasn't finished INITIALIZING by the time the bulk POST lands. Live reproductions: PRs #293, #294, and #295 all hit this exact failure on consecutive CI runs.

## Reproduction

Three live CI failures with byte-identical error shape — sufficient as field reproduction. Local repro is unit-test-only:

```bash
.venv/bin/python -m pytest backend/tests/unit/scripts/test_seed_es_retry.py -v
```

The test file mocks httpx to return `unavailable_shards_exception` on the first attempt(s), then a clean payload — exercising the retry path that pre-fix code would have failed on.

## Root cause

- **Owning layer:** script — [`backend/app/scripts/seed_es.py`](../../../../../backend/app/scripts/seed_es.py)
- **Origin:** the per-chunk bulk POST at [seed_es.py:105-110](../../../../../backend/app/scripts/seed_es.py#L105-L110) (pre-fix)
- **Error sink:** the `if payload.get("errors"): return 1` branch at [seed_es.py:112-122](../../../../../backend/app/scripts/seed_es.py#L112-L122) (pre-fix)

ES bulk semantics return HTTP 200 even when the shard isn't ready — the error lives in the JSON response body. The pre-fix code treated any non-empty `errors` field as terminal, so a transient `unavailable_shards_exception` (which clears in 60–90s as the primary shard finishes INITIALIZING) became a permanent CI failure.

## Fix design (locked decisions)

1. **`_cluster/health/<index>?wait_for_status=yellow&timeout=10m` between create and bulk** — the actual synchronization point. Blocks until ES's allocation state machine reports the primary shard active, or 10 minutes elapse. This replaced the original blind-retry-only design after PR #297 run `26611895567` exhausted 8 × 62s retries with the shard still INITIALIZING — blind retries were burning ES's internal 60s shard-availability timeout per attempt without making the shard active any faster. The health probe is the standard ES mechanism for "wait until the index is ready" and lets ES tell us when to proceed instead of guessing.
2. **httpx per-request `timeout=620.0` on the health probe** — overrides the client's 90s default so the 10m server-side wait isn't killed client-side. 620s = 10m + a 20s buffer.
3. **Retry on `unavailable_shards_exception` only** (3 attempts × 2s) — kept as a safety net for residual transients after the health probe returns. Mapping errors / type mismatches still fail loudly on attempt 1. Cites: CLAUDE.md "Don't add error handling for scenarios that can't happen" — broad retry would mask real bugs.
4. **Extract `_bulk_with_retry` + `_first_bulk_error` helpers** — pure-function design lets the unit test mock httpx without spinning up ES. Cites: existing pattern in `backend/app/scripts/seed_meaningful_demos.py` (constants + helpers at module level).
5. **WARN log on each retry** — `seed_es: bulk transient unavailable_shards_exception, retry 1/3 after 2.0s` so flake telemetry is visible in CI logs. Cites: existing structlog pattern at [seed_es.py:42](../../../../../backend/app/scripts/seed_es.py#L42).
6. **Allowlist via `RETRYABLE_BULK_ERROR_TYPES` frozenset** — future additions (e.g., `cluster_block_exception` if it surfaces) extend the set, not the retry call sites. Cites: same source-of-truth pattern as `backend/app/db/models/study.py` `StudyStatus` Literal.
7. **INFO log on health probe outcome** — `seed_es: /products reached yellow (active_shards=1) in Nms` so operators see when activation happened. If the probe times out, log a WARN and proceed to bulk + retries anyway (don't fail-fast at the probe — the bulk may still succeed if activation finishes during the seed walk).

### Open questions

None. All forks lock-with-rationale cleanly.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| Unit | [`backend/tests/unit/scripts/test_seed_es_retry.py`](../../../../../backend/tests/unit/scripts/test_seed_es_retry.py) | 11 cases across 3 classes: succeed after 1/2 transients, exhaust retries → False, non-retryable → False on attempt 1 (no sleep), happy path → 1 call only, `_first_bulk_error` picks the right error from heterogeneous items, constants pinned (3 attempts × 2.0s) |

The test fails on `main` (pre-fix code returns 1 on any error payload, so `_bulk_with_retry` doesn't exist there) and passes on this branch. The existing integration test at `backend/tests/integration/test_seed_es.py` already covers the full `main()` happy path against a real ES — kept unchanged.

## Rollout

None — code-only change to a CI seed script. No migration, no operator action, no feature flag. The fix lands and the next CI run benefits. Worst case if the change misses an edge case: smoke red on PR (which is the status quo).

## Tangential observations

None — the trace stayed clean inside `seed_es.py`. The idea already cataloged the design forks; preflighting saved the discovery step here.
