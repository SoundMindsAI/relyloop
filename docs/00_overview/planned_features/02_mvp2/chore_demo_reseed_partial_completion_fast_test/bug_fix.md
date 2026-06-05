# Bug fix — chore_demo_reseed_partial_completion_fast_test

**Source idea:** [idea.md](./idea.md)
**Branch:** `chore/demo-reseed-partial-completion-fast-test`
**Type:** chore — test-robustness (medium; routed through /bug-fix per the preflight decision tree). Not a defect fix: a *guard* test for already-correct behavior.
**Date:** 2026-06-05

## Problem

`infra_solr_ci_readiness` made `reseed_demo_state` engine-tolerant — an unreachable engine's scenario is skipped, the reseed still finishes `status="complete"` with a non-empty `scenarios_skipped`, and exactly one `demo_reseed_partial_completion_engines_unreachable` WARN fires (AC-7). The building blocks have fast unit coverage, but the **end-to-end partial path** (ES + OS + rich seed actually complete, Solr skips) was asserted only by the heavy-lane `test_demo_seeding_ubi_full.py` (full stack + live OpenAI key, 13–19 min). A regression in the skip accounting or the WARN would only surface in the slow lane.

## Reproduction

This is a guard test for correct behavior, so the "fails on main" inverts: the new test PASSES against current correct code, and a mutation that breaks the partial-completion logic makes it FAIL. Verified load-bearing:

```bash
# Passes on current code:
.venv/bin/python -m pytest backend/tests/unit/services/test_demo_reseed_partial_completion_fast.py -q --no-cov
# Mutation (suppress the partial WARN: `if progress.scenarios_skipped:` -> `if False:`)
#   -> test_partial_completion_skips_only_solr_and_warns_once FAILS (len(partial_warns) 0 != 1).
```

## Root cause

N/A — no defect. The gap is a *missing fast guard* for the partial-completion control flow in `reseed_demo_state`.

- Owning layer: service — [`backend/app/services/demo_seeding.py:1442`](../../../../backend/app/services/demo_seeding.py) (`reseed_demo_state`); the guarded logic is the per-scenario reachability gate (:1578-1584), the rich-scenario gate (:1962-1972), the all-unreachable verdict (:1997), and the partial WARN (:1999-2006).

## Fix design (locked decisions)

1. **Approach (b′): monkeypatch demo_seeding's module-level I/O helpers, NOT an httpx-URL mock and NOT a seam extraction.** The per-scenario seed body is a chain of module-level `async def`s (`_post`/`_get`/`_put`/`_seed_real_study_for_scenario`/`_seed_rich_scenario`/`ensure_ubi_indices`/`seed_synthetic_ubi`/`fabricate_ubi_for_scenario`/`_poll_judgment_list_until_terminal`). The test `monkeypatch.setattr`s these to canned success, leaving the orchestrator's control flow real. Cites: keeps the orchestrator structure untouched → no conflict with the deferred `chore_demo_seeding_integration_tests_rewrite`; pure unit (no DB/engine/OpenAI) → locally verifiable. Rejected: (a) `httpx.MockTransport` URL routing (fragile, must enumerate every URL); (c) Postgres-only integration (needs a real DB in CI for no extra signal — persistence is delegated through the mocked `api_client`).
2. **`is_engine_reachable` → `engine_type != "solr"`** so only the Solr scenario skips. The Solr seed path (`_seed_solr_scenario`) is never reached, so it needs no mock.
3. **`db` is an `AsyncMock`** (the body only does TRUNCATE + study-rename `execute` + `commit`); the engine client's one direct call (Step 1b index DELETE) returns a tolerated 204.
4. **`_get` returns the union of all SCENARIOS' query texts** so each scenario's text-lookup resolves (the body raises `DemoSeedingError` on a missing text); extras are harmless (each scenario filters to its own).

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/services/test_demo_reseed_partial_completion_fast.py` | (1) only-Solr-down → `scenarios_skipped == ["acme-kb-docs-solr"]`, `status="complete"`, `scenarios_completed == 5`, exactly one partial WARN carrying the skip list; (2) AC-3 — a reachable scenario failing mid-seed raises a generic `DemoSeedingError` (not `AllEnginesUnreachableError`) and the slug is never added to `scenarios_skipped`. |

## Rollout

None — test-only change, no migration, no production diff.

## Tangential observations

None.
