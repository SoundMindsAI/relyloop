# bug_worker_optuna_init_race

## Status

Idea — captured during `chore_tutorial_polish` Story 3.2 smoke-test CI
verification (PR #64, round 3). Pre-existing bug masked by typical local
operator workflows.

## Origin

Surfaced 2026-05-12 / 13 when the new `smoke-test` GHA job ran `make up`
end-to-end on a Linux runner for the first time and the smoke test timed
out at "judgment generation did not complete within 120s". Worker logs
showed:

```
worker-1 | 01:32:31: Starting worker for 8 functions: run_trial, …
worker-1 | psycopg2.errors.InvalidSchemaName: no schema has been selected to create in
worker-1 | sqlalchemy.exc.ProgrammingError: (psycopg2.errors.InvalidSchemaName) no schema has been selected to create in
worker-1 | [SQL: CREATE TYPE studydirection AS ENUM ('NOT_SET', 'MINIMIZE', 'MAXIMIZE')]
```

…and then the worker stayed dead. Smoke test's POST to
`/api/v1/judgments/generate` enqueued the job but no worker consumed it.

## Problem

Compose ordering:

```
postgres + redis + ES + OpenSearch  →  api (waits for postgres healthy)
                                         ↓
                                     worker (waits for api healthy)
```

`api` reaches healthy quickly (just needs `/healthz` to respond, which
doesn't require business tables). `worker` then starts and Optuna's
`OptunaStorage` connect-and-`CREATE TYPE` flow fires before `make migrate`
ever runs. Postgres has the database `relyloop` but **no `public` schema
yet** (Optuna's `CREATE TYPE` defaults to `public`). Result:
`InvalidSchemaName: no schema has been selected to create in`.

The worker has no `restart` policy in `docker-compose.yml`, so once it
crashes it stays dead until something explicitly restarts it.

Why this hasn't been caught before:

- Local operators run `make up && make migrate` and don't immediately
  fire judgment-gen / studies. By the time they do, they're often on a
  fresh stack restart that reads the now-existing schema.
- `data/postgres` persists across `make down`/`make up`, so the schema
  exists from the second boot onward.
- Existing CI jobs (`backend`, `frontend`, `docker buildx`) don't run
  `make up` — they use service-container Postgres with their own
  migrations.

The new `smoke-test` job in PR #64 is the first CI job to run `make up`
end-to-end. It hit the bug immediately on a clean runner.

## Workaround

`chore_tutorial_polish` PR #64 inserts a
`docker compose restart worker` step in the smoke job after `make migrate`,
before the smoke test runs. Documented inline at
[`pr.yml`](../../../../.github/workflows/pr.yml).

## Why deferred

Real fix needs one of:

1. Make the worker tolerate Optuna `InvalidSchemaName` at startup —
   retry once after a delay, or defer the Optuna connection to first
   actual `run_trial` call instead of import time.
2. Add a `migration` init container that runs `alembic upgrade head` +
   `optuna_schema` between Postgres healthy and api/worker startup.
3. Add `restart: unless-stopped` to the worker service so a crash
   self-heals after migrations are applied (still racy on cold-boot
   timing).

All three change semantics that go beyond the chore_tutorial_polish
release polish scope. The CI workaround unblocks the smoke gate; the
proper fix should pick option 2 (init container) for determinism.

## How to verify the fix

1. Bring the stack down, delete the postgres volume:
   `make down && rm -rf ./data/postgres`.
2. `make up` — observe worker crash via `docker compose logs worker`.
3. Apply the chosen fix.
4. Re-run step 2 — worker stays healthy, `make migrate` succeeds, and
   `pytest backend/tests/smoke/test_tutorial_path.py` passes without
   needing a manual worker restart.

## Scope estimate

Small (option 3) to medium (options 1 or 2). Likely 1–2 stories under a
`bug_` pipeline.

## Related

- [`chore_tutorial_polish`](../chore_tutorial_polish/) — the consumer
  that surfaced this latent bug
- [`infra_optuna_eval`](../../../00_overview/implemented_features/2026_05_10_infra_optuna_eval/) —
  owns the Optuna RDB schema init
