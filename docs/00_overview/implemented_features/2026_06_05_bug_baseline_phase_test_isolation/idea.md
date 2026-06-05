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
the `DATABASE_URL_FILE` / `POSTGRES_PASSWORD_FILE` env and these tests
free-ride on that side effect.

**Root cause confirmed (2026-06-02 idea-preflight, verified against the
live tree):** there are two cooperating defects:

1. **Test-isolation leak (the trigger).**
   `backend/tests/unit/test_main_lifespan.py:45-46` calls
   `os.environ.setdefault("DATABASE_URL_FILE", ...)` +
   `os.environ.setdefault("POSTGRES_PASSWORD_FILE", ...)` at **module
   level** (collection time), pointing both at valid stub files in a
   `tempfile.mkdtemp()` dir. Because it uses raw `os.environ.setdefault`
   (NOT `monkeypatch.setenv`), the vars are **never reverted** — they
   persist for the entire pytest process. The module-level comment at
   `test_main_lifespan.py:32-37` is wrong: it claims "the stubs here only
   apply during this module's collection / first call," but `setdefault`
   leaks process-wide. The autouse `_clear_settings_caches` fixture
   (`backend/tests/conftest.py:39-51`) clears the `get_settings` lru_cache
   between tests but does **not** touch `os.environ`, so the leaked env
   vars survive. In the full `backend/tests/unit/` run, `test_main_lifespan.py`
   is collected alphabetically before `workers/`, so by the time the
   baseline-wait tests run, `os.environ` already has the two `*_FILE`
   vars → `Settings()` constructs cleanly. In isolation they're absent →
   `Settings()` raises `ValidationError`.

2. **Production code reads settings it doesn't need (the latent
   fragility).** `_compute_baseline_wait_s`
   (`backend/workers/orchestrator.py:467-474`) calls `get_settings()`
   **unconditionally** on line 469, even though it only needs
   `settings.studies_default_timeout_s` as a fallback when
   `study.config["trial_timeout_s"]` is absent (line 470:
   `study.config.get("trial_timeout_s") or settings.studies_default_timeout_s`).
   The three failing tests all pass an explicit `trial_timeout_s`, so they
   should never touch settings at all — but the eager read forces a
   `Settings()` construction regardless. (Confirmed: the fourth test,
   `test_missing_trial_timeout_uses_settings_default`, passes in isolation
   precisely because it `monkeypatch.setattr`s `orch.get_settings`.)

Reproduced in isolation: `3 failed, 1 passed`. Combined with
`test_main_lifespan.py` first: `9 passed`. The traceback dies at
`backend/workers/orchestrator.py:469: settings = get_settings()` →
`backend/app/core/settings.py:425` → pydantic `ValidationError`.

## Why it matters

A unit test that only passes via suite-ordering is a latent flake: any
re-sharding, `-p no:randomly` change, or `pytest <single-file>` invocation
re-surfaces the failure. Unit tests must be hermetic (the testing.md
convention: "No DB fixtures; `monkeypatch` for env / module-level state").

## Proposed fix

Two-layer fix (the production lazy-settings change is the durable one; the
autouse test fixture is the hermetic-isolation belt-and-suspenders):

1. **Make `_compute_baseline_wait_s` lazy.** Read settings only when the
   fallback is actually needed — i.e. when `study.config` has no
   `trial_timeout_s`. Today's line 470 (`study.config.get("trial_timeout_s")
   or settings.studies_default_timeout_s`) reads `get_settings()` eagerly
   on line 469 regardless. Restructure so the `get_settings()` call is
   guarded behind the missing-key branch. This makes the three explicit-
   timeout tests genuinely settings-free and removes the import-graph
   coupling for them.
2. **Add an autouse env fixture to `test_orchestrator_baseline_phase.py`**
   that seeds `DATABASE_URL_FILE` + `POSTGRES_PASSWORD_FILE` via
   `monkeypatch.setenv` + `get_settings.cache_clear()`, mirroring the
   canonical precedent at
   `backend/tests/unit/workers/test_poll_cron_kwargs.py:34-55`
   (`_settings_env_and_restore`). This keeps the module hermetic even for
   the `test_missing_trial_timeout_uses_settings_default` path (which
   constructs a real `Settings` after monkeypatching the timeout) and any
   future test in the module that legitimately needs settings.

   Note: the stale precedent `test_register_webhook_worker.py::_relyloop_base_url`
   cited in an earlier draft does **not** exist in the tree — the real
   precedent is `test_poll_cron_kwargs.py` (corrected during idea-preflight).
3. Verify with `.venv/bin/python -m pytest
   backend/tests/unit/workers/test_orchestrator_baseline_phase.py -p no:randomly`
   in isolation (must be all-green standalone), then the full
   `backend/tests/unit/` suite (must stay green).

**Out of scope (do NOT fix here):** the `os.environ.setdefault` leak in
`test_main_lifespan.py:45-46` is the *upstream* trigger, but fixing it
(switching to `monkeypatch.setenv` or a session-scoped fixture) is a
separate test-hygiene change in an unrelated module that touches app-
startup lifespan testing. The defect this bug fixes is that
`test_orchestrator_baseline_phase.py` *depends* on that leak; making the
baseline-wait tests hermetic is the correct, minimal fix and does not
require touching the lifespan test. If the lifespan leak warrants its own
cleanup it should be a separate `chore_` idea (a one-line
`monkeypatch`-vs-`setdefault` swap would, however, retroactively break any
*other* module silently free-riding on the same leak — so it must be
handled deliberately, not as a drive-by).

## Scope signals

- Backend change: one lazy-settings tweak in
  `backend/workers/orchestrator.py` (`_compute_baseline_wait_s`) + one
  autouse fixture + one regression assertion in
  `backend/tests/unit/workers/test_orchestrator_baseline_phase.py`.
- No migration, no frontend, no API surface, no product decision.
- No `audit_log` impact (pure helper + test hygiene; no state mutation).
