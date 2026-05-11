# Periodic in-worker resume sweep for stuck judgment lists

**Date:** 2026-05-11
**Status:** Idea — deferred from feat_llm_judgments cycle-2 plan review
**Origin:** `docs/02_product/planned_features/feat_llm_judgments/implementation_plan.md` cycle 2 F1 (Appendix)
**Depends on:** None

## Problem

`feat_llm_judgments` Story 2.1 ships a **boot-time** resume sweep in
`backend/workers/all.py:on_startup`: every `judgment_lists.status='generating'`
row gets re-enqueued at worker boot, covering the case where
`POST /judgments/generate` committed the row but `arq.enqueue_job` raised
mid-call (Redis transient outage).

Gap: an Arq enqueue failure that lands **while the worker is already
running** leaves the row stuck in `status='generating'` until the next
worker restart. The runbook documents a manual CLI recovery
(`python -m backend.scripts.judgments_resume`), but a periodic in-worker
sweep would heal these without operator intervention.

## Proposed capabilities

### In-worker periodic re-enqueue

Implement an Arq cron job (or equivalent) that runs every N minutes:

* Fetch `list_generating_judgment_list_ids(db)`.
* For each id, fetch the most recent Arq job log entry. If the worker
  hasn't observed the id in the last M minutes, re-enqueue it.
* Cap re-enqueues per (id, day) to avoid runaway loops when a list
  fails for a structural reason (e.g., bad rubric).

### Failure-floor metric

Emit a structured `event_type=judgment_stuck_detected` log line on every
sweep so observability can alarm when N>0 lists are stuck for >M minutes.

## Scope signals

- **Backend:** new Arq cron + supporting `repo.last_judgment_event_at` helper
- **Frontend:** none
- **Migration:** none (uses existing `status` column)
- **Config:** new settings `JUDGMENTS_RESUME_SWEEP_INTERVAL_MIN`,
  `JUDGMENTS_RESUME_MAX_PER_DAY`
- **Audit events:** N/A (MVP1)

## Why deferred

* MVP1 ships boot-time sweep + manual CLI; both are sufficient for the
  single-operator-laptop deployment target.
* Periodic in-worker sweeps need cron-style infra that isn't yet in the
  worker (Arq has `cron_jobs` but the project hasn't wired one yet —
  introducing it here would expand the scope beyond the feature).

## Relationship to other work

Independent. The CLI recovery path documented in
`docs/03_runbooks/judgment-generation-debugging.md` is the MVP1
workaround; this idea is the strategic fix.
