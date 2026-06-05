# chore_demo_reseed_partial_completion_fast_test — a fast test for the reseed partial-completion path

**Date:** 2026-06-01
**Status:** Idea — tangential discovery during `infra_solr_ci_readiness` Story 1.2 implementation
**Priority:** P2 — the behavior IS covered (heavy-lane integration test), just not by a fast test; no felt incident, but the new partial-completion path is the feature's headline behavior and rides entirely on a slow, OpenAI-dependent test.
**Origin:** `infra_solr_ci_readiness` Epic 1 implementation (PR for `feature/infra-solr-ci-readiness`). Surfaced in the GPT-5.5 phase-gate review (Finding 5) and the post-impl tangential sweep.
**Depends on:** `infra_solr_ci_readiness` Phase 1 merged.

> **PREFLIGHT (2026-06-05).** Live-codebase audit: all concrete claims verified.
> - `reseed_demo_state` at [`demo_seeding.py:1442`](../../../../backend/app/services/demo_seeding.py); `is_engine_reachable` :446; `snapshot_engine_reachability` :488; `AllEnginesUnreachableError` :210 / `_is_all_engines_unreachable` :232; worker `_build_failed_status` at [`demo_reseed.py:64`](../../../../backend/workers/demo_reseed.py); the `demo_reseed_partial_completion_engines_unreachable` WARN at `demo_seeding.py:2001`; `scenarios_skipped.append(slug)` at :1583; the Solr slug `acme-kb-docs-solr` confirmed in `SCENARIOS`. Existing fast coverage: [`test_demo_seeding_partial_completion.py`](../../../../backend/tests/unit/services/test_demo_seeding_partial_completion.py) (building blocks); the end-to-end partial path only in heavy-lane [`test_demo_seeding_ubi_full.py:144`](../../../../backend/tests/integration/test_demo_seeding_ubi_full.py).
> - **Local verifiability:** `.venv/bin/pytest` is present and the chosen approach is a pure unit test (no DB, no engines, no OpenAI), so it runs offline before push — no CI-blind risk.
> - **DESIGN FORK LOCKED → (b′) monkeypatch the module-level I/O helpers, NOT a seam extraction and NOT httpx-URL routing.** The per-scenario seed body is a chained sequence of module-level `async def`s in `demo_seeding.py` (`_post` :?, `_get`, `_put` :580, `_seed_real_study_for_scenario` :965, `_seed_rich_scenario` :1123, `_seed_solr_scenario` :657, `ensure_ubi_indices` / `fabricate_ubi_for_scenario` / `seed_synthetic_ubi`). The test `monkeypatch.setattr`s these to canned-success (returning the exact shapes the body consumes — e.g. `_post` cluster/template/qset/jlist → dicts with the `id` keys the body reads), plus `is_engine_reachable` (Solr→False, ES/OS→True), plus an `AsyncMock` `db` (the body only does one TRUNCATE + commit). This avoids touching the orchestrator's structure — so it does NOT conflict with the deferred `chore_demo_seeding_integration_tests_rewrite`, and keeps the test a pure unit. Rejected: (a) full `httpx.MockTransport` URL-routing over both clients (fragile, must enumerate every URL); (c) Postgres-only integration (needs a real DB in CI for no extra signal — the body delegates all persistence through `api_client`, which is mocked anyway).
> - **Coordination:** overlaps with the deferred `chore_demo_seeding_integration_tests_rewrite` — proceed **standalone now** (the rewrite is deferred pending a local stack; this focused unit test is small and the rewrite can absorb/supersede it later).
> - **Route:** `chore_` + just-locked design fork + bounded test-only backend scope → `/bug-fix --ship` (focused `bug_fix.md` locking the helper-monkeypatch approach, then `/impl-execute --ad-hoc`).

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
~~Options: (a) a Postgres-only integration test with `api_client`/`engine_client` mocked to
return canned success shapes; (b) extract the per-scenario seed body into a seam that can
be stubbed; (c) a `respx`/`httpx-mock` layer over both clients.~~

**LOCKED at preflight → (b′): monkeypatch the module-level I/O helpers** (`_post`/`_get`/`_put`/
`_seed_real_study_for_scenario`/`_seed_rich_scenario`/`_seed_solr_scenario`/`ensure_ubi_indices`/
`fabricate_ubi_for_scenario`/`seed_synthetic_ubi`) to canned-success + `is_engine_reachable`
(Solr→False) + `AsyncMock` db. Pure unit test, no seam extraction, no orchestrator-structure
change. See the PREFLIGHT block above for the full rationale + rejected alternatives.

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
