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

The static regression test (`backend/tests/unit/test_dockerfile_runtime_stage.py`) parses the Dockerfile and asserts the runtime-stage `USER relyloop` directive appears BEFORE the project-installing `RUN uv sync --frozen --no-dev`, AND that no `RUN chown -R /app/.venv` step exists (which would bloat the image — see Decision #1 below). It fails on the pre-fix Dockerfile and passes on the fixed one.

## Root cause

- **Owning layer:** Dockerfile build stage.
- **Origin:** [Dockerfile:107](../../../../Dockerfile#L107) — `RUN uv sync --frozen --no-dev` runs as root (no `USER` directive yet) and writes 11 files under `relyloop-0.1.0.dist-info/` as `root:root`.
- **Propagation:** [Dockerfile:109](../../../../Dockerfile#L109) switches `USER relyloop`, but the previously-written files keep their root ownership. Any `uv run` / `uv sync` from the relyloop user inside the image then fails on those files.

## Fix design (locked decisions)

1. **Move `USER relyloop` to BEFORE the runtime-stage `RUN uv sync`** (Option B from idea.md). Cites: Gemini Code Assist review on PR #263 (image-bloat finding, High severity). The originally-locked Option A (`RUN chown -R relyloop:relyloop /app/.venv` after the sync) was rejected after empirical measurement: `docker history` on the Option-A image showed the `RUN chown` step added a **385MB layer** — overlay2 copies up every touched file into a new layer, effectively duplicating the venv. Final image was 963MB vs 577MB with Option B. Option B is functionally equivalent (both produce `find /app/.venv -not -user relyloop | wc -l` = 0 and an `INSTALLER` owned by `relyloop:relyloop`) but avoids the bloat layer entirely. All inputs `uv sync` touches are already relyloop-owned at the point of the move: `/app/.venv` via [Dockerfile:89](../../../../Dockerfile#L89)'s `COPY --chown`; source + project metadata via the chowned COPYs at [Dockerfile:93-104](../../../../Dockerfile#L93-L104); `/home/relyloop` for uv's cache via `useradd --create-home` at [Dockerfile:86](../../../../Dockerfile#L86); `UV_LINK_MODE=copy` at [Dockerfile:26](../../../../Dockerfile#L26) avoids hardlink-permission issues.
2. **Revert the `--user root` + `-e PYTHONDONTWRITEBYTECODE=1` workaround in [scripts/run-tests-in-worktree.sh](../../../../scripts/run-tests-in-worktree.sh) in the same PR.** Cites: idea.md §"Proposed fix" explicitly couples the revert to this fix ("the workaround can be reverted"). The workaround's inline comment cites this bug folder as its sole justification — leaving it in place after the fix creates a documentation contradiction. The image's base stage already sets `PYTHONDONTWRITEBYTECODE=1` at [Dockerfile:23](../../../../Dockerfile#L23), so the `-e` flag was always redundant once the `--user root` reason disappears.
3. **Regression test = static Dockerfile-parse unit test, not docker-build smoke.** Cites: CLAUDE.md §"Testing Conventions" — the regression test must "fail without the fix and pass with it" but doesn't mandate end-to-end coverage. A parse-and-assert unit test (<10ms, no docker) catches the regression case (someone moves `USER relyloop` back below the runtime-stage `uv sync`, OR adds a `RUN chown -R /app/.venv` "to be safe" that silently bloats the image). CI's existing `docker buildx (relyloop/api)` job at [.github/workflows/pr.yml:481-503](../../../../.github/workflows/pr.yml#L481-L503) already verifies buildability. The end-to-end stat check has already happened in this skill's Phase 2 + Phase 5 verification. A deferred follow-up idea ([infra_dockerfile_invariant_smoke_in_ci](../infra_dockerfile_invariant_smoke_in_ci/idea.md)) tracks adding a runtime smoke step to the buildx job for stronger coverage.
4. **Update [backend/tests/unit/scripts/test_run_tests_in_worktree.py](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) to reflect the post-revert argv.** Cites: tightly coupled to decision 2 — the existing test at line 141-148 asserts `--user`, `root`, and `PYTHONDONTWRITEBYTECODE=1` are in the dry-run argv; with the revert those assertions become false. Flip them to negative assertions so a future "let me re-add --user root" regression fails the test. The mount count (`-v` flag count) is unchanged at 12 — the reverted flags are `-e` env vars and `--user`, not `-v` mounts.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | [backend/tests/unit/test_dockerfile_runtime_stage.py](../../../../backend/tests/unit/test_dockerfile_runtime_stage.py) | Parses `Dockerfile`; in the runtime stage, asserts `USER relyloop` appears BEFORE the project-installing `RUN uv sync --frozen --no-dev`, AND that no `RUN chown -R /app/.venv` step exists (image-bloat guard). Fails on the pre-fix Dockerfile (USER comes after the runtime-stage sync). |
| unit | [backend/tests/unit/scripts/test_run_tests_in_worktree.py](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | Updated assertions: `--user root` and `PYTHONDONTWRITEBYTECODE=1` are NOT in the dry-run argv (the workaround was reverted with the Dockerfile fix). Mount count remains at the 12-mount baseline (the reverted flags aren't `-v` mounts). |

End-to-end verification (one-time, not added to CI): `docker build -t relyloop/api:dev . && docker run --rm relyloop/api:dev sh -c 'find /app/.venv -not -user relyloop | wc -l'` returns `0`, and `docker images relyloop/api:dev` reports ~577MB (vs ~963MB with the chown-after-sync alternative).

## Rollout

- **Image rebuild required.** Operators on the fixed image won't see the bug; operators still on a pre-fix image will. The post-merge automatic image rebuild on the next `make up` covers the dev-loop case. The fix is forward-only — no data migration, no env var change, no operator action beyond rebuilding.
- **`make test-worktree` users:** the script revert is invisible if the operator is on the new image (the workaround was masking the bug, not actively required). On a pre-fix image, `make test-worktree` will start failing with the original `Permission denied` error — the right fix is to rebuild the image, which the script's image tag (`relyloop/api:${RELYLOOP_GIT_SHA:-dev}`) will pull naturally on next `make up`.

## Tangential observations

- [infra_dockerfile_invariant_smoke_in_ci](../infra_dockerfile_invariant_smoke_in_ci/idea.md) — deferred CI runtime smoke step covering venv ownership + image-size invariants. Surfaced by the rejected Option A bloat measurement during Gemini review.
