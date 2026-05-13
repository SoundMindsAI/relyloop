# Idea — chore_query_inline_crud_index_coverage_test

**Date:** 2026-05-13
**Origin:** GPT-5.5 phase-1 review F7 on `feat_query_inline_crud` PR. The implementation plan's Story 1.3 DoD said the test should "Assert the index `judgments_list_query_idx` (already exists) covers the predicate." We deferred this because PG EXPLAIN-plan assertions are brittle (planner choices can shift with stats, vacuum state, or PG version) — but the underlying concern (the batch judgment-count helper relies on an existing composite index) is real.

## Problem

`backend/app/db/repo/judgment.py::count_judgments_per_query` issues:

```sql
SELECT query_id, COUNT(*)
FROM judgments
WHERE query_id = ANY(:query_ids)
GROUP BY query_id;
```

The index that should serve this is `judgments_list_query_idx` (`(judgment_list_id, query_id)` — declared at `backend/app/db/models/judgment.py:55`). Whether Postgres actually uses it for the `WHERE query_id = ANY(...)` predicate depends on cardinality + query_ids set size — at MVP1 scale (<50 ids per page, <10k judgments per query) a seq-scan or different index might be chosen.

The functional integration test `test_count_judgments_per_query_mixed_counts` covers correctness. What's NOT covered: whether the predicate hits the expected index. If it ever stops being indexable (e.g., someone drops the column or changes the index), the helper degrades to O(n) seq-scans silently — fine at MVP1 scale, but the system surfaces no signal until p95 latency rises.

## Why deferred

Adding an `EXPLAIN ANALYZE` assertion in an integration test creates two failure modes:

1. **Brittle to planner choices.** Postgres's planner picks the cheapest plan given statistics. A test that asserts "uses Index Scan on judgments_list_query_idx" can fail simply because the test DB has too few rows for the planner to consider the index worthwhile. Forcing the test to seed enough rows to trigger index use turns a fast unit test into a slow one.

2. **Brittle to schema drift.** If a future migration changes the index name (e.g., `judgments_query_id_idx` as a more targeted single-column index), the test breaks even though the predicate is still indexable.

Both failure modes are noisy, not signal. The right pattern is a separate periodic check (e.g., `pg_stat_user_indexes` showing the index has non-zero scans in production) rather than per-test assertion.

## Proposed scope (when this idea graduates to a spec)

1. Add a `backend/tests/integration/test_query_helper_index_coverage.py` that:
   - Seeds N=100 queries with M=10 judgments each (1000 total rows — enough to make the planner prefer the index)
   - Runs `EXPLAIN (FORMAT JSON, ANALYZE) ...` against the `count_judgments_per_query` SQL
   - Asserts the plan node array contains `"Node Type": "Index Scan"` OR `"Index Only Scan"` referencing `judgments_query_id_*` or `judgments_list_query_idx`
   - Marks the test `@pytest.mark.slow` or runs only on a nightly CI job (not per-PR)

2. Document the seed-volume threshold in the test docstring so reviewers know why N is chosen.

3. Alternative considered: read `pg_stat_user_indexes.idx_scan` for the index after running a high-volume integration test — but that requires per-test stat-table snapshots which is more plumbing than worth it.

## Locked decisions

None — design space is open.

## Open questions for /spec-gen

- Should the test live in the per-PR `make test-integration` lane or a nightly slow-test lane? Recommended default: nightly. Per-PR cost is too high for an index-plan check that rarely regresses.

## Relationship to other work

- Related: `infra_test_smoke_makeup` (sibling — extends the slow-test infrastructure).
- Not blocking any active feature.

## Dependencies

- None. The current behavior is correct; this just adds a regression alarm.

## References

- GPT-5.5 phase-1 review F7 on `feat_query_inline_crud` (this folder's sibling).
- `backend/app/db/repo/judgment.py::count_judgments_per_query` — the helper under test.
- `backend/app/db/models/judgment.py:55` — the `judgments_list_query_idx` definition.
- Story 1.3 DoD in `feat_query_inline_crud/implementation_plan.md` — where this was originally specified.
