# Bug: `/app/.venv` is root-owned in the production image, blocking `uv sync` from any container running as the `relyloop` user

**Date:** 2026-05-25
**Status:** Idea — surfaced during `/impl-execute` Phase 2 operator-path verification of `make test-worktree` (PR #249, `infra_agent_sibling_worktree_isolation`).
**Priority:** P2 — the production stack works fine (existing api/worker/migrate services that ran as root pre-image-build use the venv read-only). The bug only bites in a one-shot container that needs `uv run` or `uv sync` from the `relyloop` user — i.e., the dev-loop case `make test-worktree` introduces.
**Origin:** Discovered while verifying `make test-worktree` end-to-end against the live stack. The first run failed with: `error: failed to remove file /app/.venv/lib/python3.13/site-packages/relyloop-0.1.0.dist-info/INSTALLER: Permission denied (os error 13)`. Investigation showed the file is `root:root` 644 inside the image, while the runtime user is `relyloop` (UID 1000).
**Depends on:** None.

## Problem

The `Dockerfile` has this ordering at the bottom of the `runtime` stage:

```dockerfile
# Line 89
COPY --from=deps --chown=relyloop:relyloop /app/.venv /app/.venv
# ...lines 91-105 — chowned COPYs for source, prompts, scripts, alembic.ini, pyproject.toml...
# Line 107 — runs as ROOT (no USER directive yet)
RUN uv sync --frozen --no-dev
# Line 109
USER relyloop
```

Line 89's `COPY --chown` makes the venv user-owned at that moment. Line 107's `RUN uv sync --frozen --no-dev` runs **as root** (USER directive doesn't come until line 109) and **installs the `relyloop` project itself** into the venv (the editable install). The newly-written package metadata files (e.g., `relyloop-0.1.0.dist-info/INSTALLER`, `RECORD`, `WHEEL`, `top_level.txt`) end up `root:root` 644. Line 109 switches the runtime user to `relyloop`, but the previously-written files keep their root ownership.

For the production api / worker / migrate services that consume the venv read-only, this never bites — they only need read access. For a one-shot dev container that wants to invoke `uv run pytest` (which implicitly does `uv sync` to reconcile against the lockfile + install dev deps), the implicit `uv sync` tries to remove and rewrite those root-owned files and fails immediately.

Verified inside a fresh `relyloop/api:dev` container:

```
$ docker run --rm relyloop/api:dev sh -c 'id; stat -c "%a %U:%G" /app/.venv/lib/python3.13/site-packages/relyloop-0.1.0.dist-info/INSTALLER'
uid=1000(relyloop) gid=1000(relyloop) groups=1000(relyloop)
644 root:root
```

## Why this matters for `make test-worktree`

The Phase 2 work in PR #249 ships `scripts/run-tests-in-worktree.sh` which spins up a one-shot container against the Compose network for dev-loop test execution. The default invocation runs `uv run pytest backend/tests/unit/ -v`, which hits this bug.

The Phase 2 PR works around it by passing `--user root` to `docker run` plus `-e PYTHONDONTWRITEBYTECODE=1` to prevent root-owned `__pycache__` from leaking onto the bind-mounted host paths. This is a tactical workaround — the real fix is one Dockerfile line.

## Proposed fix

Add `RUN chown -R relyloop:relyloop /app/.venv` between line 107 and line 109 of `Dockerfile`. Concretely:

```dockerfile
RUN uv sync --frozen --no-dev
RUN chown -R relyloop:relyloop /app/.venv                    # <-- ADD
USER relyloop
```

OR, alternatively, move the `USER relyloop` directive ABOVE line 107 so `uv sync` runs as the right user from the start. This is the more architecturally clean fix but requires verifying that the relyloop user has the right permissions on the COPY-target directories (lines 92-105's `--chown=relyloop:relyloop` should already cover that, but a single misalignment between stages would break the build).

Either fix is ~1 line. Both require rebuilding the image (`docker compose build api worker migrate`).

Once the fix lands, the Phase 2 script's `--user root` + `PYTHONDONTWRITEBYTECODE=1` workaround can be reverted to run as the regular `relyloop` user, and the tactical workaround disappears.

## Scope signals

- **Backend:** None.
- **Frontend:** None.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A.
- **Tests:** A smoke check that the venv is fully relyloop-owned after image build (`docker run --rm relyloop/api:dev stat -c '%U:%G' /app/.venv/lib/python3.13/site-packages/relyloop-0.1.0.dist-info/INSTALLER` → exits with `relyloop:relyloop`). One assertion line.

## Why deferred

The Phase 2 PR (which surfaced this bug) has its own success criteria (script + Makefile + smoke + runbook + operator-path verification). Folding a Dockerfile fix into the same PR would:

1. Mix subsystems (sibling-worktree feature + image-build hygiene). The PR is already mid-review on the docs-only scope; expanding scope here adds reviewer cognitive load.
2. Require a full image rebuild + CI re-run, which is at-best slow and at-worst blocked by the pre-existing `bug_smoke_dashboard_demo_state_locator_missing` failure on `main`.
3. Risk reviewer pushback on the orthogonal change.

The tactical `--user root` workaround in Phase 2 is bounded (only the `make test-worktree` path, an opt-in dev tool) and doesn't make production behavior worse. Fixing the Dockerfile bug is a separate small PR.

## Relationship to other work

- **Surfaced by** PR #249 / `infra_agent_sibling_worktree_isolation` Phase 2 (the `make test-worktree` operator-path verification).
- **Independent of** the Phase 1 + Phase 2 sibling-worktree work — the bug exists with or without that feature; the dev-loop tool just exercises it.
- **Possible coordination:** if a future PR introduces another dev-loop tool that needs `uv run` from the `relyloop` user in a one-shot container, the same workaround / fix applies. Bundling those into one Dockerfile fix PR makes sense.
