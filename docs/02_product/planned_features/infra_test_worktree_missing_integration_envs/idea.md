# `make test-worktree` silently skips integration tests that need Postgres or cluster credentials

**Date:** 2026-05-25
**Status:** Idea — surfaced during `infra_study_preflight_real_engine_integration` Story 1.3 implementation (PR #255 merged 2026-05-22).
**Priority:** P2 — workaround exists (one-shot `docker run` with the missing env vars); affects discoverability for any future test that needs DB or ES-credentials access from a sibling worktree.
**Depends on:** [`infra_agent_sibling_worktree_isolation`](../../../00_overview/implemented_features/) Phase 2 (PR #249 merged 2026-05-25) — Phase 2 shipped `scripts/run-tests-in-worktree.sh` and the `make test-worktree` target this idea patches. No upstream feature dependencies — this is a self-contained infra fix.

**Origin:** While running the 5 rewritten AC tests + helper smoke tests for `infra_study_preflight_real_engine_integration` via `make test-worktree CMD="pytest backend/tests/integration/test_studies_api.py -v"`, all 43 tests reported `SKIPPED [..] Postgres not reachable — see docs/03_runbooks/local-dev.md`. The root cause is that [`scripts/run-tests-in-worktree.sh:150-171`](../../../../scripts/run-tests-in-worktree.sh#L150-L171) passes only `DATABASE_URL_FILE=/run/secrets/database_url` as a `-e` flag and only mounts `$SECRET_FILE:/run/secrets/database_url:ro`. The `postgres_reachable()` helper at [`backend/tests/conftest.py:50-72`](../../../../backend/tests/conftest.py#L50-L72) checks for BOTH `DATABASE_URL_FILE` AND `POSTGRES_PASSWORD_FILE` env vars before declaring Postgres reachable — so integration tests skip with the misleading reason `"Postgres not reachable"` when the actual issue is the missing env var + mount in the script. The skip itself is logged loudly by pytest; what's silent is the underlying cause being misattributed.

The same gap applies to `CLUSTER_CREDENTIALS_FILE` for any test that needs `acquire_adapter()` to resolve credentials against a real cluster (the new `seed_minimum_for_overlap_probe_real_engine()` helper does this).

## Problem

`scripts/run-tests-in-worktree.sh` was designed for **unit tests** (the default `CMD` is `pytest backend/tests/unit/ -v`) which don't need Postgres or cluster credentials. When operators override `CMD=` to run integration tests that touch DB or real-engine cluster acquisition, the script silently skips them — the worktree-test pattern looks like it works, but the underlying assertions never execute.

Concretely:

1. **Postgres-touching integration tests** (any test using `postgres_reachable()` for the skip gate — the majority of `backend/tests/integration/`): all skip with "Postgres not reachable" even though the script wires the Compose network correctly. The fix is one additional `-e POSTGRES_PASSWORD_FILE=...` flag + one additional `-v <host>:<container>:ro` mount.

2. **Cluster-credentials-touching integration tests** (`backend/tests/integration/test_es_overlap_probe_helpers.py::test_seed_helper_missing_local_es_credentials` and the 5 rewritten AC tests in `test_studies_api.py`): the helper's FR-6 pre-flight skips (locally) or raises `RuntimeError` (in CI) when the YAML mount is missing. From the worktree-test script, the mount is absent — so locally the tests appear to "pass" by skipping, hiding the fact that the real-engine assertions never ran.

**Workaround** (used during Story 1.3 implementation): construct the `docker run` invocation by hand, adding the two missing `-e` + `-v` pairs and the cluster_credentials.yaml mount. ~10 lines of additional shell instead of one make-target line. Not catastrophic, but defeats the discoverability that `make test-worktree` was supposed to deliver.

## Why deferred

Out of scope for `infra_study_preflight_real_engine_integration`. The fix touches `scripts/run-tests-in-worktree.sh` (and possibly the Makefile target's argument list); the feature in flight is a test-code rewrite. Coupling the two would mix unrelated concerns in one PR.

## Canonical source-of-truth references

The two `*_FILE` env vars proposed below already have authoritative definitions elsewhere; the spec must NOT invent new names or mount paths.

| Env var | Canonical in-container path | Source-of-truth | Host secret file |
|---|---|---|---|
| `POSTGRES_PASSWORD_FILE` | `/run/secrets/postgres_password` | [`docker-compose.yml:69`](../../../../docker-compose.yml#L69) (migrate), [`:96`](../../../../docker-compose.yml#L96) (api), [`:154`](../../../../docker-compose.yml#L154) (worker) | `$MAIN_REPO/secrets/postgres_password` |
| `CLUSTER_CREDENTIALS_FILE` | `/run/secrets/cluster_credentials` | [`docker-compose.yml:102`](../../../../docker-compose.yml#L102) (api), [`:160`](../../../../docker-compose.yml#L160) (worker) | `$MAIN_REPO/secrets/cluster_credentials.yaml` |

The mount/env names in the worktree-test script MUST match these exactly so the resolved `Settings` object inside the one-shot container behaves identically to the long-running api/worker containers (cf. [`backend/app/core/settings.py:100-104`](../../../../backend/app/core/settings.py#L100-L104) for the `cluster_credentials_file` Pydantic field).

## Locked decisions

1. **`POSTGRES_PASSWORD_FILE` — required, fail-loud if missing.** Mirror the existing `DATABASE_URL_FILE` check at [`scripts/run-tests-in-worktree.sh:100-115`](../../../../scripts/run-tests-in-worktree.sh#L100-L115) exactly: validate `$MAIN_REPO/secrets/postgres_password` is readable; on failure print an `ERROR:` line + remediation hint pointing at `bash $MAIN_REPO/scripts/install.sh` and exit with a distinct non-zero code (suggest `5`, sequential to the DB-secret-missing `exit 4`). The DB secret is useless without the password — no defensible scenario exists where a worktree test should proceed with one but not the other.

2. **`CLUSTER_CREDENTIALS_FILE` — optional, mount-if-present.** Probe `$MAIN_REPO/secrets/cluster_credentials.yaml` and add the `-e` + `-v` pair to `ARGV` only if the file exists and is non-empty. When absent, skip the mount silently — unit tests, contract tests, and DB-only integration tests don't need cluster credentials, and the existing test-side skip gates (`@es_required`, `postgres_reachable()`, the FR-6 helper guard at [`test_es_overlap_probe_helpers.py:170-203`](../../../../backend/tests/integration/test_es_overlap_probe_helpers.py#L170-L203)) handle the unmounted case correctly. This is asymmetric with rule 1 by design: DB access is a baseline expectation for `make test-worktree`; cluster access is a per-test-suite escalation.

3. **Apply the same audit upstream in the Makefile target.** [`Makefile:65-66`](../../../../Makefile#L65-L66) currently shells through to the script with only `$(CMD)` forwarded. Once the script accepts the new mounts, the Makefile target needs no behavioral change — but the help text comment at line 65 should be refreshed to call out integration-test support.

## Proposed capabilities

1. **Add `POSTGRES_PASSWORD_FILE` env var + mount** to [`scripts/run-tests-in-worktree.sh:150-171`](../../../../scripts/run-tests-in-worktree.sh#L150-L171). Use the names from the source-of-truth table above. Validate the host file is readable before constructing `ARGV` (Locked decision 1).
2. **Add `CLUSTER_CREDENTIALS_FILE` env var + mount** for any test that touches `acquire_adapter()` or `seed_minimum_for_overlap_probe_real_engine()`. Conditional on host file existence per Locked decision 2.
3. **Document the env-var mount pattern** in [`docs/03_runbooks/parallel-worktrees.md`](../../../../docs/03_runbooks/parallel-worktrees.md) (specifically inside the existing §"Run tests safely" subsection at lines 29-62) so future test-infra changes that add new `*_FILE` env vars know to update both [`docker-compose.yml`](../../../../docker-compose.yml) AND the worktree-test script.

## Scope signals

- **Backend:** none.
- **Frontend:** none.
- **Infra:** ~10-15 lines in `scripts/run-tests-in-worktree.sh` + a paragraph in `parallel-worktrees.md`.
- **Migration:** none.

## Coordinates with

- **`infra_agent_sibling_worktree_isolation` Phase 2** (PR #249, merged 2026-05-25) — shipped `scripts/run-tests-in-worktree.sh` and the `make test-worktree` Makefile target. This idea patches that script in-place; no new files, no new make target.
- **`infra_study_preflight_real_engine_integration`** (PR #255, merged 2026-05-22) — the feature whose Story 1.3 implementation surfaced this gap. Its 5 rewritten AC tests + `seed_minimum_for_overlap_probe_real_engine()` helper work fine via the standalone `docker run` invocation documented in [`CLAUDE.md` §"Running tests against a sibling worktree (one-shot container recipe)"](../../../../CLAUDE.md#running-tests-against-a-sibling-worktree-one-shot-container-recipe) but skip via `make test-worktree`.
- **`infra_agent_sibling_worktree_isolation` Phase 3 idea** ([`phase3_idea.md`](../infra_agent_sibling_worktree_isolation/phase3_idea.md), Backlog) — a per-worktree `DATABASE_URL_FILE` override. Independent of this idea (this one just adds missing env propagation; Phase 3 is about per-worktree DB isolation), but the same script is the natural integration point for both, so a future implementer of either should re-check that the two changesets compose cleanly.

## Open questions for /spec-gen

1. **Should the script's `--dry-run` output explicitly list which optional mounts were skipped?** When `cluster_credentials.yaml` is absent, the dry-run printout will silently omit the `-e CLUSTER_CREDENTIALS_FILE=...` and `-v ...cluster_credentials.yaml:...` lines. An operator copy-pasting the dry-run output for a manual `docker run` won't know they need to add them. **Recommended default:** emit a `# skipped optional mount: CLUSTER_CREDENTIALS_FILE (host file not present)` line to stderr before the `docker` argv on stdout, so the visible-to-operator printout still pastes cleanly into a shell.
