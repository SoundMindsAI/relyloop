# Flaky test: `test_ac_25_since_lower_bound_inclusive` — UUIDv7 ms-collision

**Date:** 2026-05-14
**Status:** Bug — captured during feat_judgments_periodic_resume_sweep PR #104 CI run
**Origin:** PR #104 CI failure (run 25838202692, 2026-05-14 02:35Z) caught `test_ac_25_since_lower_bound_inclusive` failing in [`backend/tests/integration/test_query_sets_router_queries.py`](../../../../backend/tests/integration/test_query_sets_router_queries.py) — and the most recent `main` CI run (25835793260, 2026-05-14 01:14Z) also failed on the same test before PR #104 even existed. PR #101 (`feat_query_inline_crud`) introduced this test on 2026-05-13.

## Problem

The test (shipped in PR #101) seeds 5 queries via `_seed_set(5)`, takes `query_ids[2]`'s UUIDv7 embedded timestamp (first 48 bits = milliseconds), subtracts 1ms, and uses that as the `?since` boundary. It then expects exactly `q[2], q[3], q[4]` in the result and `q[0], q[1]` excluded.

The flake: when `_seed_set` runs fast enough that two or more queries share the same UUIDv7 millisecond (UUIDv7's 48-bit timestamp has 1ms resolution), the `?since` filter at boundary `q[2]'s ms - 1` is inclusive of any row sharing q[2]'s millisecond — which can include q[0] and q[1] if they were created in the same ms.

Observed failure (CI run 25838202692, 2026-05-14):

```
FAILED backend/tests/integration/test_query_sets_router_queries.py::test_ac_25_since_lower_bound_inclusive
- AssertionError: assert '019e2458-91f3-7613-b888-8ec304db846f' not in
  ['019e2458-91f3-7613-b888-8ec304db846f',  # q[0] — shouldn't be there
   '019e2458-91f4-7d03-b30e-64b92f73cc3b',  # q[2]
   '019e2458-91f6-7051-82e7-fb0cdb35e7da',  # q[3]
   '019e2458-91f8-7db1-b4bf-f4445e184583']  # q[4]
```

All four UUIDs share the `019e2458` 32-bit timestamp prefix → all 4 were created in the same millisecond. The test's assumption that q[0]'s timestamp is strictly less than q[2]'s breaks.

This is a **test bug** — not a production bug. The actual `?since` filter behaviour is correct: it returns every row whose `created_at` is `>= since`. The test makes an assumption about UUIDv7 timestamp uniqueness that doesn't hold under fast execution.

## Proposed capabilities

Three independent fix candidates; the test should pick one and ship:

### 1. Add ms delays between `create_query` calls in `_seed_set`

Sleep 2ms between creates so each query gets a distinct UUIDv7 ms timestamp:

```python
async def _seed_set(count: int) -> tuple[str, list[str]]:
    ...
    query_ids = []
    for i in range(count):
        q = await repo.create_query(...)
        query_ids.append(q.id)
        await asyncio.sleep(0.002)  # ensure distinct UUIDv7 ms timestamps
    ...
```

Pros: smallest change. Cons: slows the test by ~10ms per row; multiplied across all `_seed_set` callsites.

### 2. Use a different boundary that's far from the rows' timestamps

Use `q[2]'s ts - 1000ms` (one full second before) so no q[0] or q[1] can possibly share the boundary. Pros: zero perf cost. Cons: doesn't actually test the "inclusive at boundary" property the test name claims.

### 3. Pin the timestamps explicitly during seed

Use `repo.create_query` with an explicit `created_at` field (if the repo accepts it) so the test fully controls the ordering. Pros: deterministic. Cons: may require repo-layer change to expose `created_at` as a kwarg (currently `now()`-defaulted).

**Recommendation: option 1.** Smallest change, preserves the test's stated intent, predictable on every CI runner.

## Scope signals

- **Backend:** test-only change to `_seed_set` in `backend/tests/integration/test_query_sets_router_queries.py`. ~3 lines.
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.

## Why deferred

The fix is ~3 lines and would qualify for inline-implementation per the implement-over-defer rubric. Capturing as an idea file because:

1. The failing test was introduced in PR #101 (`feat_query_inline_crud`) just yesterday — fixing someone else's recently-merged test in PR #104 (`feat_judgments_periodic_resume_sweep`) would be cross-feature scope creep.
2. Same flake is now failing on `main` — needs its own PR to fix cleanly. Better caught in a follow-up that names the scope ("fix flaky test introduced in #101") than buried inside a worker-feature PR diff.

Recommended next action: ship as a `/impl-execute --ad-hoc` from `main` once #104 is merged.

## Relationship to other work

- Caused by `feat_query_inline_crud` (PR #101). The `_seed_set` helper was first introduced there.
- Same flake fails the current `main` HEAD CI run (25835793260, 2026-05-14 01:14Z) — was already broken before PR #104 opened.
- Does not affect feat_judgments_periodic_resume_sweep's correctness — the test it broke is in a separate router.
