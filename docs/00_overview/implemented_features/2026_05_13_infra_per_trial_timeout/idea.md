# infra — wire `trial_timeout_s` into the adapter call inside `run_trial`

**Date:** 2026-05-10
**Status:** Idea (deferred from `feat_study_lifecycle` Phase 2 / PR #25 GPT-5.5 review cycle 2)
**Origin:** GPT-5.5 final-review cycle 2 finding C2-F1 — the cycle-1
attempted fix passed `_job_timeout=trial_timeout_s` to
`ArqRedis.enqueue_job(...)`, but Arq doesn't recognize that kwarg
(supported: `_job_id`, `_queue_name`, `_defer_until`, `_defer_by`,
`_expires`, `_job_try`). It would be serialized as a function kwarg to
`run_trial` and fail at dispatch.

## Problem

`Settings.studies_default_timeout_s` (Story 1.5) is defined but never
consumed at runtime. The intended semantic is: when
`studies.config.trial_timeout_s` is absent, the worker should still
bound the engine query at the env-default timeout to prevent a hung
trial from monopolizing a worker slot indefinitely.

## Proposed fix

Two options:

1. **Adapter-call timeout (preferred, smaller surface)**:
   `backend/workers/trials.py` resolves `trial_timeout_s` from
   `study.config.trial_timeout_s` OR `Settings.studies_default_timeout_s`,
   and passes it as `adapter.search_batch(..., timeout=trial_timeout_s)`.
   The `SearchAdapter` Protocol already documents a `timeout` parameter
   on `search_batch`. This is the path of least resistance.

2. **Function-level Arq timeout**: register `run_trial` with
   `arq.func(run_trial, timeout=N)` where `N` is a generous upper bound
   (e.g., 3600s). Per-study override would still be impossible without
   wrapping the function body in `asyncio.wait_for(...)`.

Recommended: option 1 + option 2's generous upper bound on the
function-level Arq timeout (defense-in-depth).

## Test plan

* Unit: parametrize `trial_timeout_s` over (None, 30, 600); assert
  `adapter.search_batch` is called with the resolved value (env default
  when None).
* Integration: stub adapter that sleeps longer than `trial_timeout_s`;
  assert the trial transitions to `failed` with `error` containing
  "timeout".

## Scope signals

* Backend: yes (`run_trial` worker).
* Frontend: no.
* Migration: no.
* Config: no (env var already shipped).

## Why this isn't a blocker today

Phase 2 ships the env-var + settings field; the orchestrator resolves
the value at study start. The remaining wire is a one-line change in
`run_trial` (after the per-trial timing model is finalized — see
`run_trial`'s `duration_ms` accounting). Tracked here so it isn't
forgotten when the operator first reports a hung trial.
