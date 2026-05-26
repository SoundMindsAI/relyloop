# Feature Specification — Propagate `POSTGRES_PASSWORD_FILE` + optional `CLUSTER_CREDENTIALS_FILE` to `make test-worktree`

**Date:** 2026-05-25
**Status:** Draft
**Owners:** Eric Starr (Product + Engineering)
**Related docs:**
- [`idea.md`](idea.md) (origin brief, preflight-patched 2026-05-25)
- [`implementation_plan.md`](implementation_plan.md) (TBD — next stage)
- [`scripts/run-tests-in-worktree.sh`](../../../../scripts/run-tests-in-worktree.sh) (the script being patched, Phase 2 of `infra_agent_sibling_worktree_isolation`)
- [`backend/tests/conftest.py`](../../../../backend/tests/conftest.py) (`postgres_reachable()` skip gate at lines 50-72)
- [`docker-compose.yml`](../../../../docker-compose.yml) (canonical source-of-truth for the env-var names + container mount paths)

---

## 1) Purpose

- **Problem:** `make test-worktree` (the wrapper around `scripts/run-tests-in-worktree.sh` shipped by `infra_agent_sibling_worktree_isolation` Phase 2, PR #249) propagates only `DATABASE_URL_FILE` from the main worktree's secrets into the one-shot container. The test-side `postgres_reachable()` skip gate at [`backend/tests/conftest.py:50-72`](../../../../backend/tests/conftest.py#L50-L72) requires BOTH `DATABASE_URL_FILE` AND `POSTGRES_PASSWORD_FILE` to declare the DB reachable. Result: every Postgres-touching integration test invoked via `make test-worktree CMD="pytest backend/tests/integration -v"` reports `SKIPPED [..] Postgres not reachable — see docs/03_runbooks/local-dev.md` with a misleading reason — the actual cause is the missing env var + bind mount in the script, not unreachable Postgres. The same gap applies to `CLUSTER_CREDENTIALS_FILE` for any test that touches `acquire_adapter()` or the new `seed_minimum_for_overlap_probe_real_engine()` helper from `infra_study_preflight_real_engine_integration` (PR #255, merged 2026-05-22).
- **Outcome:** `scripts/run-tests-in-worktree.sh` propagates `POSTGRES_PASSWORD_FILE` unconditionally (fail-loud if `$MAIN_REPO/secrets/postgres_password` is missing — mirroring the existing `DATABASE_URL_FILE` prerequisite check) and `CLUSTER_CREDENTIALS_FILE` conditionally (mounted only when `$MAIN_REPO/secrets/cluster_credentials.yaml` is readable and non-empty; non-dry-run invocations skip silently if absent/empty/unreadable; `--dry-run` invocations emit a single FR-3 hint to stderr so operators inspecting the constructed argv see what was skipped and why). After this fix, integration tests run via `make test-worktree CMD="pytest backend/tests/integration -v"` execute their assertions instead of skipping; `make test-worktree` becomes the canonical worktree-test entrypoint for integration suites, not just unit suites.
- **Non-goal:** No per-worktree `DATABASE_URL_FILE` override (that's `infra_agent_sibling_worktree_isolation` Phase 3, tracked at [`../infra_agent_sibling_worktree_isolation/phase3_idea.md`](../infra_agent_sibling_worktree_isolation/phase3_idea.md), Backlog priority). No introspection of `docker-compose.yml` to auto-discover `*_FILE` env vars (static list with cited line numbers is simpler; the regression test pins it). No changes to `docker-compose.yml`, `backend/app/`, `ui/`, `migrations/`, or `prompts/`. Backend test changes are limited to `backend/tests/unit/scripts/test_run_tests_in_worktree.py`.

## 2) Current state audit

### Existing implementations

- [`scripts/run-tests-in-worktree.sh`](../../../../scripts/run-tests-in-worktree.sh) (192 lines, shipped by PR #249) — the script being patched. Key shape verified by direct read:
  - DB-secret prerequisite check at lines 100-115 (`SECRET_FILE="$MAIN_REPO/secrets/database_url"` → exit 4 with `ERROR:` + Rule #2 reference + `scripts/install.sh` hint if missing).
  - ARGV block at lines 150-170 (closing paren at 171): passes `-e DATABASE_URL_FILE=/run/secrets/database_url`, `-e PYTHONDONTWRITEBYTECODE=1`, `-e RELYLOOP_IN_WORKTREE_CONTAINER=1`, and mounts the DB secret + 10 source paths (DB secret + CLAUDE.md + 9 worktree-source paths).
  - Existing exit codes: `2` (usage error), `3` (worktree detection failure), `4` (missing DB secret). Next sequential available: `5`.
  - Override env-var `RELYLOOP_MAIN_REPO` resolves the main worktree path (Phase 2 added this for testability — hermetic tests inject a fake main repo via `tmp_path` + `RELYLOOP_MAIN_REPO=`).
- [`backend/tests/conftest.py:50-72`](../../../../backend/tests/conftest.py#L50-L72) — `postgres_reachable()` helper. Line 57: `if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"): return False`. The `db_session` fixture at lines 104-117 skips with the misleading reason `"Postgres not reachable — see docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."` when this returns False.
- [`backend/app/core/settings.py:100-104`](../../../../backend/app/core/settings.py#L100-L104) — `cluster_credentials_file: Path | None = Field(default=None, ...)`. Optional pre-`infra_adapter_elastic`. Pydantic-settings auto-maps the field to the `CLUSTER_CREDENTIALS_FILE` env var.
- [`docker-compose.yml`](../../../../docker-compose.yml) — canonical env-var → mount-path source-of-truth. Direct grep verified:
  - `POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password` at line 26 (postgres init), 69 (api), 96 (worker), 154 (migrate).
  - `CLUSTER_CREDENTIALS_FILE: /run/secrets/cluster_credentials` at line 102 (worker), 160 (migrate). NOT in `api` — the api service doesn't need cluster credentials, only the worker (which runs `acquire_adapter()`) does.
- [`Makefile:65-66`](../../../../Makefile#L65-L66) — `test-worktree` target. Thin wrapper: `@bash scripts/run-tests-in-worktree.sh $(if $(CMD),--cmd "$(CMD)")`. Help-line at line 65 reads: `## Run tests in a one-shot container that mounts the sibling worktree (use CMD="..." to override). Phase 2 of infra_agent_sibling_worktree_isolation.`
- [`docs/03_runbooks/parallel-worktrees.md`](../../../../docs/03_runbooks/parallel-worktrees.md) (88 lines) — operator runbook for the parallel-worktree workflow. §"Run tests safely" at lines 29-62. This is where the env-var-propagation guidance from FR-3 lands.
- [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) (330 lines, 6 tests) — existing smoke test suite for the script. Patterns established:
  - `_make_fake_main(tmp_path, *, with_secret: bool = True)` helper (lines 53-66) creates a hermetic fake main-repo dir with `secrets/database_url`. Will need to extend to also create `secrets/postgres_password` (always) and optionally `secrets/cluster_credentials.yaml`.
  - `TestDryRunArgvShape::test_dry_run_outputs_canonical_argv` asserts `v_mount_count == 11` at line 139. **This must change** to 12 after the unconditional `POSTGRES_PASSWORD_FILE` mount lands (DB secret + postgres_password + CLAUDE.md + 9 source paths = 12). With cluster_credentials present, 13.
  - `TestDryRunArgvShape::test_required_bind_mounts_all_present` enumerates the 11 mount targets at lines 164-176. **Must gain** `/run/secrets/postgres_password:ro` and conditionally `/run/secrets/cluster_credentials:ro`.
- [`CLAUDE.md` §"Running tests against a sibling worktree (one-shot container recipe)"](../../../../CLAUDE.md#running-tests-against-a-sibling-worktree-one-shot-container-recipe) — the verbose one-shot `docker run` recipe shipped by `infra_agent_sibling_worktree_isolation` Phase 1. **Will need updating** to add the two new `-e` flags + `-v` mounts for `POSTGRES_PASSWORD_FILE` (required) and `CLUSTER_CREDENTIALS_FILE` (optional). The CLAUDE.md recipe is the "operator-readable explanation of what the script does internally" — keeping it in sync with the script is a documentation maintenance contract.
- [`backend/tests/integration/test_es_overlap_probe_helpers.py:170-203`](../../../../backend/tests/integration/test_es_overlap_probe_helpers.py#L170-L203) — the FR-6 helper guard in `test_seed_helper_missing_local_es_credentials`. Routes missing `local-es` key in `cluster_credentials_yaml` to `pytest.skip` (locally) or `RuntimeError` (CI). After this fix, when `CLUSTER_CREDENTIALS_FILE` is mounted via `make test-worktree`, this test executes its raises-on-missing-`local-es`-key path correctly instead of silently skipping the entire suite.
- [`backend/tests/integration/test_studies_api.py:827-944`](../../../../backend/tests/integration/test_studies_api.py#L827-L944) — the 5 rewritten AC tests from `infra_study_preflight_real_engine_integration` that invoke `seed_minimum_for_overlap_probe_real_engine()`. Same beneficiary set as above.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| (none — no URLs being moved or renamed) | — | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | `v_mount_count == 11` (line 139) | 1 | Update to 12 (DB-secret + postgres_password + CLAUDE.md + 9 source = 12 with cluster_credentials absent; 13 when present). Test must also exercise both states (absent vs present). |
| [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | mount-target enumeration (lines 164-176) | 1 | Add `/run/secrets/postgres_password:ro` to the unconditional list; add a separate test for the conditional `/run/secrets/cluster_credentials:ro` mount when the host file exists. |
| [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | `_make_fake_main` helper (lines 53-66) | 1 | Extend to create `secrets/postgres_password` (always) and optionally `secrets/cluster_credentials.yaml` (when caller passes `with_cluster_credentials=True`). |

No backend integration test changes — the integration tests are the beneficiaries (they currently skip; they will run). No frontend tests touched.

### Existing behaviors affected by scope change

- **`make test-worktree` integration-test behavior.** Current: integration tests invoked via `make test-worktree CMD="pytest backend/tests/integration -v"` skip with `"Postgres not reachable"`. New: same tests execute. Decision needed: no — this is the entire point of the fix; the change is unambiguously a bug fix.
- **`make test-worktree` failure mode when `$MAIN_REPO/secrets/postgres_password` is missing.** Current: passes silently because the script doesn't check; tests then skip with `"Postgres not reachable"`. New: script exits 5 with an `ERROR:` line naming the missing file + Rule #2 + `scripts/install.sh` remediation hint, BEFORE constructing `docker run`. Decision needed: no — Locked decision 1 in the idea.
- **`make test-worktree` behavior when `$MAIN_REPO/secrets/cluster_credentials.yaml` is missing.** Current: passes silently because the script doesn't reference cluster credentials at all. New: script proceeds normally; the `CLUSTER_CREDENTIALS_FILE` env var + mount are simply omitted from the `ARGV` for that invocation; `--dry-run` output emits a one-line `# skipped optional mount: CLUSTER_CREDENTIALS_FILE (host file not present)` comment to stderr so operators copy-pasting the dry-run output understand what's missing. Decision needed: no — Locked decision 2 in the idea, plus the dry-run-stderr-hint open question is resolved below.

---

## 3) Scope

### In scope

- A small (~15-20 LOC) patch to [`scripts/run-tests-in-worktree.sh`](../../../../scripts/run-tests-in-worktree.sh) adding:
  1. A new prerequisite-check block after line 115 (after the existing DB-secret check) for `$MAIN_REPO/secrets/postgres_password`. Mirrors the DB-secret block's shape; exits `5` on missing/unreadable with an `ERROR:` line naming Rule #2 + `scripts/install.sh`.
  2. A new conditional-mount block before the `ARGV=(` line (~line 150) that probes `$MAIN_REPO/secrets/cluster_credentials.yaml`. Sets two new bash variables — `CLUSTER_CREDS_HOST` (the host path, empty string if absent) and `CLUSTER_CREDS_MOUNT_ARGS` (the `-e` + `-v` pair if present, empty array if absent) — that the `ARGV` block splices in.
  3. Two new `-e` + `-v` pairs in the `ARGV` block: `-e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` + `-v "$MAIN_REPO/secrets/postgres_password:/run/secrets/postgres_password:ro"` (unconditional), and the conditional `CLUSTER_CREDS_MOUNT_ARGS` splice (mount target `/run/secrets/cluster_credentials`, matching `docker-compose.yml` lines 102, 160).
  4. A one-line stderr emission in `--dry-run` mode when the cluster_credentials mount is skipped: `# skipped optional mount: CLUSTER_CREDENTIALS_FILE (host file not present at $MAIN_REPO/secrets/cluster_credentials.yaml)`. Stays on stderr so stdout (the `docker` argv) pastes cleanly into a shell.
- A small (~10-15 LOC) edit to the existing smoke-test file at [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py):
  1. Extend `_make_fake_main(...)` to write `secrets/postgres_password` (always) and accept a new `with_cluster_credentials: bool = False` parameter.
  2. Update `test_dry_run_outputs_canonical_argv` to assert `v_mount_count == 12` (was 11), AND that `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` and `/run/secrets/postgres_password:ro` appear in argv.
  3. Update `test_required_bind_mounts_all_present` to include `/run/secrets/postgres_password:ro`.
  4. Add **three** new tests:
     - `test_errors_on_missing_postgres_password_file` — fake main repo has `database_url` but not `postgres_password`; assert exit 5 + stderr mentions the missing file + Rule #2 + `scripts/install.sh`.
     - `test_cluster_credentials_mounted_when_host_file_present` — fake main has all three secrets (database_url, postgres_password, cluster_credentials.yaml); assert `v_mount_count == 13` AND `CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials` + `/run/secrets/cluster_credentials:ro` appear in argv.
     - `test_cluster_credentials_skipped_when_host_file_absent_or_empty` — pytest-parametrized across THREE skip modes: (a) host file absent; (b) host file present but zero bytes; (c) host file unreadable (`chmod 0o000`, skipped when running as root since chmod doesn't block root reads). For each mode, assert `v_mount_count == 12` (no cluster_credentials mount); assert stderr contains the FR-3 `# skipped optional mount: CLUSTER_CREDENTIALS_FILE` hint in `--dry-run` mode AND that `CLUSTER_CREDENTIALS_FILE` does NOT appear in argv.
- A ≤25-line update to [`docs/03_runbooks/parallel-worktrees.md`](../../../../docs/03_runbooks/parallel-worktrees.md) §"Run tests safely" (lines 29-62) documenting:
  1. That integration tests are now supported via `make test-worktree CMD="pytest backend/tests/integration -v"` (previously: docs only mentioned the unit-test default).
  2. The two new `*_FILE` env vars the script now propagates (required: `POSTGRES_PASSWORD_FILE`; optional: `CLUSTER_CREDENTIALS_FILE`).
  3. **A standing rule (the durable contract this feature is also delivering):** future test-infra changes that add a new `*_FILE` env var to `docker-compose.yml` MUST update BOTH (a) the corresponding compose service env block AND (b) the prerequisite-check + ARGV block in `scripts/run-tests-in-worktree.sh`, AND (c) the canonical recipe in `CLAUDE.md` §"Running tests against a sibling worktree (one-shot container recipe)". Skipping any of the three causes silent-skip / silent-mount-absent regressions in worktree-tested suites.
- A ≤10-line update to [`CLAUDE.md` §"Running tests against a sibling worktree (one-shot container recipe)"](../../../../CLAUDE.md#running-tests-against-a-sibling-worktree-one-shot-container-recipe) — add the two new `-e` and `-v` lines to the fenced bash recipe (one always, one with a `# Optional: only if ./secrets/cluster_credentials.yaml exists` comment line above it). The FR-7 regression test from `infra_agent_sibling_worktree_isolation` at [`backend/tests/unit/docs/test_claude_md_sections.py`](../../../../backend/tests/unit/docs/test_claude_md_sections.py) asserts "exactly one fenced `bash` block in the section" — adding lines INSIDE the existing block doesn't violate that invariant, but the test must continue to pass and the absent-bare-`DATABASE_URL` and worker-attribution invariants stay intact.

### Out of scope

- Per-worktree `DATABASE_URL_FILE` override (Phase 3 of `infra_agent_sibling_worktree_isolation`, tracked at [`../infra_agent_sibling_worktree_isolation/phase3_idea.md`](../infra_agent_sibling_worktree_isolation/phase3_idea.md)). Independent design — Phase 3 is about per-worktree DB isolation; this is about propagating existing main-repo secrets.
- Any change to `docker-compose.yml`. The compose env definitions are already correct; only the worktree-test script needs to learn what compose already does.
- Any introspection / auto-discovery of `*_FILE` env vars from `docker-compose.yml`. Static list with cited line numbers + a smoke-test guard is simpler and easier to PR-review than dynamic YAML parsing. (Mirrors the parent feature's OQ-2 deferral rationale.)
- A `pytest.skip` reason-string improvement to the `db_session` fixture (so the skip says "POSTGRES_PASSWORD_FILE missing" instead of "Postgres not reachable" when only the env var is the cause, not actual unreachability). This is a separate ergonomics improvement to `backend/tests/conftest.py` — out of scope here. Captured as a tangential discovery below.
- Any change to `backend/`, `ui/`, `migrations/`, `prompts/`, or any non-test backend file. This is purely a script + documentation + script-test patch.

### API convention check

N/A — no endpoints added or modified. This is an infra-script + docs feature. The §8 endpoint surface section below is N/A accordingly.

### Phase boundaries (single-phase)

**Phase 1 (this spec — single phase):** All capabilities ship in one PR. Rationale: the implement-over-defer rubric (CLAUDE.md "Tangential discoveries" §"Inline-fix vs idea-file rubric") applies — the work is ≤250 LOC across script + tests + 2 docs, no cross-subsystem mixing (all infra), no operator-judgment forks remain (the idea pre-locked the two open decisions: `POSTGRES_PASSWORD_FILE` required-fail-loud + `CLUSTER_CREDENTIALS_FILE` optional-mount-if-present), all design forks have clear defaults. No `phase2_idea.md` will be created — there is nothing to defer.

## 4) Product principles and constraints

- **Mirror `docker-compose.yml` exactly.** Container mount paths (`/run/secrets/postgres_password`, `/run/secrets/cluster_credentials`) and env-var names (`POSTGRES_PASSWORD_FILE`, `CLUSTER_CREDENTIALS_FILE`) MUST match the canonical source-of-truth in `docker-compose.yml`. Inventing new paths or renaming env vars would break Pydantic-settings' field-to-env-var auto-binding and produce mysterious null-Settings failures inside the one-shot container.
- **Fail-loud on missing required secrets; skip-silent on missing optional ones.** The asymmetry between `POSTGRES_PASSWORD_FILE` (required, exit 5) and `CLUSTER_CREDENTIALS_FILE` (optional, mount-if-present) is intentional and locked in the idea: DB access is a baseline expectation for `make test-worktree`; cluster access is a per-suite escalation that already has test-side skip gates (`@es_required`, `postgres_reachable()`, FR-6 helper guards) to handle absence.
- **CLAUDE.md Rule #2 (secrets via mounted files).** Every new env-var addition MUST use the `*_FILE`-mounted-secret pattern — bare env vars are forbidden. This rule is already in force across the codebase; the new mounts simply add two more entries to the existing pattern.
- **`--dry-run` output stays copy-paste-clean.** Stdout MUST be just the `docker` argv. Optional-mount-skip notices go to stderr so operators piping `--dry-run` output into a shell don't get broken commands. (The existing test pattern `subprocess.run(..., capture_output=True)` separately captures stdout and stderr, so the new stderr emission is straightforwardly testable.)
- **Forward-only.** No backwards-compat shim for the old single-secret behavior. After this PR, `make test-worktree` requires `$MAIN_REPO/secrets/postgres_password` exists. Operators who haven't run `make up` recently will see the fail-loud error and run `bash scripts/install.sh` to regenerate; that's the documented remediation.

### Anti-patterns

- **Do not** add a `POSTGRES_PASSWORD` bare env var as a "convenience fallback" when the file is missing. Violates Rule #2; defeats the secrets-management story.
- **Do not** rename the in-container mount path (e.g., `/run/secrets/postgres-pw` or `/postgres_password`). The Pydantic-settings auto-binding reads the canonical compose-mounted path; deviating produces null-Settings failures that look unrelated to the change.
- **Do not** introduce a new `*_FILE` env var or mount whose name doesn't match a `docker-compose.yml` declaration. The point of this fix is symmetry between the long-running compose containers and the one-shot worktree-test container; inventing new names breaks the invariant.
- **Do not** make `CLUSTER_CREDENTIALS_FILE` required. Unit tests, contract tests, and DB-only integration tests don't need cluster credentials; forcing the operator to maintain `secrets/cluster_credentials.yaml` for unit-test invocations of `make test-worktree` is a regression of the original feature's "minimal prerequisites" promise.
- **Do not** parse `docker-compose.yml` at script startup to auto-discover `*_FILE` vars. Beyond the scope of this PR; would couple the script to YAML structure; the failure mode (parsing error in unrelated compose edit breaks `make test-worktree`) is worse than the failure mode this fix addresses.
- **Do not** combine this change with the Phase 3 per-worktree DB override design. Phase 3 (tracked at [`../infra_agent_sibling_worktree_isolation/phase3_idea.md`](../infra_agent_sibling_worktree_isolation/phase3_idea.md)) is independent; mixing scope blurs review.
- **Do not** emit the `# skipped optional mount: ...` hint to stdout. Stdout is the `docker` argv (literally copy-pasted by operators). Mixing prose into stdout breaks the copy-paste contract. Stderr only.

## 5) Assumptions and dependencies

- **Dependency:** None at the code level. The work is isolated to `scripts/`, `backend/tests/unit/scripts/`, `docs/03_runbooks/`, `CLAUDE.md`, and a small `state.md` end-of-feature entry.
- **Dependency (informational):** `docker-compose.yml`'s env-var → mount-path declarations for `POSTGRES_PASSWORD_FILE` (lines 26, 69, 96, 154) and `CLUSTER_CREDENTIALS_FILE` (lines 102, 160) are the source-of-truth. If a future PR renames or relocates either, the script MUST be updated in the same PR. The smoke tests don't enforce line-number freshness (intentionally — line numbers shift on every compose edit), but they do enforce the in-container mount path (`/run/secrets/postgres_password`, `/run/secrets/cluster_credentials`) which is what the binding actually depends on.
- **Dependency (informational):** `backend/tests/conftest.py:postgres_reachable()` at line 57 is the reason `POSTGRES_PASSWORD_FILE` is required (not optional). If a future PR removes the env-var presence check from `postgres_reachable()`, the fail-loud guard in the worktree-test script becomes overly strict. Captured in §16 rollout.
- **Risk if missing:** Zero external dependencies. The change is contained.

## 6) Actors and roles

- Primary actor(s): autonomous agent or human operator running `make test-worktree` from a sibling worktree to execute integration tests against the main worktree's live Compose stack.
- Role model: N/A — RelyLoop MVP1 is single-tenant + no auth.
- Permission boundaries: N/A — infra-script + docs only.

### Authorization

N/A — single-tenant install, no auth surface (MVP1; multi-tenant lands at MVP4).

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md). MVP1 has no audit-event surface; even at MVP2+, an infra-script change emits no audit events (rule applies to state-mutating endpoints / service functions, not test-runner scripts).

## 7) Functional requirements

### FR-1: Required `POSTGRES_PASSWORD_FILE` propagation with fail-loud prerequisite check

- Requirement:
  - The script **MUST** add a new prerequisite-check block after the existing DB-secret check (currently at [`scripts/run-tests-in-worktree.sh:100-115`](../../../../scripts/run-tests-in-worktree.sh#L100-L115)) that validates `$MAIN_REPO/secrets/postgres_password` exists and is readable.
  - On missing/unreadable file, the script **MUST** exit `5` (next sequential after the existing `4` for DB secret) with an `ERROR:` line to stderr that names:
    1. The missing path (`$MAIN_REPO/secrets/postgres_password`).
    2. CLAUDE.md Absolute Rule #2 (secrets-via-mounted-files).
    3. The remediation command (`bash $MAIN_REPO/scripts/install.sh`).
  - The error message format **MUST** mirror the existing DB-secret error at lines 101-114 — same shape, same level of operator detail, same level of indentation. This keeps the script's error-message family visually coherent.
  - The script **MUST** pass `-e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` and `-v "$MAIN_REPO/secrets/postgres_password:/run/secrets/postgres_password:ro"` in the `ARGV` block. The in-container mount path **MUST** be exactly `/run/secrets/postgres_password` (matches `docker-compose.yml` lines 69, 96, 154).
- Notes: Mirrors the existing DB-secret prerequisite pattern. The fail-loud-vs-skip-silent asymmetry with `CLUSTER_CREDENTIALS_FILE` (FR-2) is intentional per Locked decision 1 in the idea.

### FR-2: Optional `CLUSTER_CREDENTIALS_FILE` propagation with mount-if-present semantics

- Requirement:
  - The script **MUST** add a probe before the `ARGV=(` line that tests whether `$MAIN_REPO/secrets/cluster_credentials.yaml` is readable AND non-empty (`[[ -r "$MAIN_REPO/secrets/cluster_credentials.yaml" && -s "$MAIN_REPO/secrets/cluster_credentials.yaml" ]]`). The readability check parallels FR-1's required-secret check shape; the non-empty check guards against an accidentally-truncated file (e.g., interrupted `install.sh`).
  - When the probe succeeds, the script **MUST** include `-e CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials` AND `-v "$MAIN_REPO/secrets/cluster_credentials.yaml:/run/secrets/cluster_credentials:ro"` in the `ARGV` block. The in-container mount path **MUST** be exactly `/run/secrets/cluster_credentials` (matches `docker-compose.yml` lines 102, 160 — note the host file has a `.yaml` suffix but the in-container path does NOT, mirroring compose's convention exactly).
  - When the probe fails (file absent, empty, or unreadable), the script **MUST NOT** add either the `-e` or the `-v` to `ARGV`.
  - **In non-dry-run mode**, the script **MUST NOT** print any error or warning to stderr for the optional-skip path (operators who never registered a cluster shouldn't see warnings every invocation). The single FR-3 stderr hint is the only diagnostic permitted for the optional-skip path, and it fires only when `--dry-run` is also active.
  - Implementation approach: collect the conditional flags into a bash array (e.g., `CLUSTER_CREDS_ARGS=()`) populated in the probe block, then splice it into `ARGV` via `"${CLUSTER_CREDS_ARGS[@]+"${CLUSTER_CREDS_ARGS[@]}"}"` (the `+` indirection is bash-3-safe for empty arrays — `bash --version` on macOS still ships 3.2). Implementer may choose a different idiom (e.g., inlined conditional `if`) as long as the result is identical and the script remains POSIX-bash-friendly.
- Notes: Locked decision 2 in the idea. The skip-silent behavior in non-dry-run mode preserves the script's "unit-test mode" contract; the FR-3 hint provides diagnostic visibility for operators inspecting the constructed argv.

### FR-3: `--dry-run` stderr hint when optional cluster_credentials mount is skipped

- Requirement:
  - When the script is invoked with `--dry-run` AND the FR-2 probe failed (cluster_credentials.yaml absent, empty, or unreadable), the script **MUST** emit exactly one line to **stderr** (not stdout):
    ```
    # skipped optional mount: CLUSTER_CREDENTIALS_FILE (host file not present, empty, or unreadable at <absolute path to $MAIN_REPO/secrets/cluster_credentials.yaml>)
    ```
  - The message **MUST** include the resolved absolute path (so an operator can copy it, fix the file's existence/contents/perms, and re-run if they actually wanted the mount).
  - The wording "not present, empty, or unreadable" covers all three FR-2 failure modes in a single message. Implementers SHOULD NOT branch on which of the three triggered — bash's `[[ -r && -s ]]` already collapses the distinction at the probe site, and operators reading the hint primarily care that the mount didn't happen, not which gate failed.
  - The message **MUST NOT** appear in non-`--dry-run` invocations (those just run docker; the in-container skip gates handle the absence loudly enough).
  - The message **MUST NOT** appear when the FR-2 probe succeeded (the mount happened; no skip occurred).
  - Stdout **MUST** remain just the `docker <argv>` printout, one arg per line, exactly as today. Operators piping `--dry-run` output through `| sh` or copy-pasting must continue to get a valid command.
- Notes: Resolves the lone open question from the idea ("should `--dry-run` indicate which optional mounts were skipped?") with the recommended default. Stderr-not-stdout preserves the copy-paste contract.

### FR-4: CLAUDE.md one-shot recipe synchronized with the script

- Requirement:
  - The CLAUDE.md §"Running tests against a sibling worktree (one-shot container recipe)" fenced `bash` block **MUST** be updated to include the same two new `-e` + `-v` pairs that FR-1 + FR-2 add to the script:
    1. Always: `-e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` and `-v "$MAIN_REPO/secrets/postgres_password:/run/secrets/postgres_password:ro"`.
    2. Conditionally — preceded by a single `# Optional: only if ./secrets/cluster_credentials.yaml exists in the main repo` comment line: `-e CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials` and `-v "$MAIN_REPO/secrets/cluster_credentials.yaml:/run/secrets/cluster_credentials:ro"`.
  - The edit **MUST NOT** add a second fenced `bash` block (the FR-7 regression test from `infra_agent_sibling_worktree_isolation` Phase 1 — at [`backend/tests/unit/docs/test_claude_md_sections.py`](../../../../backend/tests/unit/docs/test_claude_md_sections.py) — asserts exactly one).
  - The edit **MUST NOT** introduce the literal substring `DATABASE_URL=postgresql://` in the section body (the FR-7 regression test asserts its absence to enforce Rule #2).
  - The edit **MUST NOT** attribute `./migrations/`, `./alembic.ini`, or `./samples/` to `worker` in the Compose-anchored paths catalog above the recipe (the FR-7 regression test asserts this attribution invariant).
- Notes: Keeps CLAUDE.md (agent-facing) in sync with the script (operator-facing). The CLAUDE.md recipe is what an agent reads at session start; if it drifts from the script, agents debugging weird test-worktree failures will re-derive incorrectly.

### FR-5: Runbook update at `parallel-worktrees.md` §"Run tests safely"

- Requirement:
  - [`docs/03_runbooks/parallel-worktrees.md`](../../../../docs/03_runbooks/parallel-worktrees.md) §"Run tests safely" (lines 29-62) **MUST** be updated to:
    1. State that `make test-worktree CMD="pytest backend/tests/integration -v"` now executes integration tests instead of skipping them.
    2. List the prerequisites the script enforces: `$MAIN_REPO/secrets/database_url` (required, was already there) and `$MAIN_REPO/secrets/postgres_password` (required, new). Note that both are auto-generated by `bash scripts/install.sh` / `make up`, so the typical operator never sees these errors.
    3. State the optional behavior: `$MAIN_REPO/secrets/cluster_credentials.yaml`, if present, is mounted so cluster-credential-dependent tests (`acquire_adapter()`, `seed_minimum_for_overlap_probe_real_engine()`) execute correctly. If absent, those tests skip via their existing test-side gates.
    4. Add a short "Adding a new `*_FILE` env var" subsection (≤8 lines) stating the durable contract: when a contributor adds a new `*_FILE` env var to `docker-compose.yml`, the same PR MUST update (a) `scripts/run-tests-in-worktree.sh` (add the prerequisite check + mount + dry-run hint if optional), (b) `CLAUDE.md` §"Running tests against a sibling worktree (one-shot container recipe)" (add the matching `-e` + `-v` lines), and (c) this runbook subsection (extend the list). Without all three, worktree-tested suites that depend on the new env var will silently skip.
  - Total addition: ≤25 lines. The existing "Residual root-file risk" subsection at lines 48-56 stays intact; the new content slots between the existing CMD-override example (lines 33-38) and the "Residual root-file risk" subsection.
- Notes: The runbook is the human-facing operating procedure. Without this update, the durable contract from §3 ("future test-infra changes that add a new `*_FILE` env var MUST update all three places") lives only in this spec and evaporates after the PR merges.

### FR-6: Smoke-test coverage update

- Requirement:
  - [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) **MUST** be extended:
    1. The `_make_fake_main(tmp_path, *, with_secret: bool = True)` helper at lines 53-66 **MUST** gain a new parameter `with_cluster_credentials: bool = False` AND **MUST** unconditionally create `secrets/postgres_password` (with a non-empty placeholder, e.g., `"fakepw\n"`) whenever `with_secret=True`. When `with_cluster_credentials=True`, it also creates `secrets/cluster_credentials.yaml` with a non-empty placeholder (e.g., `"local-es: {username: x, password: y}\n"`).
    2. The existing `test_dry_run_outputs_canonical_argv` assertion `v_mount_count == 11` (line 139) **MUST** change to `v_mount_count == 12` (DB secret + postgres_password + CLAUDE.md + 9 source paths). The test **MUST** also assert that `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` and a mount targeting `/run/secrets/postgres_password:ro` appear in argv.
    3. The existing `test_required_bind_mounts_all_present` enumeration (lines 164-176) **MUST** add `/run/secrets/postgres_password:ro`.
  - Three new tests **MUST** be added:
    1. `test_errors_on_missing_postgres_password_file` — fake main has `database_url` but not `postgres_password`; assert `result.returncode == 5` AND stderr contains `"secrets/postgres_password"` AND `"Rule #2"` AND `"scripts/install.sh"`. Mirrors the existing `test_errors_on_missing_secret_file` shape.
    2. `test_cluster_credentials_mounted_when_host_file_present` — fake main has all three secrets via `_make_fake_main(tmp_path, with_cluster_credentials=True)`; assert exit 0, `v_mount_count == 13`, AND `CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials` + `/run/secrets/cluster_credentials:ro` appear in argv.
    3. `test_cluster_credentials_skipped_when_host_file_absent_or_empty` — pytest-parametrized across THREE skip modes: (a) host file absent; (b) host file present but zero bytes; (c) host file unreadable (mode `0o000`). For each mode, fake main has database_url + postgres_password configured + the parameterized cluster_credentials.yaml state. Assert exit 0, `v_mount_count == 12`, `CLUSTER_CREDENTIALS_FILE` does NOT appear in argv, AND stderr contains the FR-3 hint substring `"skipped optional mount: CLUSTER_CREDENTIALS_FILE"`. Parametrizing all three failure modes in one test covers AC-4 (absent), AC-5 (empty), and the new FR-2 unreadable case without test sprawl.
  - All new tests **MUST** respect the existing module-level skip (`pytestmark` at lines 43-50: skips when `RELYLOOP_IN_WORKTREE_CONTAINER=1`). No new fixtures or markers required.
  - All new tests **MUST** invoke the script via `--dry-run` only — no `docker` execution. CI hermeticity preserved.
- Notes: 3 new tests + 3 modifications to existing tests/helper. Test file grows from ~330 to ~430 lines. Sub-second runtime. The parametrized skip-mode test is the substantive sharpening from GPT-5.5 cycle-1 findings #3 + #4.

## 8) API and data contract baseline

### 8.1 Endpoint surface

N/A — no endpoints added or modified.

### 8.2 Contract rules

N/A.

### 8.3 Response examples

N/A.

### 8.4 Enumerated value contracts

N/A — no filters, status badges, sort keys, or dropdowns.

### 8.5 Error code catalog

The script's exit-code "catalog" (script-internal, not an API):

| Code | Trigger | Meaning |
|------|---------|---------|
| `0` | success | argv constructed; docker invoked (or dry-run printed) |
| `2` | usage error | invalid CLI flag or `--cmd` without value (existing) |
| `3` | worktree detection failure | not invoked from inside a git worktree, or `RELYLOOP_MAIN_REPO` override points at non-existent path (existing) |
| `4` | missing DB secret | `$MAIN_REPO/secrets/database_url` not readable (existing) |
| `5` | **NEW** — missing postgres-password secret | `$MAIN_REPO/secrets/postgres_password` not readable (this spec, FR-1) |

Existing codes are immutable (operators may grep for them in CI failures). The new code is the next sequential.

## 9) Data model and state transitions

### New/changed entities

N/A — no tables added or modified. No migration required.

### Required invariants

- **In-container mount paths match compose source-of-truth.** `/run/secrets/postgres_password` MUST match `docker-compose.yml` lines 69, 96, 154; `/run/secrets/cluster_credentials` MUST match `docker-compose.yml` lines 102, 160. Enforced by FR-6 test assertions on the in-container mount-target strings.
- **`POSTGRES_PASSWORD_FILE` propagation is unconditional; `CLUSTER_CREDENTIALS_FILE` is conditional on host-file readability AND non-emptiness** (the FR-2 probe is `[[ -r && -s ]]`; absent/empty/unreadable all collapse to the skip path). Enforced by the symmetric pair of FR-6 tests `test_cluster_credentials_mounted_when_host_file_present` and `test_cluster_credentials_skipped_when_host_file_absent_or_empty` (the latter parametrized across all three skip modes per AC-4).
- **Stdout in `--dry-run` mode contains only the `docker` argv (no prose).** Enforced by the existing `test_dry_run_outputs_canonical_argv` (continues to assert `argv_lines[0] == "docker"`) and reinforced by the new `test_cluster_credentials_skipped_when_host_file_absent` (asserts skipped-mount hint is on stderr, not stdout).
- **Existing exit-code semantics are immutable.** Codes 2, 3, 4 retain their existing meanings; code 5 is the new addition. Enforced by the existing `test_errors_on_missing_secret_file` (still asserts the DB-secret missing path → exit 4 stays intact) plus the new `test_errors_on_missing_postgres_password_file` (asserts the new path → exit 5).
- **CLAUDE.md §"Running tests against a sibling worktree" still satisfies the FR-7 regression test from `infra_agent_sibling_worktree_isolation` Phase 1.** Specifically: exactly one fenced bash block remains; no `DATABASE_URL=postgresql://` substring; `worker` still not attributed to `./migrations/`, `./alembic.ini`, or `./samples/` in the Compose-anchored paths catalog above the recipe. Enforced by re-running [`backend/tests/unit/docs/test_claude_md_sections.py`](../../../../backend/tests/unit/docs/test_claude_md_sections.py) (no test changes needed; the test should continue to pass on the edited CLAUDE.md).

### State transitions

N/A.

### Idempotency/replay behavior

N/A — the script is one-shot per invocation; `docker run --rm` cleans up the container; no persistent state.

## 10) Security, privacy, and compliance

- **Threats:**
  1. `secrets/postgres_password` content leaks into a log or process listing if the script accidentally echoes it.
  2. An operator misreads the new error message and types the password directly into a shell command instead of regenerating via `install.sh`.
- **Controls:**
  1. The script NEVER reads the secret file content (only checks file existence with `[[ -r ... ]]`). The error message names the file path, not the content. Mirrors the existing `database_url` handling.
  2. The error message format explicitly points at `bash $MAIN_REPO/scripts/install.sh` as the remediation — no inline password-creation hint that could mislead.
  3. The new mount uses `:ro` (read-only); the in-container code cannot mutate the host secret file.
  4. `$MAIN_REPO/secrets/postgres_password` and `cluster_credentials.yaml` are already in `.gitignore` (the existing `secrets/*` pattern; only `.gitkeep` is committed). No risk of accidentally committing the new mount targets.
- **Secrets/key handling:** No new secrets introduced. Existing `secrets/postgres_password` and `secrets/cluster_credentials.yaml` files are mounted read-only into the one-shot container, exactly as `docker-compose.yml` does for the long-running api / worker / migrate containers.
- **Auditability:** N/A — infra-script, no API.
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

### Information architecture

- **Surface:** terminal output of `make test-worktree` (and indirectly `bash scripts/run-tests-in-worktree.sh`). No web UI.
- **Labeling taxonomy:** error messages follow the existing script's `ERROR: ...` + indented remediation-hint pattern. The new `# skipped optional mount: ...` stderr message follows the bash comment convention (starts with `#`) so it's visually distinct from `ERROR:` lines.
- **Content hierarchy:** prerequisite checks fire BEFORE argv construction; argv construction fires BEFORE dispatch (or dry-run print). Operators see errors in the natural read-order.
- **Progressive disclosure:** N/A — terminal output is linear.
- **Relationship to existing pages:** the script is itself a Phase 2 product of `infra_agent_sibling_worktree_isolation`; this spec extends its surface without reorganizing it.

### Tooltips and contextual help

N/A — no UI surface.

### Primary flows

1. **Operator runs `make test-worktree CMD="pytest backend/tests/integration -v"` from a sibling worktree, with a fully-bootstrapped main repo.** Script auto-detects both worktrees, validates DB secret + postgres_password, probes for cluster_credentials.yaml (present in this case — operator has registered an Elasticsearch cluster), constructs argv with all 13 mounts, invokes docker. Integration tests execute; assertions run; results stream back. Operator sees pass/fail per test instead of `SKIPPED [..] Postgres not reachable`.
2. **Operator runs `make test-worktree` (no override, default unit-test cmd) from a sibling worktree, in a minimal setup.** Same path but `cluster_credentials.yaml` is absent. Script constructs argv with 12 mounts (no CLUSTER_CREDENTIALS). Unit tests execute; no skips (they don't need any of the propagated secrets). Operator sees unit tests pass.

### Edge/error flows

- **`$MAIN_REPO/secrets/postgres_password` is missing.** Script exits 5 with `ERROR: missing or unreadable Postgres password secret at: $MAIN_REPO/secrets/postgres_password` + indented remediation hint. Operator runs `bash scripts/install.sh` (or `make up`), retries. (This is the new error path.)
- **`$MAIN_REPO/secrets/cluster_credentials.yaml` is missing AND the operator runs `make test-worktree CMD="pytest backend/tests/integration -v"`.** Script runs successfully (cluster_credentials is optional). Tests that need cluster credentials (the 5 rewritten AC tests from `infra_study_preflight_real_engine_integration` + `test_seed_helper_missing_local_es_credentials`) skip via their existing test-side gates with the right reason strings — operator sees specific skip messages naming the missing `local-es` key in `cluster_credentials_yaml`, not the misleading "Postgres not reachable" from before.
- **Operator runs `bash scripts/run-tests-in-worktree.sh --dry-run` to inspect the constructed command before executing.** Stdout contains the `docker ...` argv (copy-pasteable); stderr contains the `# skipped optional mount: CLUSTER_CREDENTIALS_FILE (...)` hint if applicable. Operator can redirect stderr if they don't care: `bash scripts/run-tests-in-worktree.sh --dry-run 2>/dev/null`. Note: the Makefile target `make test-worktree` does NOT pass arbitrary flags through to the script (`Makefile:65-66` forwards only `CMD=`); `--dry-run` must be invoked against the script directly. Adding a `--dry-run` pass-through to the Makefile target is out of scope here (would belong to a hypothetical Phase-2-style extension of the parent feature).
- **Pre-existing test bug: a downstream contributor edits `docker-compose.yml` to add a new `*_FILE` env var without updating `scripts/run-tests-in-worktree.sh`.** Symptom: the new compose-secret-dependent test skips silently via `make test-worktree`. Mitigation: FR-5 adds a durable contract to the runbook. The runbook is the procedure; PR review is the enforcement. Not enforced by an automated regression test in this spec (the parent feature's OQ-2 already deferred YAML introspection; the same trade-off applies here).

## 12) Given/When/Then acceptance criteria

### AC-1: `POSTGRES_PASSWORD_FILE` propagation is unconditional

- **Given** the patched script and a fake main-repo with both `secrets/database_url` and `secrets/postgres_password` present
- **When** invoked with `--dry-run`
- **Then** stdout contains `-e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` AND `-v "<fake_main>/secrets/postgres_password:/run/secrets/postgres_password:ro"`
- **And** `v_mount_count == 12` (DB secret + postgres_password + CLAUDE.md + 9 source paths)
- **And** exit code is 0
- Example values:
  - Cmd: `bash scripts/run-tests-in-worktree.sh --dry-run` (with `RELYLOOP_MAIN_REPO=<tmp_path>/fake-main`)
  - Stdout substring (one line each): `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password`, `<tmp_path>/fake-main/secrets/postgres_password:/run/secrets/postgres_password:ro`
  - Test: `backend/tests/unit/scripts/test_run_tests_in_worktree.py::TestDryRunArgvShape::test_dry_run_outputs_canonical_argv` (modified to assert 12 + new strings)

### AC-2: Missing `postgres_password` fails loud with exit 5

- **Given** a fake main-repo with `secrets/database_url` present but `secrets/postgres_password` absent
- **When** the script is invoked with `--dry-run`
- **Then** exit code is `5`
- **And** stderr contains the substrings `"secrets/postgres_password"`, `"Rule #2"`, `"scripts/install.sh"`
- **And** stdout is empty (no argv printed — the check fires before argv construction)
- Example values:
  - Test: `test_errors_on_missing_postgres_password_file` (new)
  - Expected stderr format (rough): `ERROR: missing or unreadable Postgres password secret at: <path>\n       CLAUDE.md Absolute Rule #2 requires secrets-via-mounted-files; bare\n       POSTGRES_PASSWORD= env vars are forbidden. Regenerate via:\n         bash <path>/scripts/install.sh`

### AC-3: `CLUSTER_CREDENTIALS_FILE` is mounted when the host file exists and non-empty

- **Given** a fake main-repo with `secrets/database_url`, `secrets/postgres_password`, AND `secrets/cluster_credentials.yaml` (non-empty) present
- **When** invoked with `--dry-run`
- **Then** stdout contains `-e CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials` AND `-v "<fake_main>/secrets/cluster_credentials.yaml:/run/secrets/cluster_credentials:ro"`
- **And** `v_mount_count == 13`
- **And** exit code is 0
- **And** stderr does NOT contain `"skipped optional mount"`
- Example values:
  - Test: `test_cluster_credentials_mounted_when_host_file_present` (new)
  - Helper: `_make_fake_main(tmp_path, with_cluster_credentials=True)`

### AC-4: `CLUSTER_CREDENTIALS_FILE` is silently omitted when the host file is absent, empty, or unreadable

- **Given** a fake main-repo with `secrets/database_url` and `secrets/postgres_password` configured, AND `secrets/cluster_credentials.yaml` in one of three skip-mode states: (a) absent, (b) present but zero bytes, (c) present, non-empty, but unreadable (mode `0o000`)
- **When** invoked with `--dry-run`
- **Then** stdout does NOT contain `CLUSTER_CREDENTIALS_FILE` or `/run/secrets/cluster_credentials`
- **And** `v_mount_count == 12`
- **And** stderr contains exactly one line matching `# skipped optional mount: CLUSTER_CREDENTIALS_FILE (host file not present, empty, or unreadable at <fake_main>/secrets/cluster_credentials.yaml)`
- **And** exit code is 0
- Example values:
  - Test: `test_cluster_credentials_skipped_when_host_file_absent_or_empty` (new, pytest-parametrized across all three skip modes)
  - Mode (c) skips at the pytest level when `os.geteuid() == 0` (root can read 0o000 files; the chmod-based assertion would falsely pass)

### AC-5: AC-4's empty-file subcase is the same code path

- **Given** AC-4 mode (b) — zero-byte `cluster_credentials.yaml`
- **When** the FR-2 probe `[[ -r && -s ]]` runs
- **Then** `-s` returns false (empty file), the probe fails, and the script omits the mount + emits the FR-3 stderr hint
- Example values: covered by the parametrized test above; no separate test required. AC-5 exists as a discoverable named criterion for empty-file behavior but the implementation collapses into AC-4's parametrization.

### AC-6: Runbook documents the new propagation + the durable contract

- **Given** the post-merge state of `docs/03_runbooks/parallel-worktrees.md`
- **When** a reader scans §"Run tests safely"
- **Then** they find: a sentence stating integration tests are supported via `make test-worktree CMD="..."`; the two new `*_FILE` env vars listed (one required, one optional, with the correct semantics); the standing "Adding a new `*_FILE` env var" subsection with the three-place update rule
- **And** the section's length grows by ≤25 lines vs. pre-PR baseline

### AC-7: CLAUDE.md one-shot recipe is updated and FR-7 regression test still passes

- **Given** the post-merge state of `CLAUDE.md`
- **When** the FR-7 regression test from `infra_agent_sibling_worktree_isolation` Phase 1 ([`backend/tests/unit/docs/test_claude_md_sections.py`](../../../../backend/tests/unit/docs/test_claude_md_sections.py)) runs
- **Then** all 5 tests pass (section exists, ordering correct, no bare `DATABASE_URL=postgresql://`, correct worker attribution in catalog, exactly one fenced bash block)
- **And** the fenced bash block contains lines for both `POSTGRES_PASSWORD_FILE` (always) and `CLUSTER_CREDENTIALS_FILE` (with a `# Optional: ...` comment line above it)

## 13) Non-functional requirements

- **Performance:** script invocation overhead unchanged (~10ms host-side before `docker run` dispatch). Tests run sub-second.
- **Reliability:** new fail-loud path eliminates the silent-skip regression class.
- **Operability:** error messages include the missing file path + the remediation command (`bash scripts/install.sh`) — operator needs no external context to recover.
- **Accessibility/usability:** N/A — terminal output.

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/scripts/`):** the patched + extended `test_run_tests_in_worktree.py` covers FR-1 (AC-1, AC-2), FR-2 (AC-3, AC-4, AC-5), FR-3 (AC-4), FR-6 (the whole file). 3 new tests + 3 modifications to existing tests. Sub-second runtime.
- **Unit tests (`backend/tests/unit/docs/`):** re-run the existing `test_claude_md_sections.py` to verify the CLAUDE.md edits (FR-4 / AC-7) don't violate any FR-7 invariants from the parent feature. No new tests needed.
- **Integration tests (`backend/tests/integration/`):** N/A directly — but the **point** of this spec is that existing Postgres-touching integration tests stop skipping when invoked via `make test-worktree CMD="pytest backend/tests/integration -v"`. Operator-path verification (below) confirms this end-to-end.
- **Contract tests (`backend/tests/contract/`):** N/A — no API.
- **E2E tests (`ui/tests/e2e/`):** N/A — no UI.
- **Operator-path verification (manual, one-time per PR — mandated by CLAUDE.md Step 3 + `impl-execute` ad-hoc-mode operator-path step):** before push, run `make test-worktree CMD="pytest backend/tests/integration/test_studies_api.py -v"` from a sibling worktree against the live Compose stack. Expected result: tests execute (no `Postgres not reachable` skips); a representative subset passes (the rest may legitimately skip via `@es_required` if the operator hasn't seeded ES, which is fine). Document the actual pass/fail/skip counts in the PR description.

## 15) Documentation update requirements

- `docs/01_architecture/`: no updates (no architecture changes).
- `docs/02_product/`: no updates (no product surface changes).
- `docs/03_runbooks/parallel-worktrees.md`: FR-5 (≤25-line addition to §"Run tests safely", new "Adding a new `*_FILE` env var" subsection).
- `docs/04_security/`: no updates (no new secrets, no new threat model entries — `secrets/*` is already gitignored, the mount is `:ro`, the script never reads file content).
- `docs/05_quality/`: no updates.
- `CLAUDE.md` §"Running tests against a sibling worktree (one-shot container recipe)": FR-4 (~10-line addition to the fenced bash block).
- `state.md`: end-of-feature update — add a "recent changes" entry describing the script extension + the runbook update.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A — script edit, single PR, takes effect immediately on merge.
- **Migration/backfill expectations:** N/A — no schema, no data.
- **Operational readiness gates:**
  - The fail-loud guard (FR-1) requires `$MAIN_REPO/secrets/postgres_password` to exist. Every operator who has ever run `make up` or `bash scripts/install.sh` already has this file (auto-generated). For the rare contributor who has the repo checked out but has never bootstrapped, the first `make test-worktree` invocation after the PR merges will fail loud with the new error message and the remediation hint. This is the desired behavior (don't fail late inside docker with a confusing error).
- **Release gate:** standard pre-push gate (lint + typecheck + test-unit on the changed files + `make test-worktree` operator-path verification). No CI workflow changes.
- **Inheritance assumption (the script is read at every `make test-worktree` invocation):** after the PR merges, every subsequent invocation across all worktrees uses the patched script — no propagation delay. Sibling worktrees branched off `main` before the PR retain the old script until they rebase; the symptom of running the old script (silent integration-test skips) is the same as pre-PR, so no breakage — just no benefit until rebase.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (required postgres_password) | AC-1, AC-2 | Story 1 (script edit) | `test_dry_run_outputs_canonical_argv` (mod), `test_required_bind_mounts_all_present` (mod), `test_errors_on_missing_postgres_password_file` (new) | CLAUDE.md (FR-4), parallel-worktrees.md (FR-5) |
| FR-2 (optional cluster_credentials) | AC-3, AC-4, AC-5 | Story 1 | `test_cluster_credentials_mounted_when_host_file_present` (new), `test_cluster_credentials_skipped_when_host_file_absent_or_empty` (new, parametrized across absent/empty/unreadable) | CLAUDE.md (FR-4), parallel-worktrees.md (FR-5) |
| FR-3 (--dry-run stderr hint) | AC-4, AC-5 | Story 1 | `test_cluster_credentials_skipped_when_host_file_absent_or_empty` (new) | parallel-worktrees.md (FR-5) — implicit |
| FR-4 (CLAUDE.md sync) | AC-7 | Story 2 (docs) | re-run existing `test_claude_md_sections.py` (no change) | CLAUDE.md |
| FR-5 (runbook update) | AC-6 | Story 2 | n/a (review-gated) | parallel-worktrees.md |
| FR-6 (smoke-test coverage) | AC-1, AC-2, AC-3, AC-4, AC-5 | Story 1 | the file itself | n/a |

## 18) Definition of feature done

- [ ] All 7 acceptance criteria (AC-1..AC-7) pass.
- [ ] All test layers green: `make test-unit` (covers `test_run_tests_in_worktree.py` + `test_claude_md_sections.py`); operator-path `make test-worktree CMD="pytest backend/tests/integration/test_studies_api.py -v"` from a sibling worktree shows integration tests executing instead of skipping.
- [ ] Documentation merged: CLAUDE.md, `docs/03_runbooks/parallel-worktrees.md`, `state.md`.
- [ ] No open questions remain in §19.
- [ ] `git diff` shows changes only in: `scripts/run-tests-in-worktree.sh`, `backend/tests/unit/scripts/test_run_tests_in_worktree.py`, `docs/03_runbooks/parallel-worktrees.md`, `CLAUDE.md`, `state.md`, and the planned-features → implemented-features folder move artifacts. No backend, frontend, migration, or compose changes.

## 19) Open questions and decision log

### Open questions

None — all open questions from the idea ("should --dry-run indicate skipped optional mounts?") are resolved via FR-3 (yes, emit to stderr only, in --dry-run mode only).

### Decision log

- **2026-05-25 — D-0 (added during GPT-5.5 cycle 1 review): FR-2 probe checks readability AND non-emptiness.** Rationale: GPT-5.5 cycle-1 finding #4 — `[[ -s ]]` alone allows the mounted-but-unreadable-by-the-container-user edge case. Tightening to `[[ -r && -s ]]` parallels FR-1's `[[ -r ]]` check on the required secret and produces semantically symmetric pre-flight validation across both probes. The FR-3 hint message subsumes all three failure modes under one wording ("not present, empty, or unreadable") rather than branching at the probe site.
- **2026-05-25 — D-0a (added during GPT-5.5 cycle 2 review): unreadable-mode test subcase skips when test process is root.** Rationale: GPT-5.5 cycle-2 finding #2 — `chmod 0o000` doesn't block root-owned reads, so the unreadable parametrization would assert against a mount-still-happened state under root and falsely fail. Defensive skip at the parametrize level (`pytest.skip("requires non-root euid")` when `os.geteuid() == 0`) keeps the test correct across both unprivileged developer environments (where the chmod check is meaningful) and the rare root-runner edge case (CI runners, in-container nested invocations that the `RELYLOOP_IN_WORKTREE_CONTAINER` module skip already protects from, but defense-in-depth is cheap).
- **2026-05-25 — D-1: `POSTGRES_PASSWORD_FILE` is REQUIRED, fail-loud on missing.** Rationale: the DB secret is useless without the password (the Postgres password is what `postgres_reachable()` ultimately needs to verify connectivity). No defensible scenario where a worktree test should proceed with one but not the other. Mirrors the existing `DATABASE_URL_FILE` prerequisite-check shape exactly. Locked from idea Locked Decision 1.
- **2026-05-25 — D-2: `CLUSTER_CREDENTIALS_FILE` is OPTIONAL, mount-if-present.** Rationale: unit tests, contract tests, and DB-only integration tests don't need cluster credentials. Forcing the operator to maintain `cluster_credentials.yaml` for unit-test invocations of `make test-worktree` would regress the script's "minimal prerequisites" promise. Test-side skip gates (`@es_required`, `postgres_reachable()`, FR-6 helper guards) handle the absent case correctly. Locked from idea Locked Decision 2.
- **2026-05-25 — D-3: New exit code is `5`.** Rationale: existing codes (2 usage, 3 worktree, 4 DB-secret) are immutable contracts; 5 is next sequential. Operators grepping CI failures for exit codes shouldn't see existing codes change meaning.
- **2026-05-25 — D-4: `--dry-run` stderr hint goes to stderr, not stdout.** Rationale: stdout in `--dry-run` is the `docker` argv — operators copy-paste it directly into a shell. Mixing prose into stdout breaks the copy-paste contract. Stderr is the right channel for diagnostic-but-non-error annotations.
- **2026-05-25 — D-5: Single-phase delivery.** Rationale: ≤250 LOC across script + tests + 2 docs; no cross-subsystem mixing; no operator-judgment forks remain after D-1/D-2. The implement-over-defer rubric (CLAUDE.md §"Tangential discoveries / Inline-fix vs idea-file rubric") applies; no `phase2_idea.md` needed.
- **2026-05-25 — D-6: No YAML-introspection auto-discovery of `*_FILE` env vars.** Rationale: same trade-off as parent feature's OQ-2 deferral. Static list + cited line numbers + a smoke-test guard is simpler and easier to PR-review than dynamic YAML parsing. The durable contract in FR-5 (runbook) substitutes prose discipline for automated discovery.
- **2026-05-25 — D-7: Captured tangential discovery (out of scope here):** the `db_session` fixture in `backend/tests/conftest.py:108-117` skips with the misleading reason `"Postgres not reachable — see docs/03_runbooks/local-dev.md"` even when the actual cause is the env-var presence check failing at line 57 (not actual TCP unreachability). Improving the skip-reason message to differentiate the two failure modes is a separate ergonomics fix. Tracked: if the operator decides the ergonomics improvement is worth a separate PR, capture as a new `chore_db_session_skip_reason_disambiguation` idea file. Not blocked by this spec.
