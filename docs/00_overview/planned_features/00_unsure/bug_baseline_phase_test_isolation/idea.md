# bug_baseline_phase_test_isolation — baseline-phase unit tests depend on suite ordering

**Date:** 2026-05-29
**Status:** Idea — pre-existing bug surfaced during `feat_ubi_judgments` PR #317
**Origin:** feat_ubi_judgments PR #317 — while running a targeted subset of
`backend/tests/unit/workers/`, the `TestComputeBaselineWaitS` cases in
`test_orchestrator_baseline_phase.py` failed in isolation but pass in the
full `pytest backend/tests/unit/` run. Confirmed pre-existing by
re-running on a `git stash`-ed clean tree (same failure).
**Why deferred:** Not introduced by this PR; not in scope for the UBI
feature. Captured per the tangential-discoveries rule.
**Priority:** P2

## Problem

`backend/tests/unit/workers/test_orchestrator_baseline_phase.py::TestComputeBaselineWaitS::*`
fail when run in isolation with:

```
pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings
  database_url_file  Field required
  postgres_password_file  Field required
```

They pass when run as part of the full `backend/tests/unit/` suite. That
means a *different* unit test (run earlier in collection order) populates
the `DATABASE_URL_FILE` / `POSTGRES_PASSWORD_FILE` env (or seeds the
`get_settings` lru_cache) and these tests free-ride on that side effect.

Root cause is almost certainly a module-level `get_settings()` /
`Settings()` construction reachable from this test module's import graph
that isn't guarded by an env fixture (unlike the integration tests, which
all skip cleanly via `postgres_reachable()`).

## Why it matters

A unit test that only passes via suite-ordering is a latent flake: any
re-sharding, `-p no:randomly` change, or `pytest <single-file>` invocation
re-surfaces the failure. Unit tests must be hermetic (the testing.md
convention: "No DB fixtures; `monkeypatch` for env / module-level state").

## Proposed fix

1. Find the module-level `Settings()` / `get_settings()` call in the
   `test_orchestrator_baseline_phase.py` import graph (likely a worker
   module imported at test-module top level that reads settings at import
   time rather than call time).
2. Either defer the settings read to call time, or add an autouse fixture
   in the test module that seeds the `*_FILE` env + clears the settings
   cache (mirror `test_register_webhook_worker.py::_relyloop_base_url`).
3. Verify with `uv run pytest backend/tests/unit/workers/test_orchestrator_baseline_phase.py`
   in isolation.

## Scope signals

- Backend test-only change (+ possibly a lazy-settings tweak in the
  imported worker module).
- No migration, no frontend, no product decision.
