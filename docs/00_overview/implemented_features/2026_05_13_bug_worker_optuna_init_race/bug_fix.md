# Bug fix — bug_worker_optuna_init_race

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/worker-optuna-init-race`
**Type:** bug fix — medium (Compose-shape change + regression test)
**Date:** 2026-05-13

## Problem

On a truly fresh stack (no `./data/postgres` volume), `docker compose up -d` starts the worker before `make migrate` runs. The worker's `on_startup` hook constructs Optuna's `RDBStorage`, which issues `CREATE TYPE studydirection AS ENUM (…)` against the `optuna` schema. The schema doesn't exist yet, so Postgres rejects with `psycopg2.errors.InvalidSchemaName: no schema has been selected to create in` and the worker exits. The worker has no `restart` policy, so it stays dead until something explicitly restarts it.

Local operators rarely see this because their `./data/postgres` volume persists across `make down`/`make up` cycles — the schema exists from the second boot onward. CI's new `smoke-test` job (chore_tutorial_polish PR #64) hit it immediately on a clean Linux runner; PR #64 worked around it with a post-migrate `docker compose restart worker` step.

## Reproduction

1. **Compose-shape contract test** (the regression guard for this fix):

   ```bash
   pytest backend/tests/unit/test_compose_deployment_shape.py -v
   ```

   On `main`: 6 failed (no `migrate` service, `api`/`worker` lack the dependency).
   On this branch: 6 passed.

2. **End-to-end via the CI smoke job** (the in-the-wild trigger):

   ```bash
   make down && rm -rf ./data/postgres
   make up
   docker compose logs worker | grep InvalidSchemaName  # fires on main; silent on the branch
   ```

   The pre-fix smoke job included `docker compose restart worker` after `make migrate`. The fix removes that workaround; CI staying green is the in-the-wild assertion.

## Root cause

- **Owning layer:** deployment topology (Compose orchestration).
- **Origin:** [`docker-compose.yml`](../../../../docker-compose.yml) — pre-fix worker `depends_on` only requires `postgres` healthy + `redis` healthy + `api` healthy. None of those gate on migrations having run.
- **Failure surface:** [`backend/workers/all.py:111-112`](../../../../backend/workers/all.py#L111-L112) — `on_startup` calls `build_storage()` which constructs Optuna's `RDBStorage`. Optuna's constructor issues DDL against the search-path-pinned `optuna` schema before any user code runs.
- **Why search-path pinning isn't enough:** [`backend/app/eval/optuna_runtime.py:32`](../../../../backend/app/eval/optuna_runtime.py#L32) sets `options=-csearch_path=optuna`, which routes DDL to the right schema — but the schema must already exist. `init_optuna_schema()` ([`backend/app/db/optuna_schema.py:26`](../../../../backend/app/db/optuna_schema.py#L26)) creates it idempotently, but only runs when `make migrate` is invoked, which is operator-driven and post-`up`.

The race is structural: Compose's only ordering primitive is `depends_on`, and there's no service the worker can depend on whose readiness implies "migrations have completed."

## Fix design (locked decisions)

1. **Init container for migrations** — add a `migrate` Compose service that runs `alembic upgrade head && python -m backend.app.db.optuna_schema` once at boot and exits. `api` and `worker` depend on it via `condition: service_completed_successfully`. Cites: idea.md "Why deferred" §1 explicitly recommends "Option 2 (init container) for determinism"; the pattern matches what the MVP3 production deploy will use. Compose v2.10+ supports `service_completed_successfully` (Aug 2022, well within current Docker Desktop / GHA runner versions).
2. **Reuse the api image** — same `relyloop/api:${RELYLOOP_GIT_SHA:-dev}` tag, same build context. No new Dockerfile, no additional `docker build` step in install.sh. The migrate command runs inside the existing image's entrypoint surface.
3. **`restart: "no"` on the migrate service** — init containers are one-shot. `unless-stopped` would re-run migrations after a clean exit on every Compose reboot.
4. **Keep `make migrate` as a manual target** — operators authoring a new revision via `make migrate-create` still need a way to apply it without bouncing the stack. The Makefile help block + `docs/03_runbooks/local-dev.md` document that `make migrate` is now optional at boot but useful for incremental dev.
5. **Do NOT add `restart: unless-stopped` to the worker** — defense-in-depth would mask future genuine worker crashes (idea option 3, explicitly rejected). The init container removes the original failure mode; any future worker crash is its own bug to investigate.
6. **Remove the CI workaround** — `.github/workflows/pr.yml` no longer needs the `docker compose restart worker` step after `make migrate`. The remaining `make migrate` invocation is preserved as a no-op re-run so the operator-facing target gets continuous exercise.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/test_compose_deployment_shape.py` | `migrate` service exists; runs `alembic upgrade head` + `optuna_schema`; depends on postgres-healthy; `restart: "no"`; both `api` and `worker` depend on `migrate` with `service_completed_successfully` |
| integration | (existing) `.github/workflows/pr.yml::smoke` | End-to-end: removes the post-migrate restart workaround. Stays green iff the init container actually unblocks the worker before the smoke test queues jobs |

The unit test fails 6× on `main` and passes 6× on the branch — verified.

## Rollout

- **Compose-only.** No migration, no schema change, no settings field, no code change to the application layer.
- **Documentation drift swept** in the same commit: `Makefile` help, `docs/03_runbooks/local-dev.md`, `docs/01_architecture/deployment.md` Compose snippet + daily-use table.
- **Operator action:** none. The `migrate` init container runs automatically on first `make up` after this lands. Existing installs (operators whose `./data/postgres` volume already has the schema) see the init container run alembic as a no-op + ensure the optuna schema exists (idempotent).

## Tangential observations

- The smoke job's `make migrate` invocation is now a no-op re-run. Keeping it exercises the operator-facing Makefile target and catches a regression where the target itself bit-rots; rephrased as a comment in `pr.yml`.
- `backend/app/db/optuna_schema.py:42` strips `+asyncpg` from the URL via `str.replace` — works for the only driver currently in use; would need extending if a future driver prefix lands. Out of scope for this fix; not capturing as a separate idea file because it's a one-line change someone can make when they actually need the second driver.
