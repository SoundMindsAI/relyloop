# Bug fix — `bug_dockerfile_venv_root_owned_after_user_switch`

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/dockerfile-venv-root-owned-after-user-switch`
**Type:** bug fix — medium (this skill's scope)
**Date:** 2026-05-26

## Problem

The `Dockerfile`'s runtime stage runs `RUN uv sync --frozen --no-dev` at [Dockerfile:107](../../../../Dockerfile#L107) **as root** — the `USER relyloop` directive doesn't fire until [Dockerfile:109](../../../../Dockerfile#L109). That `uv sync` installs the project package itself (`relyloop-0.1.0`) into the venv, writing 11 metadata files under `/app/.venv/lib/python3.13/site-packages/relyloop-0.1.0.dist-info/` as `root:root` 644. The venv was previously fully relyloop-owned by the line 89 `COPY --chown=relyloop:relyloop`; line 107 silently re-introduces root-owned files inside it.

Production `api` / `worker` / `migrate` services consume the venv read-only, so they never bite. But any one-shot container that needs `uv run` (which implicitly does `uv sync` to reconcile against the lockfile + install dev deps) fails with `Permission denied (os error 13)` trying to rewrite those files as the `relyloop` user. The Phase 2 `scripts/run-tests-in-worktree.sh` (`make test-worktree`) shipped in PR #249 hits this on every invocation and works around it with `--user root` + `PYTHONDONTWRITEBYTECODE=1`.

## Reproduction

Reproducer on `main` (image already built locally as `relyloop/api:dev`):

```bash
docker run --rm relyloop/api:dev sh -c \
  'stat -c "%a %U:%G" /app/.venv/lib/python3.13/site-packages/relyloop-0.1.0.dist-info/INSTALLER'
# Expected on main:  644 root:root
# Expected on fix:   644 relyloop:relyloop

docker run --rm relyloop/api:dev sh -c \
  'find /app/.venv -not -user relyloop | wc -l'
# Expected on main:  11
# Expected on fix:   0
```

The static regression test (`backend/tests/unit/infra/test_dockerfile_venv_chown.py`) parses the Dockerfile and asserts the chown line appears between the `RUN uv sync --frozen --no-dev` line and the `USER relyloop` line. It fails on the pre-fix Dockerfile and passes on the fixed one.

## Root cause

- **Owning layer:** Dockerfile build stage.
- **Origin:** [Dockerfile:107](../../../../Dockerfile#L107) — `RUN uv sync --frozen --no-dev` runs as root (no `USER` directive yet) and writes 11 files under `relyloop-0.1.0.dist-info/` as `root:root`.
- **Propagation:** [Dockerfile:109](../../../../Dockerfile#L109) switches `USER relyloop`, but the previously-written files keep their root ownership. Any `uv run` / `uv sync` from the relyloop user inside the image then fails on those files.

## Fix design (locked decisions)

1. **Add `RUN chown -R relyloop:relyloop /app/.venv` between [Dockerfile:107](../../../../Dockerfile#L107) and [Dockerfile:109](../../../../Dockerfile#L109).** Cites: bug-fix protocol "smallest scope that addresses the root cause" (CLAUDE.md §"Bug Fix Protocol" step 3). The alternative — moving `USER relyloop` above line 107 so `uv sync` runs as the right user from the start — is more architecturally clean but requires verifying `uv sync` works as a non-root user (extra build cycle + extra risk surface for a P2 bug). Both alternatives produce the same end state; Option A is the minimal diff.
2. **Revert the `--user root` + `-e PYTHONDONTWRITEBYTECODE=1` workaround in [scripts/run-tests-in-worktree.sh](../../../../scripts/run-tests-in-worktree.sh) in the same PR.** Cites: idea.md §"Proposed fix" explicitly couples the revert to this fix ("the workaround can be reverted"). The workaround's inline comment cites this bug folder as its sole justification — leaving it in place after the fix creates a documentation contradiction. The image's base stage already sets `PYTHONDONTWRITEBYTECODE=1` at [Dockerfile:23](../../../../Dockerfile#L23), so the `-e` flag was always redundant once the `--user root` reason disappears.
3. **Regression test = static Dockerfile-parse unit test, not docker-build smoke.** Cites: CLAUDE.md §"Testing Conventions" — the regression test must "fail without the fix and pass with it" but doesn't mandate end-to-end coverage. A parse-and-assert unit test (<10ms, no docker) catches the regression case (someone deletes the chown line in a future Dockerfile cleanup). CI's existing `docker buildx (relyloop/api)` job at [.github/workflows/pr.yml:481-503](../../../../.github/workflows/pr.yml#L481-L503) already verifies buildability. The end-to-end stat check has already happened in this skill's Phase 2 + Phase 5 verification.
4. **Update [backend/tests/unit/scripts/test_run_tests_in_worktree.py](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) to reflect the post-revert argv.** Cites: tightly coupled to decision 2 — the existing test at line 141-148 asserts `--user`, `root`, and `PYTHONDONTWRITEBYTECODE=1` are in the dry-run argv; with the revert those assertions become false. Flip them to negative assertions so a future "let me re-add --user root" regression fails the test.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | [backend/tests/unit/infra/test_dockerfile_venv_chown.py](../../../../backend/tests/unit/infra/test_dockerfile_venv_chown.py) | Parses `Dockerfile`; locates the `RUN uv sync --frozen --no-dev` line, the `RUN chown -R relyloop:relyloop /app/.venv` line, and the `USER relyloop` line in the runtime stage; asserts they appear in that strict order. Fails on the pre-fix Dockerfile (no chown line exists). |
| unit | [backend/tests/unit/scripts/test_run_tests_in_worktree.py](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | Updated assertions: `--user root` and `PYTHONDONTWRITEBYTECODE=1` are NOT in the dry-run argv (the workaround was reverted with the Dockerfile fix). Mount count drops from 12 to 11 (no Postgres count change — postgres_password is independent). |

End-to-end verification (one-time, not added to CI): `docker build -t relyloop/api:dev . && docker run --rm relyloop/api:dev sh -c 'find /app/.venv -not -user relyloop | wc -l'` returns `0`.

## Rollout

- **Image rebuild required.** Operators on the fixed image won't see the bug; operators still on a pre-fix image will. The post-merge automatic image rebuild on the next `make up` covers the dev-loop case. The fix is forward-only — no data migration, no env var change, no operator action beyond rebuilding.
- **`make test-worktree` users:** the script revert is invisible if the operator is on the new image (the workaround was masking the bug, not actively required). On a pre-fix image, `make test-worktree` will start failing with the original `Permission denied` error — the right fix is to rebuild the image, which the script's image tag (`relyloop/api:${RELYLOOP_GIT_SHA:-dev}`) will pull naturally on next `make up`.

## Tangential observations

None — the trace was clean. The Dockerfile structure is otherwise correct; the bug is a single ordering issue between line 107 and line 109.
