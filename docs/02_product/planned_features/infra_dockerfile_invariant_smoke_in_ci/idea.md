# Infra: Dockerfile invariant smoke check in CI's buildx job

**Date:** 2026-05-26
**Status:** Idea — surfaced during `/bug-fix --ship` for [`bug_dockerfile_venv_root_owned_after_user_switch`](../../../00_overview/implemented_features/2026_05_26_bug_dockerfile_venv_root_owned_after_user_switch/bug_fix.md) (PR #263 merged 2026-05-26 as squash `644b0b80`; finalized via PR #264 `74d85b08`).
**Priority:** P2 — the recently-shipped static Dockerfile-parse unit test ([backend/tests/unit/test_dockerfile_runtime_stage.py](../../../../backend/tests/unit/test_dockerfile_runtime_stage.py), 3 tests) catches the load-bearing structural case (someone moves `USER relyloop` back after the runtime-stage `uv sync`, OR adds a `RUN chown -R /app/.venv` "to be safe" that would silently bloat the image). This idea covers the orthogonal "Dockerfile builds but post-build runtime state is somehow wrong" case, which is a much smaller risk surface but trivial to add.
**Origin:** Bug fix for `bug_dockerfile_venv_root_owned_after_user_switch` (PR #263). The fix's `bug_fix.md` Decision #3 explicitly chose the static unit test over a CI smoke step because adding it would have extended the bug-fix PR into pr.yml — a different subsystem. Capturing the deferred option here.
**Depends on:** None.

## Problem

CI's `docker buildx (relyloop/api)` job at [.github/workflows/pr.yml:481-503](../../../../.github/workflows/pr.yml#L481-L503) builds the runtime image with `push: false` and `cache-to: type=gha,mode=max` — it verifies buildability but never runs the image. The static Dockerfile-parse unit test catches structural regressions in the file but cannot catch runtime-state regressions (e.g., a future uv release silently rearranges where it writes dist-info files; an unrelated USER-directive edit accidentally regresses to running the runtime-stage `uv sync` as root; an upstream Python base image switches default UID).

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

- **Originating bug:** [`bug_dockerfile_venv_root_owned_after_user_switch`](../../../00_overview/implemented_features/2026_05_26_bug_dockerfile_venv_root_owned_after_user_switch/) (the USER-before-uv-sync fix that triggered this observation; merged PR #263 / `644b0b80`).
- **Live bundling opportunity:** the `smoke (operator-path tutorial flow)` job at [.github/workflows/pr.yml:307-470](../../../../.github/workflows/pr.yml#L307-L470) already runs `make up` end-to-end and exercises the image through the tutorial — but does NOT check image filesystem invariants like venv ownership or default user. This new step bolts onto the `docker buildx (relyloop/api)` job (which builds the image but never runs it), giving a fast image-invariant signal that fails BEFORE the heavier smoke job starts. The two are complementary: smoke catches operator-path behavior; this catches image-construction invariants.
- **Predecessor (already shipped):** [`infra_ci_smoke_makeup`](../../../00_overview/implemented_features/2026_05_13_infra_ci_smoke_makeup/idea.md) shipped 2026-05-13 — that's the work that established the `make up`-driven smoke job in the first place. This idea extends the same "actually run the image in CI" philosophy down one layer (run the image directly inside the buildx job, before smoke).
