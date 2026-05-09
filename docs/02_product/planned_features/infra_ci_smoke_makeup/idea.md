# infra_ci_smoke_makeup — Idea

**Date:** 2026-05-09
**Status:** Idea — captured during `infra_foundation` PR #4 first-run testing
**Origin:** PR #4 (`infra_foundation`). The unit/integration/contract test layers all passed CI but five real bugs escaped to operator first-run testing on the maintainer's laptop:

1. **Stale `relyloop/api:dev` image** — `make up` doesn't auto-rebuild; container ran code missing `psycopg2-binary` (added to `pyproject.toml` after the image was last built). `/healthz` returned 500. *Fixed in commit `5bd59b6`* (install.sh now runs `docker compose build` before `up`).
2. **Stale `secrets/database_url` from earlier debugging** — install.sh's `[[ ! -s ./secrets/database_url ]]` idempotency guard kept a stub URL without the `+asyncpg` driver prefix → SQLAlchemy fell back to psycopg2 dialect → `ModuleNotFoundError` at `/healthz`. *Fixed in commit `5bd59b6`* (install.sh now validates the prefix and re-templates if missing).
3. **`make migrate` and `make migrate-create` ran from the host** without `DATABASE_URL_FILE` env vars set, and Postgres is intentionally not host-exposed. *Fixed in commit `3fd5045`* (both targets now `docker compose exec` into the api container).
4. **`make test-integration` migration tests** failed with the same root cause as #3 (host shell can't reach Postgres). *Fixed in commit `3fd5045`* (module-level `pytest.mark.skipif` that gates on env var presence + TCP reachability).
5. **`make migrate-create` ran inside the container but** (a) generated a hashed rev-id instead of the sequential `0002` numeric per CLAUDE.md Rule #5, (b) the alembic `[post_write_hooks]` config tried to invoke `ruff` (a dev dep absent from the runtime image), (c) the generated file lived in the container's ephemeral filesystem and couldn't escape to the host repo. *Fixed in this commit* (Makefile computes next sequential `--rev-id`; alembic.ini `hooks =` empty; docker-compose.yml bind-mounts `./migrations` and `./alembic.ini`).

**Common failure pattern:** every one of these is at the **integration boundary** between the host shell, the Docker daemon, the Compose network, the build cache, and the live containers. None of them are detectable by the existing unit/integration/contract test layers because those layers all run *before* `make up` (or simulate `make up`'s preconditions via service containers).

## Problem

CI runs `make test-unit && make test-integration && make test-contract` against a service-container Postgres on `localhost:5432` — a synthetic environment that masks every real-world `make up` failure mode. The MVP1 bootstrap PR shipped through CI green, then five bugs surfaced in the first 30 minutes of first-run testing. Future infra changes (new service containers, env-var renames, image dependencies, Compose volume changes) will all fall in the same blind spot.

## Why deferred

Out of scope for `infra_foundation`. This PR addressed each individual bug as it surfaced; the underlying gap (no end-to-end CI smoke test) needs its own scope: a new GitHub Actions workflow job (or a `smoke` job in `pr.yml`) that runs `make up && wait-for-healthz && make migrate && make migrate-create` and asserts `/healthz` returns 200 with all subsystems healthy.

Adds ~3 minutes to every PR run (Docker daemon startup + image build + 6-service boot + healthcheck wait). Worth it for the bug-class it catches.

## Proposed work

A new `smoke` job in `.github/workflows/pr.yml`:

```yaml
smoke:
  name: smoke (make up + AC-1 + make migrate)
  runs-on: ubuntu-latest
  needs: [backend, frontend, docker]
  timeout-minutes: 10
  steps:
    - uses: actions/checkout@v4
    - uses: docker/setup-buildx-action@v3
    - run: make up
    - run: |
        # Wait up to 90s for /healthz to return 200 (the AC-1 gate)
        for i in $(seq 1 18); do
          curl -fs http://localhost:8000/healthz && break
          sleep 5
        done
    - run: |
        # Assert all subsystems are healthy
        STATUS=$(curl -s http://localhost:8000/healthz | jq -r .status)
        [ "$STATUS" = "ok" ] || { curl -s http://localhost:8000/healthz | jq .; exit 1; }
    - run: make migrate
    - run: make migrate-create name=smoke_test
    - run: |
        # The new revision should land on the host with the right rev-id
        ls migrations/versions/0002_smoke_test.py
        grep -q "^revision: str = '0002'" migrations/versions/0002_smoke_test.py
    - run: docker compose logs api worker
      if: failure()
```

This single job catches:
- Stale image (would fail at /healthz timeout)
- Bad install.sh secret-gen (would fail at /healthz)
- `make migrate` not working (explicit step)
- `make migrate-create` rev-id / bind-mount / hook regressions (explicit step)
- Compose dependency ordering or healthcheck regressions (would fail the wait-for-healthz loop)

## Scope signals

- Backend: none
- Frontend: none
- Migration: none
- Config: `.github/workflows/pr.yml` (one new job)
- CI: ~3 min added per PR; gated on backend+frontend+docker passing first so the smoke job only runs after the cheap layers green

## Depends on

`infra_foundation` (this PR — establishes the `make up` flow this would smoke-test).
