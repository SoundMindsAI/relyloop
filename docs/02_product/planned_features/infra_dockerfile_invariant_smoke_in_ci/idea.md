# Infra: Dockerfile invariant smoke check in CI's buildx job

**Date:** 2026-05-26
**Status:** Idea — surfaced during `/bug-fix --ship` for `bug_dockerfile_venv_root_owned_after_user_switch` (PR landing 2026-05-26).
**Priority:** P3 — the recently-shipped static Dockerfile-parse unit test ([backend/tests/unit/test_dockerfile_runtime_stage.py](../../../../backend/tests/unit/test_dockerfile_runtime_stage.py)) catches the load-bearing case (someone deletes the chown line). This idea covers the orthogonal "Dockerfile builds but post-build runtime state is somehow wrong" case, which is a much smaller risk surface but trivial to add.
**Origin:** Bug fix for `bug_dockerfile_venv_root_owned_after_user_switch` (commit 58835184). The fix's `bug_fix.md` Decision #3 explicitly chose the static unit test over a CI smoke step because adding it would have extended the bug-fix PR into pr.yml — a different subsystem. Capturing the deferred option here.
**Depends on:** None.

## Problem

CI's `docker buildx (relyloop/api)` job at [.github/workflows/pr.yml:481-503](../../../../.github/workflows/pr.yml#L481-L503) builds the runtime image with `push: false` and `cache-to: type=gha,mode=max` — it verifies buildability but never runs the image. The static Dockerfile-parse unit test catches structural regressions in the file but cannot catch runtime-state regressions (e.g., `chown` runs but doesn't propagate to all files because of a future build-cache interaction, `uv sync` behavior shifts in a future uv release, etc.).

The reproducer-format from `bug_dockerfile_venv_root_owned_after_user_switch` is one shell command:

```bash
docker run --rm relyloop/api:<tag> sh -c 'find /app/.venv -not -user relyloop | wc -l | grep -q "^0$"'
```

That returns exit 0 on a correctly-built image and non-zero on a regressed one. Adding it to the buildx job is ~5 lines of YAML.

## Proposed fix

Two small changes to [.github/workflows/pr.yml](../../../../.github/workflows/pr.yml):

1. Add `load: true` to the `docker/build-push-action@v7` step so the built image is loaded into the local Docker daemon (currently only exported to GHA cache, not loadable).
2. Add a new step after the build:

```yaml
- name: Verify runtime image invariants
  run: |
    docker run --rm relyloop/api:${{ github.sha }} sh -c '
      set -e
      # /app/.venv must be fully relyloop-owned (bug_dockerfile_venv_root_owned_after_user_switch).
      n=$(find /app/.venv -not -user relyloop | wc -l)
      [ "$n" = "0" ] || { echo "FAIL: $n non-relyloop files in /app/.venv"; exit 1; }
      # Default user must be relyloop, not root.
      id | grep -q "uid=1000(relyloop)" || { echo "FAIL: default user is not relyloop"; exit 1; }
    '
```

The list of invariants is extensible — future Dockerfile bugs surface as new assertions in the same step.

## Scope signals

- **Backend:** None.
- **Frontend:** None.
- **Migration:** None.
- **Config:** None (CI workflow change only).
- **Audit events:** N/A.
- **Tests:** The new CI step IS the test; no Python test changes.

## Why deferred

`bug_dockerfile_venv_root_owned_after_user_switch` had a strict "smallest scope that addresses the root cause" mandate. The static unit test already catches the load-bearing regression case (Dockerfile structural change). The CI runtime smoke covers a different (much smaller) risk surface and bundles better with similar smoke checks for other Dockerfile invariants — better to add several at once when one becomes warranted, rather than land a one-line CI gate alone.

## Relationship to other work

- **Originating bug:** `bug_dockerfile_venv_root_owned_after_user_switch` (the chown fix that triggered this observation).
- **Adjacent:** `infra_ci_smoke_makeup` (idea — broader systemic CI smoke covering `make up` and other operator-paths). Could bundle.
