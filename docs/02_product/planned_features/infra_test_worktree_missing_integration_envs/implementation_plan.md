# Implementation Plan — Propagate `POSTGRES_PASSWORD_FILE` + optional `CLUSTER_CREDENTIALS_FILE` to `make test-worktree`

**Date:** 2026-05-25
**Status:** Ready for Execution
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md` §"Absolute Rules" #2 (secrets via mounted files)](../../../../CLAUDE.md), [`docker-compose.yml`](../../../../docker-compose.yml) (canonical env-var → mount-path source-of-truth)

---

## 0) Planning principles

- **Spec traceability first:** every story/task maps to one or more FR IDs from the spec.
- **Mirror compose exactly:** env var names + in-container mount paths come from `docker-compose.yml` lines 26/69/96/154 (`POSTGRES_PASSWORD_FILE`) and lines 102/160 (`CLUSTER_CREDENTIALS_FILE`). The plan does NOT introduce new names; Pydantic-settings auto-binding depends on the exact canonical names.
- **Fail-loud for required secrets, skip-silent for optional:** mirrors the spec's D-1 / D-2 lock.
- **Keep increments narrow enough to verify independently:** Story 1.1 ships the script + smoke tests in one PR-ready unit (TDD-shaped — tests verify the script change); Story 1.2 ships the doc sync once Story 1.1's behavior is locked.
- **No new infra layers:** no new file types, no new test directories, no new make targets. This plan extends existing surfaces (`scripts/run-tests-in-worktree.sh` + its existing smoke test file + the existing CLAUDE.md recipe + the existing parallel-worktrees runbook).

## 1) Scope traceability (FR → stories)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (required `POSTGRES_PASSWORD_FILE` propagation) | Story 1.1 | Script edit + new prereq check + ARGV mount |
| FR-2 (optional `CLUSTER_CREDENTIALS_FILE` propagation) | Story 1.1 | Script edit + probe + conditional ARGV mount |
| FR-3 (--dry-run stderr hint when cluster_credentials skipped) | Story 1.1 | Script edit |
| FR-4 (CLAUDE.md one-shot recipe synchronized) | Story 1.2 | Doc edit |
| FR-5 (runbook update at `parallel-worktrees.md`) | Story 1.2 | Doc edit |
| FR-6 (smoke-test coverage update) | Story 1.1 | Test file extension (3 new tests + 3 modifications to existing tests/helper) |

**Phase coverage:** spec is single-phase (per D-5); this plan covers all FRs. No deferred phases. **No `phase2_idea.md` needed.**

## 2) Delivery structure

This plan uses **Epic → Story → Tasks → DoD**. One epic, two stories. Story 1.1 contains the production change + its smoke tests (TDD-shaped). Story 1.2 contains the documentation sync that consumes Story 1.1's behavior.

### Conventions

- Script: bash, `set -euo pipefail`, error messages mirror existing `DATABASE_URL_FILE`-missing block's shape (file path on first line, indented remediation hints below).
- Tests: `subprocess.run(..., capture_output=True, text=True, check=False)`; assert against `--dry-run` stdout/stderr only; never invoke `docker`. Pattern source: existing tests in [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py).
- All script edits respect CLAUDE.md Rule #2: no bare `DATABASE_URL=` or `POSTGRES_PASSWORD=` env vars; only `*_FILE` mounts.
- All docs edits respect the FR-7 regression test from `infra_agent_sibling_worktree_isolation` Phase 1 ([`backend/tests/unit/docs/test_claude_md_sections.py`](../../../../backend/tests/unit/docs/test_claude_md_sections.py)): section ordering, no bare `DATABASE_URL=postgresql://`, no `worker` attribution in the catalog for migrations/alembic/samples, exactly one fenced bash block.

### AI Agent Execution Protocol

0. **Load context:** read `state.md`, `architecture.md`, `feature_spec.md`, and the existing `scripts/run-tests-in-worktree.sh` + `backend/tests/unit/scripts/test_run_tests_in_worktree.py` end-to-end before editing.
1. **Story 1.1 first:** the script + tests must land as one atomic change. The 11→12→13 mount-count assertion in `test_dry_run_outputs_canonical_argv` is the canary — if the script's ARGV doesn't produce exactly 12 mounts (no cluster credentials present in test) or 13 (present), the test fails and the script is wrong.
2. **Run smoke tests after every script edit:** `uv run pytest backend/tests/unit/scripts/test_run_tests_in_worktree.py -v`. Fix → re-run loop. Sub-second runtime; treat as the inner dev loop.
3. **Operator-path verification before push:** from inside a sibling worktree (create one via `git worktree add /private/tmp/relyloop-<slug> -b <branch>` if needed), invoke `make test-worktree CMD="pytest backend/tests/integration/test_studies_api.py -v"` against the live Compose stack. The sibling-worktree requirement is non-negotiable per spec §14 — a `RELYLOOP_MAIN_REPO=$(pwd)` override from the main repo is NOT a substitute (it bypasses the worktree-detection code path the script actually executes for real operators). Expected: tests execute (no `Postgres not reachable` skips); document pass/fail/skip counts in PR description.
4. **Story 1.2 after 1.1's smoke tests are green:** the docs describe the shipped behavior. Don't write the docs against intent — write them against what Story 1.1 actually produces.
5. **After Story 1.2:** re-run `uv run pytest backend/tests/unit/docs/test_claude_md_sections.py -v` to confirm the CLAUDE.md edits don't violate any of the parent feature's FR-7 invariants.
6. **Attach evidence in PR:** smoke-test output (all green), operator-path command + output (integration tests executing), the FR-7 doc-checker re-run (all green).

---

## Epic 1 — Propagate the two `*_FILE` env vars + sync docs

### Story 1.1 — Patch `run-tests-in-worktree.sh` to propagate `POSTGRES_PASSWORD_FILE` (required) and `CLUSTER_CREDENTIALS_FILE` (optional); extend smoke tests

**Outcome:** integration tests invoked via `make test-worktree CMD="pytest backend/tests/integration -v"` execute their assertions instead of skipping with the misleading `"Postgres not reachable"` reason; cluster-credential-dependent tests (5 rewritten AC tests from `infra_study_preflight_real_engine_integration`, plus the FR-6 helper guard test) gain working credentials when the host file is present.

**FRs covered:** FR-1, FR-2, FR-3, FR-6.

**New files**

None. This story extends existing files only.

**Modified files**

| File | Change |
|---|---|
| [`scripts/run-tests-in-worktree.sh`](../../../../scripts/run-tests-in-worktree.sh) | Add postgres-password prereq check after line 115 (exit 5 on missing/unreadable). Add cluster-credentials probe block before the `ARGV=(` line at ~line 150. Add 2 new `-e` + `-v` pairs to the `ARGV` block (postgres_password always; cluster_credentials conditionally via a bash array splice). Add 1 new stderr emission in `--dry-run` mode when cluster_credentials probe fails. Total LOC: ~25-30 lines added. |
| [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | Extend `_make_fake_main()` helper (add `secrets/postgres_password` always; add `with_cluster_credentials: bool = False` parameter). Update `test_dry_run_outputs_canonical_argv` mount count: `v_mount_count == 11` → `== 12`; assert `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` and `/run/secrets/postgres_password:ro` in argv. Update `test_required_bind_mounts_all_present` to include `/run/secrets/postgres_password:ro`. Add 3 new tests: `test_errors_on_missing_postgres_password_file`, `test_cluster_credentials_mounted_when_host_file_present`, `test_cluster_credentials_skipped_when_host_file_absent_or_empty` (parametrized across absent / empty / unreadable). Total LOC: ~90-110 lines added. |

**Endpoints**

N/A — script edit, no API surface.

**Key interfaces**

The script's behavior changes are best described by the new ARGV shape:

```bash
# scripts/run-tests-in-worktree.sh — new prereq check (insert after line 115)
PG_PASSWORD_FILE="$MAIN_REPO/secrets/postgres_password"
if [[ ! -r "$PG_PASSWORD_FILE" ]]; then
  echo "ERROR: missing or unreadable Postgres password secret at: $PG_PASSWORD_FILE" >&2
  echo "       CLAUDE.md Absolute Rule #2 requires secrets-via-mounted-files; bare" >&2
  echo "       POSTGRES_PASSWORD= env vars are forbidden. Regenerate via:" >&2
  echo "         bash $MAIN_REPO/scripts/install.sh" >&2
  echo "       (or 'make up' from the main worktree, which auto-generates secrets" >&2
  echo "       on first run by invoking scripts/install.sh)." >&2
  exit 5
fi

# scripts/run-tests-in-worktree.sh — new optional probe (insert before ARGV=( at ~line 150)
CLUSTER_CREDS_HOST="$MAIN_REPO/secrets/cluster_credentials.yaml"
CLUSTER_CREDS_ARGS=()
if [[ -r "$CLUSTER_CREDS_HOST" && -s "$CLUSTER_CREDS_HOST" ]]; then
  CLUSTER_CREDS_ARGS=(
    -e "CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials"
    -v "$CLUSTER_CREDS_HOST:/run/secrets/cluster_credentials:ro"
  )
elif [[ "$DRY_RUN" -eq 1 ]]; then
  echo "# skipped optional mount: CLUSTER_CREDENTIALS_FILE (host file not present, empty, or unreadable at $CLUSTER_CREDS_HOST)" >&2
fi

# scripts/run-tests-in-worktree.sh — updated ARGV (modify the existing block)
ARGV=(
  run
  --rm
  --user root
  --network "$NETWORK_NAME"
  -e "DATABASE_URL_FILE=/run/secrets/database_url"
  -e "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password"   # NEW
  -e "PYTHONDONTWRITEBYTECODE=1"
  -e "RELYLOOP_IN_WORKTREE_CONTAINER=1"
  -v "$SECRET_FILE:/run/secrets/database_url:ro"
  -v "$PG_PASSWORD_FILE:/run/secrets/postgres_password:ro"      # NEW
  "${CLUSTER_CREDS_ARGS[@]+"${CLUSTER_CREDS_ARGS[@]}"}"          # NEW — conditional splice
  -v "$WORKTREE_ROOT/CLAUDE.md:/app/CLAUDE.md:ro"
  -v "$WORKTREE_ROOT/backend:/app/backend"
  # ... rest unchanged (lines 161-170)
)
```

(The bash-3-safe `+` indirection on the array splice survives macOS's `bash 3.2`; implementer may use an `if … then … fi` block instead if preferred, as long as ARGV remains a single contiguous bash array.)

**Test helper changes:**

```python
# backend/tests/unit/scripts/test_run_tests_in_worktree.py:53-66 — extended helper
def _make_fake_main(
    tmp_path: Path,
    *,
    with_secret: bool = True,
    with_cluster_credentials: bool = False,
) -> Path:
    """Build a fake main-repo dir. Always writes postgres_password when with_secret=True."""
    fake_main = tmp_path / "fake-main"
    (fake_main / "secrets").mkdir(parents=True)
    if with_secret:
        (fake_main / "secrets" / "database_url").write_text(
            "postgresql+asyncpg://relyloop:fake@postgres/relyloop\n"
        )
        (fake_main / "secrets" / "postgres_password").write_text("fakepw\n")  # NEW
    if with_cluster_credentials:
        (fake_main / "secrets" / "cluster_credentials.yaml").write_text(
            "local-es: {username: x, password: y}\n"
        )  # NEW
    return fake_main
```

**Tasks**

1. Read [`scripts/run-tests-in-worktree.sh`](../../../../scripts/run-tests-in-worktree.sh) end-to-end (192 lines) to confirm current exit-code semantics, the DB-secret error-message format, and the exact ARGV-block shape.
2. Read [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) end-to-end (330 lines) to confirm the existing test patterns: `_make_fake_main` helper, `_run` subprocess wrapper, `pytestmark` skip, `v_mount_count == 11` assertion shape.
3. Edit the script: insert the postgres-password prereq check immediately after the existing DB-secret check block (currently ends at line 115). Use the exact error-message format above. Verify with `bash -n scripts/run-tests-in-worktree.sh` (syntax check) and `shellcheck` (if available).
4. Edit the script: insert the cluster-credentials probe block immediately before the `ARGV=(` line (currently line 150). Splice the conditional `CLUSTER_CREDS_ARGS` array into ARGV. Keep the existing array structure intact; just add the two new unconditional `-e` + `-v` lines for postgres_password and the conditional splice line.
5. Edit the script: confirm the FR-3 stderr hint emits ONLY when both conditions are true (probe failed AND `--dry-run` mode active). The probe block above handles this with `elif [[ "$DRY_RUN" -eq 1 ]]`.
6. Edit the test file: extend `_make_fake_main` per the snippet above.
7. Edit the test file: update `test_dry_run_outputs_canonical_argv` — change `v_mount_count == 11` to `== 12` AND add assertions for `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` and `/run/secrets/postgres_password:ro` in argv.
8. Edit the test file: update `test_required_bind_mounts_all_present` — add `/run/secrets/postgres_password:ro` to the enumerated mount-target list.
9. Add new test `test_errors_on_missing_postgres_password_file` — fake main has `database_url` but not `postgres_password` (call `_make_fake_main(tmp_path)` then `(fake_main / "secrets" / "postgres_password").unlink()`); assert `result.returncode == 5`, stderr contains `"secrets/postgres_password"`, `"Rule #2"`, `"scripts/install.sh"`. Mirror the shape of the existing `test_errors_on_missing_secret_file` at lines 185-213.
10. Add new test `test_cluster_credentials_mounted_when_host_file_present` — call `_make_fake_main(tmp_path, with_cluster_credentials=True)`; assert `result.returncode == 0`, `v_mount_count == 13` (use the same counting logic as `test_dry_run_outputs_canonical_argv` at lines 136-138), AND `CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials` + `/run/secrets/cluster_credentials:ro` appear in argv.
11. Add new test `test_cluster_credentials_skipped_when_host_file_absent_or_empty` — pytest-parametrized across three IDs: `"absent"`, `"empty"`, `"unreadable"`. Use `pytest.mark.parametrize` with a setup-callable that constructs the cluster_credentials.yaml in each mode. For `"unreadable"`, after writing the file, `os.chmod(..., 0o000)` then `try/finally` to restore perms on teardown; skip with `pytest.skip("requires non-root euid")` when `os.geteuid() == 0` (per spec D-0a). For each mode assert: `result.returncode == 0`, `v_mount_count == 12`, `CLUSTER_CREDENTIALS_FILE` NOT in argv, stderr contains `"skipped optional mount: CLUSTER_CREDENTIALS_FILE"`.
12. Run the smoke-test suite: `uv run pytest backend/tests/unit/scripts/test_run_tests_in_worktree.py -v`. All 9 tests (6 existing + 3 new) must pass; sub-second runtime expected.
13. Operator-path verification: from inside a sibling worktree at `/private/tmp/relyloop-<slug>/` (create one via `git worktree add /private/tmp/relyloop-<slug> -b <branch-name>` if not already on one), invoke `make test-worktree CMD="pytest backend/tests/integration/test_studies_api.py -v"`. **`RELYLOOP_MAIN_REPO=$(pwd)` from the main repo is NOT an acceptable substitute** — it bypasses the script's worktree-detection code path (`git rev-parse --show-toplevel` at line 82) that real operators execute, and the spec §14 gate exists specifically to prove this path works end-to-end. Expected output: tests execute (no `Postgres not reachable` skips); the 5 rewritten overlap-probe AC tests should pass against the live ES service container (or `@es_required`-skip cleanly if ES is not seeded). Capture stdout+stderr; attach to PR description.

**Definition of Done (DoD)**

- [ ] `scripts/run-tests-in-worktree.sh` adds POSTGRES_PASSWORD_FILE unconditionally + CLUSTER_CREDENTIALS_FILE conditionally per the snippets above.
- [ ] `bash -n scripts/run-tests-in-worktree.sh` exits 0 (syntax valid).
- [ ] `bash scripts/run-tests-in-worktree.sh --dry-run` (from the main worktree with all 3 secrets present) prints 13 `-v` mounts and includes both new env vars in stdout.
- [ ] `bash scripts/run-tests-in-worktree.sh --dry-run` with `cluster_credentials.yaml` absent prints 12 `-v` mounts AND emits the `# skipped optional mount: CLUSTER_CREDENTIALS_FILE` hint to stderr (not stdout).
- [ ] `bash scripts/run-tests-in-worktree.sh --dry-run` with `postgres_password` absent exits 5 with the FR-1 error message on stderr.
- [ ] `uv run pytest backend/tests/unit/scripts/test_run_tests_in_worktree.py -v` — all 9 tests pass (6 existing + 3 new; the parametrized test counts as 3 subtests under one ID).
- [ ] Operator-path verification documented in PR description: `make test-worktree CMD="pytest backend/tests/integration/test_studies_api.py -v"` shows the 5 rewritten overlap-probe AC tests EXECUTING (not skipping with `Postgres not reachable`).
- [ ] All AC-1, AC-2, AC-3, AC-4, AC-5 from spec §12 verified.

### Story 1.2 — Sync CLAUDE.md one-shot recipe and `parallel-worktrees.md` runbook with the new propagation behavior

**Outcome:** the agent-facing CLAUDE.md recipe and the human-facing parallel-worktrees runbook both describe the now-shipped propagation behavior. The standing "Adding a new `*_FILE` env var" contract is added to the runbook so future test-infra changes know to update all three places (`docker-compose.yml`, the script, CLAUDE.md).

**FRs covered:** FR-4, FR-5.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`CLAUDE.md`](../../../../CLAUDE.md) (line 410 onwards — §"Running tests against a sibling worktree (one-shot container recipe)") | Add 2 new unconditional lines inside the fenced `bash` block (~lines 420-444): `-e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password \` (after the existing DATABASE_URL_FILE line) and `-v "$MAIN_REPO/secrets/postgres_password:/run/secrets/postgres_password:ro" \` (after the existing database_url mount line). For the optional cluster_credentials: prepare a `CLUSTER_CREDS_ARGS=()` bash array BEFORE the `docker run` command, conditionally populating it via an `if [[ -r ... && -s ... ]]; then ... fi` block (with the `# Optional: only if ./secrets/cluster_credentials.yaml exists in the main repo` comment INSIDE the if-block where comments are syntactically safe), then splice `"${CLUSTER_CREDS_ARGS[@]+"${CLUSTER_CREDS_ARGS[@]}"}"` into the `docker run` continuation chain after the postgres_password mount line. **Deviation note from spec FR-4:** the spec's literal "single comment line preceded by backslash-continued lines on either side" instruction is incompatible with bash line-continuation semantics — bash joins `\<newline>` with the next line, swallowing the comment marker and orphaning subsequent `-e` flags. The array-splice pattern is bash-safe AND mirrors the script's own implementation, so operators reading the recipe see exactly what the script does. The deviation preserves FR-4's *intent* (both env vars documented in the recipe; optional behavior explicit) without producing broken bash. Total LOC: ~7-8 lines added (array setup block + 2 unconditional `-e`/`-v` pairs + 1 splice line). NO new fenced bash blocks; NO bare `DATABASE_URL=` or `POSTGRES_PASSWORD=` env vars (preserves FR-7 regression invariants from `infra_agent_sibling_worktree_isolation` Phase 1). |
| [`docs/03_runbooks/parallel-worktrees.md`](../../../../docs/03_runbooks/parallel-worktrees.md) (currently 88 lines; §"Run tests safely" at lines 29-62) | Add a sentence after the existing `make test-worktree CMD="pytest backend/tests/integration -v"` example (around line 37) stating that integration tests are now supported AND that the script's prereq checks ensure `secrets/database_url` and `secrets/postgres_password` exist before the docker invocation. Add a sentence covering the optional `secrets/cluster_credentials.yaml` behavior: when present, mounted automatically; when absent/empty/unreadable, cluster-credential-dependent tests skip via their existing test-side gates (`@es_required`, FR-6 helper guard at `test_es_overlap_probe_helpers.py:170-203`) — covers spec FR-5 item 3. Insert the new ≤8-line "Adding a new `*_FILE` env var" subsection BETWEEN the CMD-override example (lines 33-38) AND the existing "Residual root-file risk" subsection (lines 48-56) — matches spec FR-5 placement exactly. The subsection states the three-place update contract: `docker-compose.yml` → `scripts/run-tests-in-worktree.sh` → `CLAUDE.md` §"Running tests against a sibling worktree (one-shot container recipe)". Total LOC: ≤25 lines added. |

**Endpoints**

N/A.

**Key interfaces**

The CLAUDE.md fenced-block additions (exact illustration of the change — uses bash-safe array splice, NOT inline backslash-continued comments which would break copy-paste):

```bash
MAIN_REPO=$(git worktree list | awk '{print $1; exit}')

# Optional: cluster_credentials.yaml is only present when the operator has
# registered an ES cluster (via install.sh or manually). When present, the
# worker / migrate containers in docker-compose.yml mount it at
# /run/secrets/cluster_credentials; mirror that here for parity.
CLUSTER_CREDS_ARGS=()
if [[ -r "$MAIN_REPO/secrets/cluster_credentials.yaml" && -s "$MAIN_REPO/secrets/cluster_credentials.yaml" ]]; then
  CLUSTER_CREDS_ARGS=(
    -e "CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials"
    -v "$MAIN_REPO/secrets/cluster_credentials.yaml:/run/secrets/cluster_credentials:ro"
  )
fi

docker run --rm --user root \
  --network relyloop_default \
  -e DATABASE_URL_FILE=/run/secrets/database_url \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e RELYLOOP_IN_WORKTREE_CONTAINER=1 \
  -v "$MAIN_REPO/secrets/database_url:/run/secrets/database_url:ro" \
  -v "$MAIN_REPO/secrets/postgres_password:/run/secrets/postgres_password:ro" \
  "${CLUSTER_CREDS_ARGS[@]+"${CLUSTER_CREDS_ARGS[@]}"}" \
  -v "$PWD/CLAUDE.md:/app/CLAUDE.md:ro" \
  # ... rest unchanged (10 worktree-source mounts + image + cmd)
```

**Why this shape (vs. the spec's literal "single inline comment line" instruction):** bash joins `\<newline>` with the next line as a continuation. A `# Optional` comment line placed BETWEEN two backslash-continued lines of a docker command gets absorbed into the preceding continuation, swallowing the comment marker AND orphaning the subsequent `-e CLUSTER_CREDENTIALS_FILE=...` line as a standalone (failing) command. Operators copy-pasting the recipe get broken bash. The array-splice pattern above is syntactically valid AND mirrors the script's own implementation, so the recipe stays a faithful "what the script does" reference. FR-4's intent (both env vars documented; optional behavior explicit) is preserved.

The new runbook subsection (exact prose):

```markdown
### Adding a new `*_FILE` env var to the Compose stack

When a contributor adds a new `*_FILE` env var to [`docker-compose.yml`](../../docker-compose.yml), the same PR MUST update three places to keep `make test-worktree` consistent with the long-running stack:

1. [`scripts/run-tests-in-worktree.sh`](../../scripts/run-tests-in-worktree.sh) — add a prereq check (fail-loud for required secrets; mount-if-present probe for optional secrets) and add the `-e` + `-v` pair to the `ARGV` block.
2. [`CLAUDE.md`](../../CLAUDE.md) §"Running tests against a sibling worktree (one-shot container recipe)" — add the matching `-e` + `-v` lines to the fenced bash block (optional mounts preceded by a `# Optional: ...` comment).
3. This runbook — extend the §"Run tests safely" prerequisites list to mention the new env var.

Without all three updates, worktree-tested suites that depend on the new env var will silently skip — symptomatic of the `infra_test_worktree_missing_integration_envs` failure mode this contract prevents.
```

**Tasks**

1. Open [`CLAUDE.md`](../../../../CLAUDE.md) at the §"Running tests against a sibling worktree (one-shot container recipe)" section (line 410). Locate the fenced `bash` block that starts at approximately line 420.
2. Add the `POSTGRES_PASSWORD_FILE` env-var line directly after the existing `DATABASE_URL_FILE` line. Add the matching `-v` mount line directly after the existing `database_url` mount line. Both are unconditional, with backslash continuation matching the surrounding lines.
3. **Bash-safe optional cluster_credentials handling** (the substantive deviation from spec FR-4's literal "inline comment line" instruction — see Key Interfaces block above for the full snippet): insert a `CLUSTER_CREDS_ARGS=()` array initialization BEFORE the `docker run` command, populated conditionally via `if [[ -r ... && -s ... ]]; then ... fi`. Then splice `"${CLUSTER_CREDS_ARGS[@]+"${CLUSTER_CREDS_ARGS[@]}"}"` into the `docker run` continuation chain after the `postgres_password` mount line. Place the `# Optional: ...` comment INSIDE the if-block where it's syntactically safe (or as a multi-line comment BEFORE the if-block, also safe). **Do NOT place the comment between two backslash-continued `-e` / `-v` lines of the docker command** — bash absorbs `\<newline>` into the next line, swallowing the comment marker and orphaning the subsequent `-e CLUSTER_CREDENTIALS_FILE=...` line as a standalone failing command.
4. Copy-paste the resulting fenced bash block into a real shell and confirm it parses (`bash -n <(cat <<'EOF'\n...\nEOF\n)` or paste-and-Ctrl-C-without-executing). This is the manual gate that proves the recipe is copy-paste-safe — it caught the cycle-1 failure mode.
5. Verify the FR-7 invariants from `infra_agent_sibling_worktree_isolation` are preserved:
   - No second fenced `bash` block introduced (the existing one absorbs all new lines).
   - No `DATABASE_URL=postgresql://` substring anywhere in the section.
   - The Compose-anchored paths catalog above the recipe is untouched (no `worker` attribution changes to `./migrations/`, `./alembic.ini`, or `./samples/`).
6. Open [`docs/03_runbooks/parallel-worktrees.md`](../../../../docs/03_runbooks/parallel-worktrees.md) at §"Run tests safely" (line 29).
7. After the existing `make test-worktree CMD="pytest backend/tests/integration -v"` example (around line 37), add one sentence stating that integration tests are now supported AND that the script enforces the database_url + postgres_password prerequisites at startup (with a one-line nod to install.sh as the regeneration path).
8. **FR-5 item 3 explicit task:** add a second sentence (or short paragraph) immediately after the prerequisites sentence covering the OPTIONAL cluster_credentials behavior: when `secrets/cluster_credentials.yaml` is present in the main repo, the script mounts it at `/run/secrets/cluster_credentials` (matching `docker-compose.yml` lines 102/160) so cluster-credential-dependent tests like the 5 overlap-probe AC tests in `backend/tests/integration/test_studies_api.py:827-944` execute correctly. When absent (or empty / unreadable), those tests skip via their existing test-side gates (`@es_required` decorator, FR-6 helper guard at `backend/tests/integration/test_es_overlap_probe_helpers.py:170-203`) — no spurious failures, no misleading skip messages.
9. Insert the new "Adding a new `*_FILE` env var" subsection (exact prose above) BETWEEN the CMD-override examples (lines 33-38) AND the existing "Residual root-file risk" subsection (line 48) — matches spec FR-5 placement exactly. (Earlier draft placed it after Residual root-file risk; corrected per GPT-5.5 cycle-1 finding #4.)
10. Verify the runbook stays under 110 lines total (started at 88; this adds ~25; comfortable margin).
11. Run the FR-7 regression test: `uv run pytest backend/tests/unit/docs/test_claude_md_sections.py -v`. All 5 existing tests MUST pass — this confirms the CLAUDE.md edits respect the parent feature's section invariants.
12. Manual review: open both edited files in `mdcat` (or a markdown previewer) to visually confirm the changes render correctly — no markdown-syntax surprises (no broken table cells, no orphan backticks).

**Definition of Done (DoD)**

- [ ] `CLAUDE.md` fenced bash block contains: the 2 new unconditional lines (postgres_password env + mount), the `CLUSTER_CREDS_ARGS` array setup block before `docker run`, and the splice line inside `docker run`. No inline backslash-continued comment marker mid-command.
- [ ] Copy-paste of the new CLAUDE.md fenced bash block into a real shell parses without syntax errors (manual test described in §3.5 below).
- [ ] `uv run pytest backend/tests/unit/docs/test_claude_md_sections.py -v` — all 5 tests pass (no regression on the parent feature's FR-7 invariants).
- [ ] `docs/03_runbooks/parallel-worktrees.md` §"Run tests safely" mentions BOTH (a) integration-test support + postgres_password prerequisite AND (b) the optional cluster_credentials mount-if-present behavior + test-side skip gates (covers spec FR-5 item 3).
- [ ] `docs/03_runbooks/parallel-worktrees.md` contains the new "Adding a new `*_FILE` env var" subsection at the correct location: BETWEEN the CMD-override examples (lines 33-38) AND the existing "Residual root-file risk" subsection (line 48) — matches spec FR-5 placement exactly.
- [ ] Runbook total length ≤ 110 lines.
- [ ] All AC-6, AC-7 from spec §12 verified.

---

## 3) Testing workstream

### 3.1 Unit tests

- **Location:** `backend/tests/unit/scripts/`
- **Scope:** script behavior — argv construction, error paths, conditional mount probe, dry-run stderr hint
- **Tasks:**
  - [ ] Story 1.1: extend `_make_fake_main()` helper to support `postgres_password` (always when `with_secret=True`) and `with_cluster_credentials` parameter.
  - [ ] Story 1.1: modify `test_dry_run_outputs_canonical_argv` (assert `v_mount_count == 12`; assert new env-var + mount appear).
  - [ ] Story 1.1: modify `test_required_bind_mounts_all_present` (add `/run/secrets/postgres_password:ro`).
  - [ ] Story 1.1: add `test_errors_on_missing_postgres_password_file` (asserts exit 5 + FR-1 error message shape).
  - [ ] Story 1.1: add `test_cluster_credentials_mounted_when_host_file_present` (asserts mount count → 13 + new env/mount appear).
  - [ ] Story 1.1: add `test_cluster_credentials_skipped_when_host_file_absent_or_empty` (parametrized across absent/empty/unreadable; unreadable subcase skips when `os.geteuid() == 0`).
- **DoD:**
  - [ ] All 9 tests in `test_run_tests_in_worktree.py` pass (6 existing + 3 new); sub-second runtime.
  - [ ] `uv run pytest backend/tests/unit/docs/test_claude_md_sections.py -v` — all 5 existing tests pass (regression check on parent feature's invariants after Story 1.2's CLAUDE.md edits).

### 3.2 Integration tests

N/A — no new integration tests written by this plan. **The point of this fix** is that the *existing* Postgres-touching integration tests in `backend/tests/integration/` (which currently skip via `make test-worktree`) start executing their assertions after Story 1.1 ships. This is verified operationally (§3.4 below), not by adding new integration test files.

### 3.3 Contract tests

N/A — no API surface added or modified.

### 3.4 E2E tests

N/A — no UI surface added or modified.

### 3.5 Operator-path verification (manual, one-time per PR)

This replaces the E2E layer for this docs/infra feature. **Required** before push.

- [ ] Story 1.1: from inside a sibling worktree (e.g., `/private/tmp/relyloop-<slug>/`; create one if not already on a sibling — `RELYLOOP_MAIN_REPO=$(pwd)` from the main repo is NOT acceptable per spec §14), invoke:
  ```bash
  make test-worktree CMD="pytest backend/tests/integration/test_studies_api.py -v"
  ```
  Expected: the 5 rewritten overlap-probe AC tests (lines 827-944) execute. They may pass, fail, or skip via `@es_required` (acceptable — depends on whether the operator has ES + `local-es` credentials configured), but they MUST NOT all skip with `"Postgres not reachable"`. Document the pass/fail/skip counts in the PR description.
- [ ] Story 1.1: from inside the same sibling worktree, invoke:
  ```bash
  bash scripts/run-tests-in-worktree.sh --dry-run 2>/dev/null
  ```
  (Stderr redirected.) Expected: stdout contains 13 `-v` mounts (when `cluster_credentials.yaml` is present in the main repo's `secrets/`) or 12 (when absent). Operator pastes the output into a shell to manually verify the constructed `docker run` command is valid.
- [ ] Story 1.2 verification: open CLAUDE.md + parallel-worktrees.md in a markdown viewer; visually confirm the new content renders correctly. Additionally: copy-paste the new CLAUDE.md fenced bash recipe (including the array-splice block) into a real shell and confirm it parses without syntax errors (`bash -n <(echo "...")` or paste-and-Ctrl-C-without-executing). This guards against the bash-continuation-vs-comment failure mode that GPT-5.5 cycle-1 finding #1 surfaced.

### 3.6 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | `v_mount_count == 11` (line 139) | 1 | Update to `== 12` (Story 1.1, task 7). |
| [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | enumerated mount-target list (lines 164-176) | 1 | Add `/run/secrets/postgres_password:ro` (Story 1.1, task 8). |
| [`backend/tests/unit/scripts/test_run_tests_in_worktree.py`](../../../../backend/tests/unit/scripts/test_run_tests_in_worktree.py) | `_make_fake_main(...)` definition (lines 53-66) | 1 | Extend to write `postgres_password` always + accept `with_cluster_credentials` (Story 1.1, task 6). |
| [`backend/tests/unit/docs/test_claude_md_sections.py`](../../../../backend/tests/unit/docs/test_claude_md_sections.py) | section-existence, ordering, no-bare-DATABASE_URL, worker-attribution-catalog, exactly-one-bash-block | 5 tests | **No changes needed.** Story 1.2's CLAUDE.md edits stay inside the existing fenced bash block (adds lines, doesn't add new blocks) and don't introduce bare `DATABASE_URL=` or change worker-attribution. Re-run as a regression check (Story 1.2 DoD). |
| All `backend/tests/integration/*.py` files that use `postgres_reachable()` | n/a — these are the beneficiaries | 0 | **No changes needed.** Tests start executing instead of skipping after Story 1.1 ships. |

### 3.7 Migration verification

N/A — no schema changes.

### 3.8 CI gates

- [ ] `make test-unit` (covers Story 1.1's smoke-test changes + Story 1.2's regression-check on the parent feature's doc-section tests).
- [ ] No `make test-integration` / `make test-contract` / `cd ui && pnpm test:e2e` changes — those layers are not touched.

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update at end-of-feature:
- [ ] Add a "recent changes" entry summarizing that `make test-worktree` now propagates `POSTGRES_PASSWORD_FILE` + optional `CLUSTER_CREDENTIALS_FILE`; integration tests via the worktree script now execute instead of skipping.

**`architecture.md`** — no updates required. No new services, no new layers, no new integrations, no new data flows. The bind-mount catalog in CLAUDE.md is the relevant architecture surface and it doesn't change shape — just gets two new entries via the script (which the catalog already covers via the existing `./secrets/` row).

**`CLAUDE.md`** — Story 1.2 (FR-4) covers the recipe update. No convention / rule additions.

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] No updates required.

### 4.2 Product docs (`docs/02_product`)

- [ ] No updates required. (This planned-features folder gets moved to `implemented_features/<date>_infra_test_worktree_missing_integration_envs/` at finalization per `impl-execute` Step 9.)

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] Story 1.2 (FR-5): update `parallel-worktrees.md` §"Run tests safely" + add "Adding a new `*_FILE` env var" subsection.

### 4.4 Security docs (`docs/04_security`)

- [ ] No updates required. The new mounts use `:ro` (read-only); `secrets/*` is already in `.gitignore`; the script doesn't read secret content. Threat model unchanged.

### 4.5 Quality docs (`docs/05_quality`)

- [ ] No updates required.

**Documentation DoD**

- [ ] `state.md` recent-changes entry added at finalization.
- [ ] CLAUDE.md §"Running tests against a sibling worktree (one-shot container recipe)" updated and FR-7 regression test (5 tests) still passes.
- [ ] `docs/03_runbooks/parallel-worktrees.md` updated per Story 1.2.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

N/A — no refactor in scope. This is a focused additive change to one script + one test file + two docs files.

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

- [ ] No behavioral changes outside the new propagation path (postgres_password + cluster_credentials).
- [ ] Existing exit codes 2/3/4 unchanged in meaning (asserted by existing tests).
- [ ] Existing `--cmd` / `--` / `--dry-run` flag-parsing unchanged.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_agent_sibling_worktree_isolation` Phase 2 (PR #249, merged 2026-05-25) | Story 1.1 — the script being patched | ✓ Implemented | This feature literally extends the script that Phase 2 shipped; without Phase 2, there's nothing to patch. |
| `$MAIN_REPO/secrets/postgres_password` exists | Story 1.1 runtime — after the PR merges, every `make test-worktree` invocation requires this file | ✓ Auto-generated by `bash scripts/install.sh` / `make up` (verified at `scripts/install.sh:24-26`) | Operator who has never run `install.sh` sees the fail-loud error on first invocation; remediation is one command. Documented in §16 rollout. |
| `$MAIN_REPO/secrets/cluster_credentials.yaml` (optional) | Story 1.1 runtime — when present, the mount happens; when absent, skipped silently | Optional — present for operators who registered an ES cluster, absent otherwise | No risk; skip-silent is the designed behavior. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Operator's existing `secrets/postgres_password` has gone stale (e.g., regenerated DB after `secrets/` checkout) | L | L | Same risk class as the existing `database_url` check; remediation is `bash scripts/install.sh`. |
| `[[ -r && -s ]]` semantics differ across bash versions | L | L | macOS 3.2 + Linux 4+/5+ both support `-r` and `-s`; the conjunction is POSIX. Verified by existing `[[ -r "$SECRET_FILE" ]]` at line 100. |
| Future contributor adds a new `*_FILE` env var to compose without updating the script | M | M (silent skip in new test suite) | Mitigated by the FR-5 runbook subsection that documents the three-place update contract. Not enforced by automated test — relies on PR review discipline (same trade-off as parent feature's OQ-2 deferral of YAML introspection). |
| `chmod 0o000` unreadable test subcase passes spuriously when test runner is root | L | L | Mitigated by `pytest.skip("requires non-root euid")` when `os.geteuid() == 0` (Story 1.1 task 11). Module-level `pytestmark` also skips the entire file inside the one-shot container (where root is the default). |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Missing `secrets/postgres_password` on first `make test-worktree` invocation | Operator never ran `make up` / `install.sh` | Script exits 5; stderr lists the file path + Rule #2 + `bash scripts/install.sh` remediation hint; no docker invoked | Operator runs `bash scripts/install.sh`; re-invokes `make test-worktree`. Manual. |
| Missing `secrets/cluster_credentials.yaml` when operator runs integration tests that need a cluster | Operator never registered an ES cluster, or never ran `install.sh -2` (or similar opt-in step) | Script proceeds successfully; cluster-credential-dependent tests skip via their existing test-side gates (`@es_required`, FR-6 helper guard) with their own descriptive skip messages | Operator decides if they want cluster credentials; if yes, populates `secrets/cluster_credentials.yaml`; re-invokes. Manual. |
| Operator pipes `bash scripts/run-tests-in-worktree.sh --dry-run | sh` and stderr contains the skip hint | Operator did not redirect stderr | Shell ignores the comment line (starts with `#`); docker run proceeds | None — by design. The shell-comment shape of the hint message is intentional. |
| `RELYLOOP_IN_WORKTREE_CONTAINER=1` causes nested `make test-worktree` invocation inside the one-shot container | Operator inside the one-shot container runs `make test-worktree` recursively (unusual but possible) | Smoke-test file's module-level `pytestmark` (existing, lines 43-50) skips the whole file with a "host-only" reason | None — designed behavior. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — script edit + smoke-test extension. Must come first (Story 1.2's docs describe the shipped behavior).
2. **Story 1.2** — CLAUDE.md + parallel-worktrees.md updates. Depends on Story 1.1's behavior being locked.

### Parallelization opportunities

None within this plan. Stories are small enough that serial execution by one agent in one PR is the right shape. Story 1.2 can be authored while Story 1.1 is in CI watch, but the PR merges as one unit.

### Single-PR scope

All work lands in one PR titled per the conventional-commit convention: `infra(test-worktree): propagate POSTGRES_PASSWORD_FILE + optional CLUSTER_CREDENTIALS_FILE to make test-worktree`. Branch name: `feature/infra-test-worktree-missing-integration-envs` (from CLAUDE.md feature-branch convention).

## 8) Rollout and cutover plan

- **Rollout stages:** single-PR ship. Takes effect immediately on merge for every subsequent `make test-worktree` invocation.
- **Feature flag strategy:** N/A — no flag (this is a script behavior fix, not a feature toggle).
- **Migration/cutover steps:** N/A — no schema, no data.
- **Reconciliation/repair strategy:** N/A — no external systems involved.
- **First-run-after-merge gotcha:** any operator whose `secrets/postgres_password` was never generated (rare — `make up` / `install.sh` always generates it) will see the new fail-loud error on first `make test-worktree`. Remediation is `bash scripts/install.sh`; documented in §16 of the spec and surfaced by the error message itself.

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Patch script + smoke tests
- [ ] Story 1.2 — Sync CLAUDE.md + runbook

### Blocked items

None.

### Done this sprint

(populated by `impl-execute` as stories complete)

## 10) Story-by-Story Verification Gate

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match the story's New/Modified files tables.
- [ ] `bash -n scripts/run-tests-in-worktree.sh` exits 0 (syntax check; Story 1.1 only).
- [ ] `uv run pytest backend/tests/unit/scripts/test_run_tests_in_worktree.py -v` — all 9 tests pass (Story 1.1).
- [ ] `uv run pytest backend/tests/unit/docs/test_claude_md_sections.py -v` — all 5 tests pass (Story 1.2; regression check).
- [ ] Operator-path verification output attached to PR description (Story 1.1).
- [ ] Visual markdown render-check of CLAUDE.md + runbook edits (Story 1.2).
- [ ] No backend, frontend, migration, or compose file changes (`git diff --stat` includes ONLY: `scripts/run-tests-in-worktree.sh`, `backend/tests/unit/scripts/test_run_tests_in_worktree.py`, `docs/03_runbooks/parallel-worktrees.md`, `CLAUDE.md`, `state.md`, and the planned-features → implemented-features folder move at finalization).

## 11) Plan consistency review (required before execution)

| Check | Status | Evidence |
|---|---|---|
| Spec ↔ plan endpoint count | ✓ N/A | Spec §8 is N/A (no endpoints); plan has no endpoint tables |
| Spec ↔ plan error code coverage | ✓ Verified | Spec §8.5 lists script exit codes 0/2/3/4/5; plan covers code 5 (FR-1) + code 0 (success paths) via Story 1.1 tests; codes 2/3/4 are existing and asserted by existing tests |
| Spec ↔ plan FR coverage | ✓ Verified | All 6 FRs mapped in §1 traceability table |
| Story internal consistency | ✓ Verified | Story 1.1 covers FR-1/2/3/6 (script + tests); Story 1.2 covers FR-4/5 (docs); no file ownership conflict |
| Test file count and assignment | ✓ Verified | Single test file `test_run_tests_in_worktree.py` extended in Story 1.1; existing `test_claude_md_sections.py` re-run (no extension) in Story 1.2 — both assigned to specific stories |
| Gate arithmetic | ✓ Verified | Single epic, single PR; no gate counts to arithmetic |
| Open questions resolved | ✓ Verified | Spec §19 lists "Open questions: None" — all locked in cycle 0/1/2 of GPT-5.5 review |
| Frontend UI Guidance | ✓ N/A | No frontend stories; no UI Guidance section needed (verified by absence of UI-related FRs in spec) |
| Plan-internal consistency (Pass 1) | ✓ Verified | This table itself |
| Codebase accuracy (Pass 2) | ✓ Verified | All file paths, line ranges, function names, and existing test assertions cross-checked by direct read |
| Enumerated value contracts | ✓ N/A | No filters/dropdowns/badges |
| Audit-event coverage | ✓ N/A | MVP1 has no `audit_log`; no state-mutating endpoints added |

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files (Endpoints/Key interfaces where applicable), Tasks, and DoD.
- [x] Test layers explicitly scoped (Unit only; Integration/Contract/E2E are N/A with rationale).
- [x] Documentation updates across docs/01-05 are planned and owned.
- [x] Lean refactor scope and guardrails are explicit (N/A).
- [x] Phase/epic gates are measurable (one epic, two stories, single PR).
- [x] Story-by-Story Verification Gate is included.
- [x] Plan consistency review (§11) performed with no unresolved findings.
