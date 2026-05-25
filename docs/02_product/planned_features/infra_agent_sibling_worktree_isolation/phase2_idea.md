# Sibling-worktree isolation — Phase 2: `scripts/run-tests-in-worktree.sh` automation

**Date:** 2026-05-25
**Status:** Idea — deferred Phase 2 of `infra_agent_sibling_worktree_isolation`. Phase 1 (capability A, the CLAUDE.md section) ships first; this Phase 2 idea picks up when the friction the section documents recurs in a second parallel-agent run.
**Priority:** P2 — only useful after a second parallel-agent test-execution event has happened. Until then, the prose example in Phase 1's `CLAUDE.md` section is enough.
**Origin:** Deferred capability B from [`idea.md`](idea.md) §"B. `scripts/run-tests-in-worktree.sh` (or a `make test-worktree` target)". Locked in [`feature_spec.md`](feature_spec.md) §3 "Phase boundaries" via decision D-1.
**Depends on:** Phase 1 merged (the CLAUDE.md section + the documented 8-flag pattern serve as the design seed).

## Problem

After Phase 1 lands, an agent (or human) running tests from a sibling worktree against the main-worktree's Compose stack still has to compose the one-shot container invocation by hand each time. The Phase 1 shell example documents the recipe but doesn't execute it — the operator still types 8+ `-v` flags, the correct `--mount` for the database secret, and the right `--network` value. A second parallel-agent run will repeat this friction; if the friction recurs more than once, automate it.

## Proposed capabilities

### A `scripts/run-tests-in-worktree.sh` entrypoint (or `make test-worktree` target)

The script should:

1. Detect the current worktree's absolute path (`$(git rev-parse --show-toplevel)` — or `git worktree list --porcelain` if the script needs to be robust to running from a sub-directory).
2. Detect the main worktree's path (the worktree whose `branch` is `main` per `git worktree list --porcelain`, or a `RELYLOOP_MAIN_REPO` env-var override).
3. Spin up a one-shot `relyloop/api:${RELYLOOP_GIT_SHA:-dev}` container with the bind mounts spelled out in Phase 1's FR-4 (`backend/`, `migrations/`, `scripts/`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `docker-compose.yml`, `Makefile`, `samples/`).
4. Join the existing Compose network (`relyloop_default` or the operator's `COMPOSE_PROJECT_NAME`-derived value).
5. Mount the main-repo's `secrets/database_url` file with `-v ...:/run/secrets/database_url:ro` and pass `-e DATABASE_URL_FILE=/run/secrets/database_url` (matching CLAUDE.md Rule #2 / D-2).
6. Forward CLI args to a configurable command. Default: `pytest backend/tests/unit/ -v`. Override via `--cmd "..."` or positional args.
7. Print a one-line summary on exit: container removed, exit code, elapsed time.

### A `make test-worktree` target

Thin wrapper around the script. `make test-worktree CMD="pytest backend/tests/integration/"` should just call the script with the override.

### A short companion runbook

Update `docs/03_runbooks/local-dev.md` (or add `docs/03_runbooks/parallel-worktrees.md` if local-dev.md is already full) with the one-paragraph "how to run tests from a sibling worktree without breaking the main stack" pointer.

## Scope signals

- **Backend:** None (no Python code change — the script invokes the existing image and the existing pytest entrypoint).
- **Frontend:** None.
- **Migration:** None.
- **Config:** New optional env var `RELYLOOP_MAIN_REPO` (defaults to the auto-detected main worktree from `git worktree list`).
- **Audit events:** N/A — local dev tooling, not a state-mutating API.
- **Tests:** One smoke test that runs the script against `/tmp/<scratch>` and asserts the container exits cleanly. Lives at `backend/tests/integration/scripts/test_run_tests_in_worktree.py` or similar.

## Why deferred

D-1 in Phase 1's [feature_spec.md](feature_spec.md) §19 explicitly defers capability B until a second parallel-agent test-execution event happens. The rationale: capability A (the CLAUDE.md section) costs ~30 min and proactively addresses the proven failure mode; capability B costs more (~80-120 LOC shell + a smoke test + a runbook update, probably 2–3 hours including review) and only pays off if the friction recurs. We've seen the friction once (`chore_reconciler_terminal_closed_no_poll`, PR #216, 2026-05-23); we wait for the second occurrence before investing.

## Relationship to other work

- **Predicated on** Phase 1 of `infra_agent_sibling_worktree_isolation` (the CLAUDE.md section, which contains the design seed — the exact bind-mount set and the `--mount` secret pattern).
- **Coordinates with** [`impl-execute` Step 0a / 6b / 9.3](../../../../.claude/skills/impl-execute/SKILL.md) — those steps already cover worktree lifecycle; this Phase 2 script covers the runtime data path for the "I want to run tests" use case the lifecycle steps don't.
- **Possible future coordination:** if a managed/cloud parallel-agent path ever ships (per the original conversation that surfaced this idea), Phase 2 becomes moot for cloud runs but still useful for local parallel work.
