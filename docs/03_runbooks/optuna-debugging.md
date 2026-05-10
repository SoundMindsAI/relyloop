# Optuna debugging runbook

> Operator-facing reference for inspecting RelyLoop's Optuna RDB tables,
> replaying a specific trial, and diagnosing stuck or orphan trials. Lands
> with `infra_optuna_eval` (the feature that wires the `run_trial` Arq job
> + Optuna `RDBStorage` against the app Postgres).

## Background

RelyLoop's optimization loop runs Optuna trials via the `run_trial` Arq
job. Optuna's state lives in Postgres under the **`optuna.*` schema** —
isolated from RelyLoop's `public.*` schema via the connection-time
`options=-csearch_path=optuna` flag (see
[`docs/01_architecture/optimization.md`](../01_architecture/optimization.md)
§"Optuna configuration"). Both schemas share the same Postgres instance
to keep operator setup simple.

The `run_trial` worker does **not** call `study.ask()` itself — Phase 2
of `feat_study_lifecycle`'s orchestrator pre-allocates the trial number
and populates `trial.params` before enqueueing. The worker loads the
in-flight trial via `study.trials[optuna_trial_number]` and proceeds
through render → search → score → tell → INSERT. See the
[`infra_optuna_eval` spec §11](../02_product/planned_features/infra_optuna_eval/feature_spec.md)
(or the implemented-features copy) for the full retry contract.

## Connect to Postgres + inspect Optuna's schema

From the API container (so the credentials file is mounted):

```bash
docker compose exec -T api bash -c '
  PGPASSWORD="$(cat $POSTGRES_PASSWORD_FILE)" \
  psql -U relyloop -d relyloop -h postgres \
    -c "\dn" \
    -c "\dt optuna.*"
'
```

Expected:

* `\dn` shows both `optuna` and `public` schemas.
* `\dt optuna.*` lists Optuna's internal tables (e.g. `optuna.studies`,
  `optuna.trials`, `optuna.trial_values`, `optuna.trial_params`).

If `\dt optuna.*` returns nothing, Optuna hasn't been touched yet — its
tables are created lazily on the first `RDBStorage` use. Boot the Arq
worker (`docker compose up worker`) and confirm the `WorkerSettings.on_startup`
hook ran successfully in the worker logs.

## Find a stuck or orphan trial

A "stuck" trial is one whose Optuna-side state is `RUNNING` but no
corresponding app-side `trials` row exists. This can happen if:

1. Phase 2's orchestrator allocated the trial via `study.ask()` but died
   before the enqueue commit (orchestrator failure — Phase 2 owns the
   reaper).
2. The worker died after `study.ask()` was loaded but before `study.tell()`
   (within-worker death — the next retry completes the SAME trial number).

To find orphan RUNNING trials in Optuna:

```sql
-- Run from psql against the Postgres directly:
SELECT s.study_name, t.trial_id, t.number, t.state, t.datetime_start
FROM optuna.trials t
JOIN optuna.studies s ON s.study_id = t.study_id
WHERE t.state = 'RUNNING'
  AND t.datetime_start < (NOW() - INTERVAL '15 minutes')
ORDER BY t.datetime_start ASC;
```

The 15-minute filter excludes trials that are legitimately in flight
right now. Optuna's `state` is stored as a string (`RUNNING`, `COMPLETE`,
`FAIL`, `PRUNED`).

To compare against the app side:

```sql
SELECT t.id, t.optuna_trial_number, t.status
FROM public.trials t
WHERE t.study_id = '<your-study-uuid>';
```

If an Optuna trial is COMPLETE (or FAIL/PRUNED) but the app side has no
corresponding row, the worker died between `study.tell()` and the INSERT.
Re-dispatching `run_trial(study_id, optuna_trial_number)` will trigger
spec §11 clause 1b reconciliation: the worker reads the terminal Optuna
state and reconstructs the app row without re-running search/score.

## Replay a specific trial

Replaying a trial is useful for:

* Reproducing a failure to gather logs.
* Forcing reconciliation after an out-of-band Optuna state change.

```bash
docker compose exec -T api python - <<'PY'
import asyncio
from backend.app.core.settings import get_settings
from backend.app.eval.optuna_runtime import build_storage
from backend.workers.trials import run_trial

storage = build_storage(get_settings().database_url)
ctx = {"optuna_storage": storage}
asyncio.run(run_trial(ctx, study_id="<study-uuid>", optuna_trial_number=<N>))
PY
```

The `ctx["optuna_storage"]` seed is required because the Arq `on_startup`
hook only runs when invoked via the worker entrypoint (`arq backend.workers.all.WorkerSettings`).
When you call `run_trial` directly from a Python REPL or CLI, you must
seed the storage yourself.

If the trial is already terminal in either the app `trials` table OR the
Optuna `optuna.trials` table, the worker's idempotency check / reconciliation
will detect it and short-circuit (no re-execution of search/score/tell).

## Diagnose a pruner false-positive

In MVP1 trials are single-step, so `MedianPruner` won't actually prune
anything mid-trial (pruning needs intermediate report points, which a
single-step trial doesn't have). If you see `status='pruned'` rows
unexpectedly, it's likely Optuna's behavior on a manual `study.tell(..., state=PRUNED)`
call, or a reconstruction of an Optuna-side PRUNED state.

To inspect pruner configuration on a study:

```python
docker compose exec -T api python - <<'PY'
from backend.app.core.settings import get_settings
from backend.app.eval.optuna_runtime import build_pruner, build_sampler, build_storage, get_or_create_study
import optuna
storage = build_storage(get_settings().database_url)
study = optuna.load_study(study_name="<study-uuid>", storage=storage)
print("pruner:", study.pruner.__class__.__name__)
print("sampler:", study.sampler.__class__.__name__)
PY
```

If the pruner is `NopPruner` but you expected `MedianPruner`, check the
study row's `config` dict in the app DB — spec §FR-2's auto-disable
safeguard fires when `max_trials < 50` AND the `pruner` key is absent
from `studies.config`. To force MedianPruner on a small study, the
operator must set `"pruner": "median"` explicitly in the config.

## Wipe & reseed Optuna for tests

For destructive test cleanup (CI ephemeral DBs handle this automatically;
follow the steps below ONLY in a dev environment):

```bash
docker compose exec -T api bash -c '
  PGPASSWORD="$(cat $POSTGRES_PASSWORD_FILE)" \
  psql -U relyloop -d relyloop -h postgres \
    -c "DROP SCHEMA IF EXISTS optuna CASCADE;" \
    -c "CREATE SCHEMA optuna;"
'
make migrate  # re-runs python -m backend.app.db.optuna_schema (idempotent)
```

The schema is recreated empty; Optuna's internal tables will be re-built
on the next `RDBStorage` use.

**Never drop the `optuna` schema in production.** Doing so loses every
study's optimization history.

## Related runbooks

* [`local-dev.md`](local-dev.md) — local stack lifecycle (`make up`,
  `make migrate`, `make reset`).
* [`cluster-registration.md`](cluster-registration.md) — adapter / cluster
  setup; trials depend on the registered cluster.

## Follow-ups

A periodic reaper for orphan RUNNING trials is tracked separately as
`infra_optuna_orphan_reaper` (filed under `docs/02_product/planned_features/`
when needed) — operationally tolerated for MVP1 per spec §11 "Operational
tolerance".
