# Flaky test: `test_ac_25_since_lower_bound_inclusive` — UUIDv7 ms-collision

**Date:** 2026-05-14
**Preflighted:** 2026-05-14 — verified test + helper still in place; added line numbers; flake-frequency reframed (most recent main run was green, but the underlying race still exists); recommended-fix sleep duration aligned to the established `test_phase2_repos.py:131` precedent.
**Status:** Bug — captured during feat_judgments_periodic_resume_sweep PR #104 CI run
**Origin:** PR #104 CI failure (run 25838202692, 2026-05-14 02:35Z) caught `test_ac_25_since_lower_bound_inclusive` failing in [`backend/tests/integration/test_query_sets_router_queries.py:202`](../../../../backend/tests/integration/test_query_sets_router_queries.py#L202). The flake is intermittent — most recent `main` CI run (25852260681, 2026-05-14 09:20Z, after PR #104 + #105 merge) passed cleanly, but run 25835793260 (2026-05-14 01:14Z, after PR #103 merge) failed on the same test with the same UUIDv7 ms-collision signature. PR #101 (`feat_query_inline_crud`) introduced this test on 2026-05-13.

## Problem

The test ([`test_query_sets_router_queries.py:202-231`](../../../../backend/tests/integration/test_query_sets_router_queries.py#L202-L231)) seeds 5 queries via `_seed_set(5)` (defined at [`:32-65`](../../../../backend/tests/integration/test_query_sets_router_queries.py#L32-L65)), takes `query_ids[2]`'s UUIDv7 embedded timestamp (first 48 bits = milliseconds), subtracts 1ms, and uses that as the `?since` boundary. It then expects exactly `q[2], q[3], q[4]` in the result and `q[0], q[1]` excluded.

The flake: `_seed_set`'s inner loop calls `uuid_utils.uuid7()` once per query inside a single `async with factory() as db:` block — no sleep between iterations. When CI's runner executes that loop fast enough, two or more queries share the same UUIDv7 millisecond (UUIDv7's 48-bit timestamp has 1ms resolution). The `?since` filter at boundary `q[2]'s ms - 1` then matches any row sharing q[2]'s millisecond — including q[0] and q[1] if they were created in the same ms.

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

### 1. Add ms delays between `create_query` calls in `_seed_set` (locked recommendation)

Sleep 10ms between creates so each query gets a distinct UUIDv7 ms timestamp. **This pattern is already used verbatim in the codebase at [`backend/tests/integration/test_phase2_repos.py:131`](../../../../backend/tests/integration/test_phase2_repos.py#L131) (and `:440`, `:461`):**

```python
# Existing precedent (test_phase2_repos.py:131):
await asyncio.sleep(0.01)  # ensure created_at differs across rows
```

Applying it to `_seed_set` in `test_query_sets_router_queries.py`:

```python
# At the top of the file — add `import asyncio` (currently not imported).
import asyncio

async def _seed_set(num_queries: int = 3) -> tuple[str, list[str]]:
    ...
    query_ids: list[str] = []
    for i in range(num_queries):
        q = await repo.create_query(
            db, id=str(uuid_utils.uuid7()), ...
        )
        query_ids.append(q.id)
        await asyncio.sleep(0.01)  # ensure distinct UUIDv7 ms timestamps
    await db.commit()
    return qs.id, query_ids
```

Pros: smallest change (~3 lines); matches established codebase precedent; predictable on every CI runner. Cons: ~50ms wall-clock per `_seed_set(5)` call, multiplied across the ~20 test callsites in that file. At 1s total slowdown across the suite this is negligible.

Why 10ms (not 2ms): UUIDv7's 48-bit timestamp resolution is 1ms; macOS/Linux CLOCK_REALTIME monotonic deltas are typically ≥1ms but not guaranteed sub-2ms. The existing precedent at `test_phase2_repos.py` uses 10ms and has been stable across hundreds of CI runs — reuse the proven value rather than tighten it.

### 2. Use a different boundary that's far from the rows' timestamps

Use `q[2]'s ts - 1000ms` (one full second before) so no q[0] or q[1] can possibly share the boundary. Pros: zero perf cost. Cons: doesn't actually test the "inclusive at boundary" property the test name claims.

### 3. Pin the timestamps explicitly during seed

Use `repo.create_query` with an explicit `created_at` field (if the repo accepts it) so the test fully controls the ordering. Pros: deterministic. Cons: may require repo-layer change to expose `created_at` as a kwarg (currently `now()`-defaulted).

**Locked: option 1** (preflight 2026-05-14). Smallest change, preserves the test's stated intent, matches the existing `test_phase2_repos.py:131,440,461` precedent verbatim, predictable on every CI runner. Options 2 and 3 left in the doc for context but not under consideration.

## Scope signals

- **Backend:** test-only change to `_seed_set` in `backend/tests/integration/test_query_sets_router_queries.py:32-65` (+1 `import asyncio` at the top). ~4 lines total.
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (test-only).
- **CLAUDE.md absolute rules walked:** none implicated (no schema, no API surface, no LLM call, no secret, no engine-adapter call, no audit_log emission, no `<select>`/enum surface, no `/healthz` touch).

## Why deferred

The fix is ~3 lines and would qualify for inline-implementation per the implement-over-defer rubric. Capturing as an idea file because:

1. The failing test was introduced in PR #101 (`feat_query_inline_crud`) just yesterday — fixing someone else's recently-merged test in PR #104 (`feat_judgments_periodic_resume_sweep`) would be cross-feature scope creep.
2. Same flake is now failing on `main` — needs its own PR to fix cleanly. Better caught in a follow-up that names the scope ("fix flaky test introduced in #101") than buried inside a worker-feature PR diff.

Recommended next action: ship as a `/impl-execute --ad-hoc` from `main` once #104 is merged.

## Relationship to other work

- Caused by `feat_query_inline_crud` (PR #101, merged 2026-05-13 as `6a21da4`). The `_seed_set` helper was first introduced there.
- Established sleep-precedent borrowed from `feat_phase2`-era integration tests at `backend/tests/integration/test_phase2_repos.py:131`. Same fix shape, same rationale comment, same 10ms value.
- Does NOT affect `feat_judgments_periodic_resume_sweep` (PR #104, shipped 2026-05-14) — the flaky test is in a separate router and was incidentally surfaced by #104's CI run.
- Recommended next action: `/impl-execute --ad-hoc` against `main` once an operator has the bandwidth — the fix is small enough for ad-hoc scope (`<60min`, single-subsystem, single-file, no product/UX decision).
