# Sibling-worktree isolation — Phase 3: per-worktree `DATABASE_URL_FILE` override

**Date:** 2026-05-25
**Status:** Idea — deferred Phase 3 of `infra_agent_sibling_worktree_isolation`. Phase 1 (CLAUDE.md section) ships first; Phase 2 (test-runner script) ships second; this Phase 3 idea picks up only if a migration-collision incident occurs between concurrent worktrees sharing the same Postgres.
**Priority:** Backlog — wait for an actual rev_id collision to motivate. Lower than Phase 2; the speculative-incident threshold is higher.
**Origin:** Deferred capability C from [`idea.md`](idea.md) §"C. Optional: separate Alembic test database per worktree". Locked in [`feature_spec.md`](feature_spec.md) §3 "Phase boundaries" via decision D-1. Secrets-pattern constraint locked via D-2.
**Depends on:** Phase 2 merged (the test-runner script is the natural place to wire in the per-worktree DB override). Possibly Phase 1 alone if the override mechanism is reframed as a Compose-only knob.

## Problem

When two worktrees both have migrations in flight against the shared Postgres, the Alembic round-trip verification (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`) on one branch can collide with the head of the other. Rev_id space, schema state, or even seed-data ordering can drift in non-deterministic ways. The classical fix is: give each worktree its own database.

## Proposed capabilities

### Per-worktree `DATABASE_URL_FILE` override (CLAUDE.md Rule #2 compliant)

Following [`feature_spec.md`](feature_spec.md) decision D-2: any per-worktree `DATABASE_URL` override **MUST** use the `*_FILE`-mounted-secret pattern. Bare `DATABASE_URL=postgresql://...` env vars are forbidden. Two concrete shapes the Phase 3 design should consider:

1. **Per-worktree secret file on disk.** When the Phase 2 script (or a new `make doctor-worktree-db`) initializes a worktree-scoped database, it writes `./secrets/database_url.worktree-<hash>` (where `<hash>` is a stable hash of the worktree's absolute path), then the Phase 2 one-shot container mounts that file via `-v $MAIN_REPO/secrets/database_url.worktree-<hash>:/run/secrets/database_url:ro`. The main worktree's stack keeps using `./secrets/database_url` (unchanged); only the one-shot test container sees the override.
2. **On-the-fly tempdir secret.** The Phase 2 script writes the override URL to a `mktemp -d`-created tempdir, mounts that tempdir's file into the one-shot container, and `rm -rf`s the tempdir on exit. Avoids leaving a stub in `./secrets/` (per the CLAUDE.md "Local-stub hygiene" rule); cost is recreation on every invocation.

### Database provisioning

A `make migrate-worktree` target (or a flag on the Phase 2 script) that:

1. Computes the worktree database name (e.g., `relyloop_worktree_${HASH}`).
2. Connects to the shared Postgres as the `relyloop` user.
3. Idempotently creates the worktree database if it doesn't exist (`CREATE DATABASE IF NOT EXISTS`-equivalent — Postgres needs the standard `pg_database` check).
4. Writes the override secret file (shape 1 or 2 above).
5. Runs `alembic upgrade head` against the worktree database.

### Cleanup

A `make clean-worktree-db` target that drops the worktree database, removes the secret file, and removes any `migrations/versions/0*.py` files that exist only in the dropped worktree's branch (probably out of scope — covered by `git worktree remove`).

## Scope signals

- **Backend:** Minor — likely zero changes to `backend/app/` because the URL resolution path already reads `*_FILE`. The change is purely in tooling (script + Makefile + maybe `backend/app/db/optuna_schema.py` if Optuna schema init needs per-worktree handling).
- **Frontend:** None.
- **Migration:** None to the migration files themselves — but the migration *invocation* changes (point alembic at a different DB).
- **Config:** New optional secret file pattern `./secrets/database_url.worktree-<hash>`. Documented in CLAUDE.md Rule #2 expansion.
- **Audit events:** N/A — local dev tooling.
- **Tests:** One integration smoke test confirming the worktree DB is created, migrations apply, and cleanup drops it. Probably `backend/tests/integration/scripts/test_worktree_db_provision.py`.

## Why deferred

D-1 in Phase 1's [feature_spec.md](feature_spec.md) §19 defers capability C until a migration-collision incident actually happens. This is the right threshold because (a) migration collisions are visible at PR time (CI fails on the colliding branch — the operator notices immediately, this is not silent), and (b) the workaround in the meantime is "rebase the second branch and re-generate the migration file." Until concurrent worktrees with non-rebasable migration states become common (e.g., two long-lived autonomous-agent branches), the workaround is cheaper than the per-worktree DB infrastructure.

D-2 also pre-locks the secrets-pattern constraint: when this idea eventually graduates to a feature spec, the `*_FILE`-mounted-secret pattern is non-negotiable. No spec-time debate about bare env vars.

## Relationship to other work

- **Predicated on** Phase 1 (the CLAUDE.md section's design seed) and likely Phase 2 (the test-runner script provides the natural plumbing point for the override). Phase 3 standalone would work but would require duplicating Phase 2's bind-mount logic.
- **Coordinates with** CLAUDE.md Absolute Rule #2 (secrets-via-files) and Rule #5 (Alembic round-trip migrations). The design must respect both.
- **Possible future coordination:** if RelyLoop ever adopts schema-per-tenant at MVP4, the per-tenant DB mechanism may overlap with this per-worktree DB mechanism. Worth flagging at the MVP4 multi-tenancy design step, but not blocking either feature on the other today.
