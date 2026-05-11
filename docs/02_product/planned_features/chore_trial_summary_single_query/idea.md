# chore — `aggregate_trials_summary` 2-query → single-query refactor

**Date:** 2026-05-10
**Type:** `chore_` — perf polish.
**Origin:** GPT-5.5 Epic 1 phase-gate review of `feat_study_lifecycle` Phase 2 (finding E1-F1, 2026-05-10).

## Problem

[`backend/app/db/repo/trial.py:aggregate_trials_summary`](../../../../backend/app/db/repo/trial.py) currently issues two SQL statements:

1. A single SELECT with COUNT(*) FILTER (...) aggregations and `MAX(primary_metric)` to compute counts + best metric.
2. A second SELECT to find `best_trial_id` matching the best metric (when non-null).

The implementation plan (Story 1.4 key interface) specified this as a single SQL statement using `COUNT(*) FILTER` + `MAX` + a window-function or CTE-based subquery for `best_trial_id`.

The 2-query implementation is functionally correct and well within the spec §13 `<100ms p99` wall-clock target on small studies (the existing integration tests pass within milliseconds). The drift is performance-shaped, not correctness-shaped — but it's a divergence from the plan's contract.

## Why deferred

The two queries are independently fast on PG's small-table data + the `trials_study_metric` index. Fixing it would mean rewriting the helper with a CTE (`WITH counts AS (...) SELECT ... FROM counts JOIN trials ...`) which is more brittle to write/test in isolation. Deferring as a polish pass keeps Story 1.4 shippable.

## Fix

Rewrite as a single CTE-based statement:

```sql
WITH summary AS (
  SELECT
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE status = 'complete') AS complete,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
    COUNT(*) FILTER (WHERE status = 'pruned') AS pruned,
    MAX(primary_metric) FILTER (WHERE status = 'complete') AS best
  FROM trials WHERE study_id = :id
)
SELECT
  summary.*,
  (SELECT id FROM trials
   WHERE study_id = :id AND status = 'complete'
     AND primary_metric = summary.best
   ORDER BY optuna_trial_number LIMIT 1) AS best_trial_id
FROM summary;
```

Existing integration tests in `test_phase2_repos.py::TestTrialsSummary` already cover the contract; no test changes needed.

## Cross-references

- [`feat_study_lifecycle/phase2_implementation_plan.md`](../feat_study_lifecycle/phase2_implementation_plan.md) Story 1.4 key interface.
- [`backend/app/db/repo/trial.py`](../../../../backend/app/db/repo/trial.py) — `aggregate_trials_summary`.
