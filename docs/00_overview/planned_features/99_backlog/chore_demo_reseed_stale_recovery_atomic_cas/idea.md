# Idea — Make demo-reseed stale-status recovery an atomic CAS

**Date:** 2026-05-28
**Status:** Idea — captured during PR #299 GPT-5.5 final review (finding #2, adjudicated non-regression)
**Priority:** Backlog (defense-in-depth; current guards already prevent duplicate runs)
**Origin:** GPT-5.5 review of PR #299 (`bug_demo_reseed_button_silent_enqueue_failure`)
**Depends on:** None — builds on the merged stale-status recovery in PR #299

## Problem

PR #299 added stale-status auto-recovery to the demo-reseed POST handler ([`_test.py`](../../../../backend/app/api/v1/_test.py)): when the Redis status is `running` but `started_at` is older than `DEMO_RESEED_JOB_TIMEOUT_S` (1200s), the handler treats it as failed and proceeds with a new enqueue instead of 409'ing forever.

GPT-5.5 noted this is a **non-atomic check-then-set**: two concurrent POSTs could both read the same stale `running` payload, both pass the staleness check, and both call `enqueue_job`.

**Why this is non-blocking (the reason it was deferred, not fixed inline):** duplicate *runs* are already prevented by two existing layers:

1. The deterministic Arq `_job_id="demo_reseed:singleton"` ([`_test.py:663-666`](../../../../backend/app/api/v1/_test.py#L663)) — Arq drops a duplicate enqueue with the same job id while the first is queued/in-progress.
2. The Postgres advisory lock the worker acquires ([`demo_reseed.py:94-101`](../../../../backend/workers/demo_reseed.py#L94)) — a second worker that somehow raced through gets `pg_try_advisory_lock` = false and exits with a clean `failed` status.

So the worst case today is two enqueue *attempts*, one of which Arq dedups, and an advisory-lock backstop beneath that. No duplicate destructive wipe can occur.

## Proposed capabilities

### Atomic stale-status transition

- Replace the check-then-set with a Redis CAS / Lua compare on the observed status payload: only the POST that successfully flips the stale `running` → a fresh `running` (or a transient `recovering` sentinel) proceeds to enqueue; the loser returns 409.
- Alternatively, a short-lived `SET NX` recovery lock keyed on the status key, released after the enqueue.

## Scope signals

- **Backend:** `backend/app/api/v1/_test.py` reseed POST handler; possibly a new helper in `backend/app/services/demo_seeding.py` for the CAS. ~30-50 LOC + a unit test for the concurrent-POST race.
- **Frontend:** none.
- **Tests:** unit test simulating two concurrent stale-recovery POSTs against a fake Redis with CAS semantics.

## Why deferred

Defense-in-depth only — the existing deterministic job-id + advisory-lock guards already make duplicate runs impossible. Filed per the tangential-discoveries protocol; graduate to P2 if a real double-enqueue is ever observed (it would show as two `demo_reseed_worker_lock_contention` WARN lines in close succession).
