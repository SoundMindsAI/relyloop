# Study lifecycle debugging runbook

> Operator-facing reference for inspecting a running / stuck / failed
> study, force-cancelling a study, purging a study, and resolving
> orchestrator-loop errors. Lands with `feat_study_lifecycle` Phase 2.

## Background

A **study** in RelyLoop is a single Optuna-driven optimization run
against one (cluster, query template, query set, judgment list) tuple.
Its lifecycle is owned by **two cooperating processes**:

1. The **API** (FastAPI) creates the `studies` row with
   `status='queued'` and enqueues `start_study(study_id)` to the Arq
   queue (`POST /api/v1/studies`).
2. The **worker** (Arq) picks up the job and runs the orchestrator
   loop in `backend/workers/orchestrator.py`. The orchestrator:
   - Transitions `queued → running` via
     `services.study_state.start_study` (FR-7 guarded).
   - Polls every 1s: aggregates trials, checks stop conditions
     (`max_trials` / `time_budget_min`), checks for 5 consecutive
     failures (AC-5), and replenishes open Optuna trial slots up to
     `parallelism`.
   - On stop-condition fire, calls
     `services.study_state.complete_study` AND inserts a
     `proposals.status='pending'` row in the same transaction
     (durable digest handoff).

Every `studies.status` change MUST go through the service-layer
mutators (`start_study` / `cancel_study` / `complete_study` /
`fail_study`); a SQLAlchemy `before_flush` event listener raises
`StudyStateProtectionError` if you bypass it (FR-7 / AC-6).

Legal transitions (spec §9 state diagram):

```
queued    → running | cancelled
running   → completed | cancelled | failed
completed → (terminal)
cancelled → (terminal)
failed    → (terminal)
```

## Connect + inspect a study row

From the API container so credentials are mounted:

```bash
docker compose exec -T api bash -c '
  PGPASSWORD="$(cat $POSTGRES_PASSWORD_FILE)" \
  psql -U relyloop -d relyloop -h postgres \
    -c "SELECT id, name, status, failed_reason, started_at, completed_at \
        FROM studies ORDER BY created_at DESC LIMIT 10;"
'
```

For a single study + its trial summary:

```bash
docker compose exec -T api bash -c '
  PGPASSWORD="$(cat $POSTGRES_PASSWORD_FILE)" \
  psql -U relyloop -d relyloop -h postgres \
    -c "SELECT s.id, s.status, s.best_metric, \
               COUNT(*) FILTER (WHERE t.status = '\''complete'\'') AS complete, \
               COUNT(*) FILTER (WHERE t.status = '\''failed'\'')   AS failed, \
               COUNT(*) FILTER (WHERE t.status = '\''pruned'\'')   AS pruned \
        FROM studies s LEFT JOIN trials t ON t.study_id = s.id \
        WHERE s.id = '\''<study-id>'\'' \
        GROUP BY s.id;"
'
```

## Find a stuck study (orchestrator died mid-loop)

A "stuck" study is one with `status='running'` whose worker has died.
The worker's `on_startup` hook is supposed to resume it via the
`SELECT id FROM studies WHERE status='running'` sweep + `enqueue_job
('resume_study', sid)`. If a study is stuck and not being picked up:

1. Confirm the worker is running:
   ```bash
   docker compose ps worker
   docker compose logs --tail=200 worker | grep resume_enqueued
   ```
   You should see one `resume_enqueued` log per running study at boot.
2. If the worker is up but no resume log appears, check
   `list_running_study_ids` returned the study:
   ```bash
   docker compose exec -T api bash -c '
     PGPASSWORD="$(cat $POSTGRES_PASSWORD_FILE)" \
     psql -U relyloop -d relyloop -h postgres \
       -c "SELECT id, name FROM studies WHERE status = '\''running'\'';"
   '
   ```
3. If the row is there but the resume didn't fire, restart the worker:
   ```bash
   docker compose restart worker
   ```
   The `on_startup` sweep runs every cold boot — restarting it
   re-enqueues every running study.

## Force-cancel a study (escape hatch)

The HTTP cancel surface (`POST /api/v1/studies/{id}/cancel`) is the
documented operator path. If for some reason the API isn't responsive,
you can call the service layer directly from a Python REPL inside the
API container. **Never UPDATE `studies.status` via raw SQL** — the
FR-7 protection listener will raise `StudyStateProtectionError` if the
mutation flows through SQLAlchemy, but the more general failure mode
is that downstream invariants (e.g., the `completed_at` timestamp,
the durable digest handoff) won't be set.

```bash
docker compose exec -T api python -c '
import asyncio
from backend.app.db.session import get_session_factory
from backend.app.services import study_state

async def _go(study_id):
    factory = get_session_factory()
    async with factory() as db:
        await study_state.cancel_study(db, study_id)
        await db.commit()

asyncio.run(_go("<study-id>"))
'
```

The orchestrator detects the new status on its next 1s poll tick and
drains in-flight trials (up to 30s) before exiting.

## Purge a study

Cascade-deletes the study row, its trials (FK CASCADE), and its
proposals (handled by the DELETE since `proposals.study_id` is
nullable):

```bash
docker compose exec -T api bash -c '
  PGPASSWORD="$(cat $POSTGRES_PASSWORD_FILE)" \
  psql -U relyloop -d relyloop -h postgres \
    -c "DELETE FROM proposals WHERE study_id = '\''<study-id>'\''; \
        DELETE FROM studies   WHERE id       = '\''<study-id>'\'';"
'
```

Note: this also purges the Optuna RDB rows for the study because the
Optuna study name is `str(studies.id)` and Optuna's storage is
namespaced by study name. To purge the Optuna side explicitly:

```bash
docker compose exec -T api python -c '
from backend.app.eval.optuna_runtime import build_storage
from backend.app.core.settings import get_settings
storage = build_storage(get_settings().database_url)
storage.delete_study(storage.get_study_id_from_name("<study-id>"))
'
```

## Common errors

### `StudyStateProtectionError: direct UPDATE of studies.status outside the service layer is forbidden`

Some code path bypassed `services.study_state.*` and tried to mutate
`Study.status` directly. Find the offender via the stack trace; route
the mutation through the service layer.

### `InvalidStateTransition: illegal transition: 'completed' → 'cancelled'`

Terminal states (`completed` / `cancelled` / `failed`) are terminal —
you can't cancel a completed study. Re-run the study by creating a
new one.

### `failed_reason: '5 consecutive trial failures'` (AC-5)

The orchestrator detected 5 consecutive `failed` trials and gave up.
Common causes:

- Cluster unreachable — check
  `/api/v1/clusters/{id}` health and the cluster registration.
- Judgment list disappeared — check
  `SELECT id FROM judgment_lists WHERE id = '...'`.
- Search template invalid against current cluster schema — try
  `POST /api/v1/clusters/{id}/run_query` with the rendered DSL.

After fixing the upstream cause, create a fresh study; the failed
one is terminal.

### Orchestrator log: `replenish_lock_contention`

Two `start_study` jobs are running for the same study (e.g., the
on_startup resume sweep raced with an Arq retry). The losers skip
their tick and retry in 1s; this is benign and self-recovering. If
the log persists for >1 minute, restart the worker to clear stale
job entries.

## See also

- [`docs/01_architecture/optimization.md`](../01_architecture/optimization.md) — Optuna sampler / pruner contract.
- [`docs/03_runbooks/optuna-debugging.md`](optuna-debugging.md) — inspect Optuna RDB tables; replay a single trial.
- [`docs/01_architecture/data-model.md`](../01_architecture/data-model.md) — `studies`, `trials`, `proposals` schema.
