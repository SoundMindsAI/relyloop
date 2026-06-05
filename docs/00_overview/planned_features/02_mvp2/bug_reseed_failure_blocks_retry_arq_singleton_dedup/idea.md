# Idea — a failed demo reseed silently blocks retries (~1h) via Arq singleton dedup

**Date:** 2026-05-31
**Status:** Idea — tangential discovery while verifying `fix(demo): add Solr (8983) to the reseed engine host-URL mapping` (branch `feat_demo_reseed_solr_and_steplog`)
**Type:** `bug_`
**Priority:** P2 — operator-facing: after ANY reseed failure, the next reseed silently never runs until the stale Arq result expires (~1h), with the UI stuck "spinning". No data loss, but confusing and blocks recovery.

> **Verified still live 2026-06-05 (P2 backlog grooming).** Confirmed against the current tree:
> - The fixed `_job_id="demo_reseed:singleton"` enqueue is unchanged at [`_test.py:691-694`](../../../../../backend/app/api/v1/_test.py) and does **not** handle the `job is None` dedup-drop (it logs `job_id=None` and returns an already-written `status="running"`).
> - The all-engines-unreachable mitigation (`infra_solr_ci_readiness`) at [`demo_seeding.py:1997`](../../../../../backend/app/services/demo_seeding.py) **deliberately raises → `status="failed"`**, which is precisely the terminal state that caches under `arq:result:demo_reseed:singleton` and wedges the retry. So that mitigation *keeps this wedge path reachable* — it fixed the "masquerade-as-success" half, not the "failed-result blocks re-enqueue" half.
> - **Severity confirmed ~1h, not 60s.** The inline comment at `_test.py:688` ("Arq drops duplicate enqueues … default 60s") is **misleading** — the live-reproduced wedge is the `keep_result` result key (~3600s), not a 60s dedup window. Fixing this idea should also correct that comment. Recommended fix is option 1 (clear the singleton result key on terminal state in the worker) — cheapest, preserves the singleton concurrency guard.

## Origin

Reproduced live: the Solr host-URL bug caused a reseed to **fail** on the Solr
scenario. Immediately re-triggering `POST /api/v1/_test/demo/reseed` returned
`200 {status: "running"}`, but the **worker never picked up the job** — its log
stayed empty and the status sat at `current_step = "enqueued — waiting for
worker"`, `scenarios_completed = 0` indefinitely. Manual Redis inspection found
the culprit; clearing it unblocked the retry.

## Problem

`run_demo_reseed` is enqueued with a fixed Arq job id `demo_reseed:singleton`
(the singleton concurrency guard). When a run reaches a terminal state, Arq
stores its **result** under `arq:result:demo_reseed:singleton` for
`keep_result` (Arq default ~3600 s). A subsequent enqueue with the **same job
id** is **deduplicated by Arq** — `enqueue_job` returns `None` and the job is
**silently dropped**. So:

- Worker never receives the retry → no `demo_reseed_worker_started`, empty logs.
- The API has already optimistically written `status = "running"` to
  `demo_reseed:status`, so the UI shows an in-progress reseed that will never
  advance, and the in-tool 409 `SEED_IN_PROGRESS` guard now rejects further
  attempts (it reads the stuck "running" status).
- Net: a single failed reseed wedges the feature for up to ~1 h.

This is the inverse of the dedup behavior `chore_demo_seeding_integration_tests_rewrite`
already documents for the *concurrent* case — here it bites the *sequential
retry-after-failure* case.

## Manual recovery (today)

```bash
docker compose exec -T redis redis-cli del arq:result:demo_reseed:singleton demo_reseed:status
# then re-POST /api/v1/_test/demo/reseed
```

## Proposed fix (pick one at spec time)

1. **Clear the singleton result on terminal state.** When the worker finishes
   (complete OR failed), `redis.delete("arq:result:demo_reseed:singleton")` (and
   any `arq:in-progress:` key) so the next enqueue isn't deduped. Cheapest;
   preserves the singleton guard for genuine concurrency.
2. **Detect the dropped enqueue.** `enqueue_job(..., _job_id="demo_reseed:singleton")`
   returns `None` when deduped — the POST handler should treat `None` as "a prior
   run's result is blocking re-enqueue", clear it (or surface a precise 409 that
   says *retry blocked by a previous run; clearing*), instead of writing an
   unbacked `status = "running"`.
3. **Fresh job id per attempt + rely on the status/lock guard for concurrency.**
   Drop the singleton job id; the existing status-based 409 + the Postgres
   advisory lock (`DEMO_RESEED_LOCK_KEY`) already prevent concurrent runs. Removes
   the dedup foot-gun entirely but changes the concurrency model — needs care.

Add a regression test: enqueue → force-fail → re-enqueue must actually run (not
be deduped). The `chore_demo_seeding_integration_tests_rewrite` async-harness
work is the natural home for this assertion.

## Scope signals

- **Backend:** small-moderate — the worker terminal-state cleanup +/or the POST
  handler's dropped-enqueue handling (`backend/workers/demo_reseed.py`,
  `backend/app/api/v1/_test.py`, `backend/app/services/demo_seeding.py`).
- **Frontend:** none (the UI just polls status).
- **Migration / config:** none.
- **Audit events:** N/A (test-only endpoint).

## Relationship to other work

- Surfaced by `fix(demo): add Solr (8983) to the reseed engine host-URL mapping`
  (the Solr failure is what left the stale singleton result).
- Adjacent to `chore_demo_seeding_integration_tests_rewrite` (async-flow test
  rewrite) — the regression test for this belongs in that harness.
- Same Arq-singleton mechanism noted in that chore's spec for the concurrent-POST
  case; this is the retry-after-failure case.
