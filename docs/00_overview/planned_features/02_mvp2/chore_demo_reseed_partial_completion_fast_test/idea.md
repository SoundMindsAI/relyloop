# chore_demo_reseed_partial_completion_fast_test — a fast test for the reseed partial-completion path

**Date:** 2026-06-01
**Status:** Idea — tangential discovery during `infra_solr_ci_readiness` Story 1.2 implementation
**Priority:** P2 — the behavior IS covered (heavy-lane integration test), just not by a fast test; no felt incident, but the new partial-completion path is the feature's headline behavior and rides entirely on a slow, OpenAI-dependent test.
**Origin:** `infra_solr_ci_readiness` Epic 1 implementation (PR for `feature/infra-solr-ci-readiness`). Surfaced in the GPT-5.5 phase-gate review (Finding 5) and the post-impl tangential sweep.
**Depends on:** `infra_solr_ci_readiness` Phase 1 merged.

## Problem

`infra_solr_ci_readiness` made the demo reseed engine-tolerant: when an engine is
unreachable, its scenario is skipped, the reseed completes with `status="complete"`
and a non-empty `scenarios_skipped`, and a single `demo_reseed_partial_completion_engines_unreachable`
WARN fires (AC-1 / AC-7). The fast layers cover the building blocks:

- `is_engine_reachable` + `snapshot_engine_reachability` (unit)
- `AllEnginesUnreachableError` + `_is_all_engines_unreachable` verdict (unit)
- worker `_build_failed_status` mapping (unit)
- the **all-engines-unreachable** orchestrator path (unit — everything skips, no seed I/O)

But the **partial-completion** end-to-end path — ES + OpenSearch scenarios actually
seed, Solr skips, `scenarios_skipped == ["acme-kb-docs-solr"]`, `status="complete"`,
exactly one summary WARN — is only asserted by the heavy-lane
`test_demo_seeding_ubi_full.py`, which:

- requires the full stack (API at :8000 + ES + OpenSearch + a live OpenAI key), and
- runs 13–19 minutes.

So the feature's headline behavior (AC-7 WARN, partial-skip accounting against the
real seed path) has no fast signal. A regression in the skip accumulation or the
WARN would only surface in the slow lane.

## Proposed capabilities

### A fast partial-completion integration (or heavily-mocked) test

A test that drives `reseed_demo_state` with `is_engine_reachable` monkeypatched so
only Solr is unreachable, and the ES/OS seed path mocked enough to complete without
a live engine/API/OpenAI, asserting:

- `scenarios_skipped == ["acme-kb-docs-solr"]`
- `status` ends `complete` (not failed)
- exactly one `demo_reseed_partial_completion_engines_unreachable` WARN (via `caplog`)
- AC-3: a reachable scenario that fails mid-seed stays a generic `DemoSeedingError`
  (NOT added to `scenarios_skipped`)

The hard part is the seed path: `reseed_demo_state` inlines a lot (engine PUT/collection-create,
`api_client` cluster/template/query-set/queries/judgments/seed-completed-study, UBI synth).
Options: (a) a Postgres-only integration test with `api_client`/`engine_client` mocked to
return canned success shapes; (b) extract the per-scenario seed body into a seam that can
be stubbed; (c) a `respx`/`httpx-mock` layer over both clients.

## Scope signals

- **Backend:** test-only (+ possibly a small seam-extraction refactor in `demo_seeding.py`).
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.

## Why deferred

Mocking the full inline seed path (or extracting a seam) is a real test-infra
investment (>60 min, touches the orchestrator's structure) and is out of scope for
the Phase-1 unblock PR, whose intent is narrowly to make `pr.yml`'s backend job green.
The behavior is not unverified — it's covered by the heavy-lane test — so this is a
test-speed/robustness improvement, not a correctness gap.

## Relationship to other work

- Direct follow-on to `infra_solr_ci_readiness` (Phase 1).
- Overlaps with `chore_demo_seeding_integration_tests_rewrite` (already in `02_mvp2/`),
  which is rewriting the demo-seeding integration tests — the fast partial-completion
  test could land as part of that rewrite rather than standalone. Coordinate before
  picking up.
