# Idea — `bug_digest_param_importance_seam`

**Date:** 2026-05-11
**Status:** Idea (deferred from `feat_digest_proposal` Story 4.2; tracked because the test was marked `xfail` rather than fixed inline)

## Origin

Surfaced during the `feat_digest_proposal` PR #41 CI run. The
integration test
[`backend/tests/integration/test_digest_parameter_importance.py`](../../../../backend/tests/integration/test_digest_parameter_importance.py)
fails in CI's hermetic service-container Postgres with `parameter_importance
== {}` despite the test fixture having called `optuna_study.tell(t,
values=...)` for 12 trials in a fresh `optuna_study` handle. The worker
loads a SEPARATELY-constructed `optuna_study` via
`get_or_create_study(...)` and `optuna.importance.get_param_importances`
returns `{}` (the worker's defense-in-depth try/except catches the
underlying `ValueError "No trials are completed yet."`).

## Problem

The test fixture builds its own `RDBStorage` via `build_storage(...)`,
constructs sampler/pruner with `seed=42`, and calls `tell()` against THAT
handle. The worker independently calls `build_storage(...)` (when
`ctx["optuna_storage"]` is absent — as in this test) and
`get_or_create_study(load_if_exists=True, ...)` with sampler/pruner
re-built from `study.config` (no seed). The two handles should converge
on the same Optuna RDB row (same `optuna_study_name`) and the worker
should see the fixture's tells… but in CI it doesn't.

Hypotheses, in order of likelihood:

1. **Engine / pool isolation**: each `build_storage` creates a new
   SQLAlchemy sync engine. Optuna's `RDBStorage` may cache trial state
   in-memory per-engine and the worker's engine never re-reads the
   committed-but-uncached rows.
2. **Sampler/pruner mismatch**: the test creates with `seed=42` but
   `study.config` is `{"max_trials": 100, "parallelism": 4, "sampler":
   "tpe"}` — no seed. `load_if_exists=True` should preserve the existing
   tells regardless, but Optuna may invalidate the cache when the
   sampler differs.
3. **Schema isolation**: Optuna's `RDBStorage` uses
   `options=-csearch_path=optuna` per `_compose_storage_url`. Both
   handles should land in the same schema; verify this in CI.

## Why deferred

AC-7 ("parameter_importance contains entries for every continuous
param") is covered at a SMALLER granularity by
[`test_digest_generate.py`](../../../../backend/tests/integration/test_digest_generate.py)
which asserts `digest.parameter_importance is not None` in the happy
path. The xfail-marked dedicated test is more rigorous (asserts the key
set + sum-to-1.0) but its fixture seam needs work that's beyond the
scope of the digest worker shipping. The bug exists in the
INTEGRATION-TEST FIXTURE LAYER, not in the worker code.

## Scope signals

- **Backend:** no production-code change expected.
- **Tests:** rewrite `_seed_trials()` to use the worker's eventual
  storage handle (parameterize via fixture or pass the storage through
  ctx). Or use Optuna's `study.add_trials([FrozenTrial(...)])` to bypass
  the ask/tell handle issue entirely.
- **Config:** no.

## Dependencies

- `feat_digest_proposal` (merged via PR #41) — this test ships with that
  feature in `xfail` state.
