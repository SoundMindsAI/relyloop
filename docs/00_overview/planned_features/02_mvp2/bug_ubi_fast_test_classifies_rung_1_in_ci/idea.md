# UBI fast-lane integration test classifies rung_1 in CI (expected rung_3)

**Date:** 2026-07-10
**Status:** Idea — surfaced during the 2026-07-10 security-audit PR (#610) CI watch; failure is pre-existing and unrelated to that PR's diff
**Priority:** P2
**Origin:** `backend/tests/integration/test_demo_seeding_ubi_fast.py::test_synthetic_ubi_seed_round_trip_hits_rung_3` fails consistently in the `pr.yml` backend (contract + integration) job.
**Depends on:** A running Elasticsearch service container / local stack to reproduce (this is why it can't be fixed CI-blind).

## Problem

The fast-lane UBI test seeds 640 synthetic UBI events into Elasticsearch and
then classifies the readiness rung. The **write** succeeds — the in-test
`assert event_count == 640` (test line 183) passes — but the subsequent
`classify_rung` read-back returns `rung_1` instead of the expected `rung_3`:

```
AssertionError: expected rung_3 after seeding 640 events for 'products-fasttest';
got 'rung_1'. Generator volume math or classifier thresholds drifted —
see backend/app/services/ubi_readiness.py.
```

It is **not** a write-refresh race: `seed_synthetic_ubi` already bulk-writes
with `params={"refresh": "wait_for"}` (`backend/app/services/demo_ubi_seed.py:347`),
so the docs are searchable when the writer returns. So the read-back
under-count points to one of:

1. `classify_rung`'s aggregation filter (the `query_set_query_ids` / `target`
   application filter passed at test lines 204-211) not matching the docs
   that `seed_synthetic_ubi` actually stamped, or
2. a threshold in `backend/app/services/ubi_readiness.py` that no longer lines
   up with the generator's rung_3 volume math (560 impressions + 40 clicks +
   40 dwells = 640), or
3. the classifier reading a different index/time-window than the seed writes.

The test + `ubi_readiness.py` have been code-stable for ~6 weeks (last touched
PR #348), and the failure reproduces across re-runs — so it is a persistent
condition, not a flake, and not caused by any recent merge.

Note: a **sibling** integration test in the same job
(`test_documents_endpoints.py:628`) skips with `CLUSTER_UNREACHABLE — Temporary
failure in name resolution`, so the CI ES service container's Compose-alias DNS
is also intermittently unhealthy in these runs. Rule out engine reachability
before assuming a classifier bug: if the aggregation query silently returns 0
hits because the adapter couldn't reach ES at read time, that also yields
`rung_1`.

## Proposed capabilities

### Diagnose and fix the read-back under-count

- Reproduce locally against a real ES (`make up`, then run the single test).
- Instrument `classify_rung` to log the raw aggregation hit count vs. the
  seeded 640; determine whether it's a filter mismatch, a threshold, or an
  engine-reachability read failure.
- Fix at the identified layer + keep the existing `event_count == 640`
  write-side assertion.

## Scope signals

- **Backend:** `backend/app/services/ubi_readiness.py`,
  `backend/app/services/demo_ubi_seed.py`,
  `backend/tests/integration/test_demo_seeding_ubi_fast.py`.
- **Frontend:** none.
- **Migration:** none expected.
- **Config:** none.
- **Audit events:** N/A.

## Why deferred (not fixed inline in PR #610)

PR #610 is a security-hardening sweep; this failure is in an unrelated
subsystem (UBI demo seeding), the code path is untouched by that PR's diff, and
diagnosing it needs a **running ES stack** to distinguish a classifier bug from
an engine-reachability read failure — a CI-blind fix would be a guess. Per the
CLAUDE.md inline-vs-idea rubric (separate subsystem + can't verify without a
local stack), this is captured rather than force-fixed.

## Relationship to other work

Adjacent to the deferred `chore_demo_seeding_integration_tests_rewrite`
(state.md: "blocked on a local stack for safe CI-blind validation") — same
root constraint. Fold this diagnosis into that rewrite if picked up together.
