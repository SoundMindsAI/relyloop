# `make test-worktree` silently skips integration tests that need Postgres or cluster credentials

**Date:** 2026-05-25
**Status:** Idea — surfaced during `infra_study_preflight_real_engine_integration` Story 1.3 implementation (PR pending).
**Priority:** P2 — workaround exists (one-shot `docker run` with the missing env vars); affects discoverability for any future test that needs DB or ES-credentials access from a sibling worktree.

**Origin:** While running the 5 rewritten AC tests + helper smoke tests for `infra_study_preflight_real_engine_integration` via `make test-worktree CMD="pytest backend/tests/integration/test_studies_api.py -v"`, all 43 tests reported `SKIPPED [..] Postgres not reachable — see docs/03_runbooks/local-dev.md`. The root cause is that [`scripts/run-tests-in-worktree.sh:150-171`](../../../../scripts/run-tests-in-worktree.sh#L150-L171) passes only `DATABASE_URL_FILE=/run/secrets/database_url` as a `-e` flag and only mounts `$SECRET_FILE:/run/secrets/database_url:ro`. The `postgres_reachable()` helper at [`backend/tests/conftest.py:50-72`](../../../../backend/tests/conftest.py#L50-L72) checks for BOTH `DATABASE_URL_FILE` AND `POSTGRES_PASSWORD_FILE` env vars before declaring Postgres reachable — so integration tests skip silently with a misleading "Postgres not reachable" reason when the actual issue is the missing env var + mount in the script.

The same gap applies to `CLUSTER_CREDENTIALS_FILE` for any test that needs `acquire_adapter()` to resolve credentials against a real cluster (the new `seed_minimum_for_overlap_probe_real_engine()` helper does this).

## Problem

`scripts/run-tests-in-worktree.sh` was designed for **unit tests** (the default `CMD` is `pytest backend/tests/unit/ -v`) which don't need Postgres or cluster credentials. When operators override `CMD=` to run integration tests that touch DB or real-engine cluster acquisition, the script silently skips them — the worktree-test pattern looks like it works, but the underlying assertions never execute.

Concretely:

1. **Postgres-touching integration tests** (any test using `postgres_reachable()` for the skip gate — the majority of `backend/tests/integration/`): all skip with "Postgres not reachable" even though the script wires the Compose network correctly. The fix is one additional `-e POSTGRES_PASSWORD_FILE=...` flag + one additional `-v <host>:<container>:ro` mount.

2. **Cluster-credentials-touching integration tests** (`backend/tests/integration/test_es_overlap_probe_helpers.py::test_seed_helper_missing_local_es_credentials` and the 5 rewritten AC tests in `test_studies_api.py`): the helper's FR-6 pre-flight skips (locally) or raises `RuntimeError` (in CI) when the YAML mount is missing. From the worktree-test script, the mount is absent — so locally the tests appear to "pass" by skipping, hiding the fact that the real-engine assertions never ran.

**Workaround** (used during Story 1.3 implementation): construct the `docker run` invocation by hand, adding the two missing `-e` + `-v` pairs and the cluster_credentials.yaml mount. ~10 lines of additional shell instead of one make-target line. Not catastrophic, but defeats the discoverability that `make test-worktree` was supposed to deliver.

## Why deferred

Out of scope for `infra_study_preflight_real_engine_integration`. The fix touches `scripts/run-tests-in-worktree.sh` (and possibly the Makefile target's argument list); the feature in flight is a test-code rewrite. Coupling the two would mix unrelated concerns in one PR.

## Proposed capabilities

1. **Add `POSTGRES_PASSWORD_FILE` env var + mount** to [`scripts/run-tests-in-worktree.sh:150-171`](../../../../scripts/run-tests-in-worktree.sh#L150-L171). Follow the existing `DATABASE_URL_FILE` pattern — read the resolved path from `$MAIN_REPO/secrets/postgres_password` (the convention `make test-worktree` already follows via `MAIN_REPO=$(git worktree list | awk '{print $1; exit}')`).
2. **Add `CLUSTER_CREDENTIALS_FILE` env var + mount** for any test that touches `acquire_adapter()`. Same pattern. Optional in the sense that the helper code paths skip cleanly when the YAML is missing, but the silent-skip is the actual bug — `make test-worktree` should propagate the available secrets, not selectively hide them.
3. **Document the env-var mount pattern** in [`docs/03_runbooks/parallel-worktrees.md`](../../../../docs/03_runbooks/parallel-worktrees.md) so future test-infra changes that add new `*_FILE` env vars know to update both Compose AND the worktree-test script.

## Scope signals

- **Backend:** none.
- **Frontend:** none.
- **Infra:** ~10-15 lines in `scripts/run-tests-in-worktree.sh` + a paragraph in `parallel-worktrees.md`.
- **Migration:** none.

## Coordinates with

- The current `infra_study_preflight_real_engine_integration` feature surfaced this; the rewritten tests work fine via the standalone `docker run` invocation but skip via `make test-worktree`.
- Future operator workflows that promote `make test-worktree` as the canonical worktree-test entrypoint would benefit (the current state silently degrades integration test coverage in that pattern).
