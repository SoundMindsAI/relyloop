# Smoke seed-es step flakes with `unavailable_shards_exception` on cold GHA runners

**Date:** 2026-05-28
**Status:** Idea — captured as part of PR #291 admin-merge
**Priority:** P1 — intermittent CI red on PRs touching the smoke surface
**Origin:** PR #291 (`chore_ci_perf_buildx_artifact_image_cache_xdist`) verified the CI-perf optimizations across 9 CI runs. The seed-es step intermittently fails with `unavailable_shards_exception: [products][0] primary shard is not active Timeout: [1m]` on the bulk-index call. Runs 3 + 4 succeeded; runs 1, 5, 6, 7, 9 failed; runs 5 + 8 failed for different reasons that PR #291 fixed. The seed-es race is the residual flake that PR #291 did not solve.
**Depends on:** PR #291 merged (`<sha>`). The fast smoke path (compose-up went from 10min → 21-90s) is what exposes this race — the previous slow path masked it by granting ES ~5min of ambient warmup.

## Problem

`backend/app/scripts/seed_es.py` creates the `products` index then immediately bulk-indexes 1000 docs against it. On cold GHA runners with ES 9.4.1 (bumped from 9.4.0 in PR #290), the bulk call sometimes returns:

```
unavailable_shards_exception: [products][0] primary shard is not active Timeout: [1m],
request: [BulkShardRequest [[products][0]] containing [500] requests]
```

The PUT `/products` index-create call succeeds (200), but the cluster takes more than 1 minute to mark the single primary shard as active. ES's bulk-index has a 1-minute internal timeout on shard availability; when it's exceeded, the call returns `unavailable_shards` and seed_es exits non-zero.

**Why it surfaces now:** PR #291 reduced the smoke job's `Bring up the stack` step from ~10 min to ~21-90 s by pre-building the API + UI images in parallel buildx jobs and caching base service-container images. Before the optimization, ES had ~5 min of ambient warmup time between coming up healthy and the seed-es step running; now seed-es runs immediately after `make up` returns, exposing the cold-start race.

**Why `number_of_replicas: 0` didn't fully fix it:** PR #291 already set `settings.number_of_replicas: 0` on the create call (eliminates the unallocatable-replica problem on single-node ES). But the primary shard itself takes >1 min to activate on a cold ES 9.4.1 cluster — that's an ES-side delay, not a replica issue.

**Why `wait_for_status=yellow` in the compose healthcheck didn't fix it:** Single-node ES at boot has no shards to wait on, so `_cluster/health?wait_for_status=yellow` returns immediately. The healthcheck is therefore "true" before ES is actually ready to allocate primary shards on newly-created indices. Tightening the healthcheck to gate on something stricter (e.g., `wait_for_active_shards`) doesn't help because we need to wait for FUTURE allocations, not existing ones. (PR #291 also tried tightening this and rolled back when it broke `docker compose up --wait`.)

## Proposed capabilities

Four candidate approaches, ranked by likely effectiveness + lowest risk:

### Option A — Retry bulk on `unavailable_shards_exception` (recommended)

Wrap the bulk loop in `seed_es.py` with a 3-attempt retry that catches `unavailable_shards_exception` specifically (not other bulk errors). 2s sleep between attempts. Total worst-case added time: 6s.

```python
for attempt in range(3):
    bulk_resp = await client.post("/_bulk", content=..., headers=...)
    payload = bulk_resp.json()
    if payload.get("errors"):
        first_error = next(...)
        if first_error and first_error.get("type") == "unavailable_shards_exception" and attempt < 2:
            logger.warning("seed_es: shard not active, retry %d/3", attempt + 1)
            await asyncio.sleep(2)
            continue
        logger.error("seed_es: bulk index reported errors; first: %s", first_error)
        return 1
    break  # success
```

Pros: surgical, targets the exact race, fails loudly if it's not transient.
Cons: adds up to 6s on the happy path (negligible).

### Option B — Pre-warm ES before seed-es runs

Add a workflow step between "Apply migrations" and "Seed clusters" that pings ES until a test-index can be created + deleted successfully. Effectively a warmup probe.

Pros: solves it at the orchestration level; doesn't change seed_es.
Cons: more YAML to maintain; the wait time is opaque to operators reading the workflow.

### Option C — Revert OS 3.6.0 → 2.19.5 in docker-compose.yml

The bumps from PR #290 (OpenSearch 2.18.0 → 3.6.0, ES 9.4.0 → 9.4.1) may have changed startup timing. ES 9.4.0 didn't show this race on PR #290's CI runs (it timed out before seed-es ever started).

Pros: bisection win if reverting fixes it.
Cons: gives up the OS 3.x scope per relyloop-spec.md §8; doesn't address ES 9.4.1 which is the one actually failing.

### Option D — Add `init_period` or `start_period` to compose healthcheck

Docker compose v2 supports `start_period` on healthchecks — give ES extra grace time on initial startup before the healthcheck starts polling.

Pros: gives the operator a clean knob to tune.
Cons: doesn't address the actual problem (ES is "healthy" but not write-allocation-ready); just slows down `docker compose up --wait`.

## Scope signals

- **Backend:** ~10 LOC change to `backend/app/scripts/seed_es.py` for Option A.
- **CI workflow:** 0 LOC for Option A; ~10 LOC for Option B.
- **Compose:** 0 LOC for Option A; 1 LOC for Option D.
- **Migration:** N/A.
- **Tests:** add a unit test for the retry logic (mocked httpx + counter for retry attempts).
- **Audit events:** N/A.

## Why not implemented inline in PR #291

PR #291 was scoped as "CI-perf: reuse buildx artifacts + image cache + pytest-xdist." Each new commit attempted to address the seed-es flake in different ways:
- 3rd commit: `number_of_replicas: 0` on index create (partial fix; helps but doesn't eliminate)
- 6th commit: tightened compose healthcheck (broke compose --wait; reverted)
- 7th commit: httpx timeout 30s → 90s (resolved one failure mode, exposed the next)

After 9 CI runs the perf wins are verified, but the seed-es race is genuinely intermittent and needs its own focused investigation rather than another speculative fix layered onto a scope-creeping PR. Per CLAUDE.md "implement-over-defer" rubric, this falls into the "different subsystem + cross-cutting" bucket that warrants a separate PR.

## Relationship to other work

- **Surfaced by PR #291** — the CI-perf optimizations exposed the latent race by removing ~5min of ambient ES warmup
- **Not blocked by anything** — can be implemented immediately
- **Composes with the MVP2 Solr adapter** (`infra_adapter_solr/idea.md`) — Solr seed will have its own analogous startup pattern; the retry-on-transient-shard-error pattern from Option A is reusable
- **Composes with MVP3 observability** — once Langfuse/SigNoz are in, slow seed-es runs will appear in traces, making the next debugging cycle easier
