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

After three rounds of CI-side iteration on the seed script, the **actual** root cause turned out to be in the ES container config, not the seed script:

- **Owning layer:** infra — [`docker-compose.yml:198-203`](../../../../../docker-compose.yml#L198-L203) (the `elasticsearch` service env)
- **Diagnostic:** smoke-logs artifact from PR #297 run `26612512222` showed:
  > `high disk watermark [90%] exceeded ... free: 6.8gb[9.5%], shards will be relocated away from this node`

  GHA runners boot with ~6.8 GB free out of ~71 GB (~9.5%). ES's default high-watermark allocation gate is 90% — exceeded — so ES refuses to allocate new shards on that node. Cluster health stays at `status: red`, `active_primary_shards: 0`, `initializing_shards: 0` (ES isn't even *trying* to allocate). That's why all the bulk retries + health probes failed: the shard was never going to activate.

The watermark behavior is correct on multi-node clusters (relocate shards off a full node), but harmful on the single-node dev/CI setup where there's nowhere to relocate to. Disabling `cluster.routing.allocation.disk.threshold_enabled` removes the gate.

Two secondary issues compounded the failure mode:
- **Script:** [`backend/app/scripts/seed_es.py:112-122`](../../../../../backend/app/scripts/seed_es.py#L112-L122) (pre-fix) treated any non-empty `errors` field in the bulk response as fatal. ES bulk semantics return HTTP 200 even when the shard is transiently unavailable, so a genuinely transient `unavailable_shards_exception` was indistinguishable from a real mapping bug.
- **Synchronization:** the script proceeded straight from `PUT /<index>` to `POST /_bulk` with no wait for the primary shard to be allocated. Even with watermark gating disabled, cold ES can take seconds-to-minutes to finish allocating; `_cluster/health?wait_for_status=yellow` is the right tool to wait for the actual readiness signal.

## Fix design (locked decisions)

1. **Disable disk-watermark gating on the single-node dev/CI ES** — add `cluster.routing.allocation.disk.threshold_enabled=false` to `docker-compose.yml`'s `elasticsearch` service env. This is the **actual** root cause; without it, no amount of script-side iteration would help on a low-disk runner. Cites: ES allocation-decider docs (`DiskThresholdMonitor`); the watermark is a multi-node-cluster safeguard not appropriate for single-node setups. Caveat: production deployment would NOT do this — production uses managed ES with provisioned disk.
2. **`_cluster/health/<index>?wait_for_status=yellow&timeout=10m` between create and bulk** — synchronization with ES's allocation state machine. Even with watermark gating off, cold ES still takes seconds-to-minutes to allocate. Blocks until ready or 10 min elapse; httpx per-request `timeout=620.0` overrides the client's 90s default. Accepts both HTTP 200 (condition met) and HTTP 408 (timed out — still proceed and let the bulk retry safety net catch any residual transient).
3. **Retry on `unavailable_shards_exception` only** (3 attempts × 2s) — safety net for residual transients after the health probe returns. Mapping errors / type mismatches still fail loudly on attempt 1. Cites: CLAUDE.md "Don't add error handling for scenarios that can't happen" — broad retry would mask real bugs.
4. **Extract `_bulk_with_retry` + `_first_bulk_error` helpers** — pure-function design lets the unit test mock httpx without spinning up ES. Cites: existing pattern in `scripts/seed_meaningful_demos.py` (constants + helpers at module level).
5. **WARN log on each retry** — `seed_es: bulk transient unavailable_shards_exception, retry 1/3 after 2.0s` so flake telemetry is visible in CI logs. Cites: existing structlog pattern at [seed_es.py:42](../../../../../backend/app/scripts/seed_es.py#L42).
6. **Allowlist via `RETRYABLE_BULK_ERROR_TYPES` frozenset** — future additions (e.g., `cluster_block_exception` if it surfaces) extend the set, not the retry call sites. Cites: same source-of-truth pattern as `backend/app/db/models/study.py` `StudyStatus` Literal.
7. **INFO log on health probe outcome** — `seed_es: /products reached yellow (active_shards=1) in Nms` so operators see when activation happened. If the probe times out (HTTP 408 with `timed_out: true`), log a WARN and proceed to bulk + retries anyway — don't fail at the probe; the bulk may still succeed if activation finishes during the seed walk.

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
