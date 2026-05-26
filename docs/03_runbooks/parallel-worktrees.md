# Parallel worktrees — running an agent or tests against a sibling checkout

Operator runbook for the parallel-worktree workflow. Companion to the agent-facing rules in [`CLAUDE.md` §"Working in sibling worktrees"](../../CLAUDE.md#working-in-sibling-worktrees) (the *what's safe to write to*) and the lifecycle steps in [`.claude/skills/impl-execute/SKILL.md`](../../.claude/skills/impl-execute/SKILL.md) Step 0a / 6b / 9.3 (the *audit / spawn / sweep* mechanics).

## When to use a sibling worktree

The main checkout (`/Users/ericstarr/relyloop`) typically has the Docker Compose stack running for day-to-day work. Spinning up a sibling worktree at a path like `/private/tmp/relyloop-<slug>/` lets you:

- Ship a feature in parallel via an autonomous agent without disturbing the operator's main stack.
- Branch experimentally without `git stash`-ing in-flight work in the main checkout.
- Run integration tests against the live Compose database from a different branch without forcing a `make restart`.

You do **not** want a sibling worktree for short-lived bug fixes that an interactive session would finish in 10 minutes — the bookkeeping (create, switch, cleanup) costs more than the parallelism is worth.

## Create + launch

```bash
# From the main checkout — create the sibling worktree on a fresh branch.
git fetch origin main
git worktree add /private/tmp/relyloop-my-feature -b feature/my-feature origin/main

# Launch the agent inside it (Claude Code, etc.) with that path as pwd.
# Agents auto-read CLAUDE.md from their pwd on session start, so the
# sibling automatically picks up the "Working in sibling worktrees" rules.
```

For agent-driven work that runs in its own ephemeral worktree (the `Agent({ isolation: "worktree" })` pattern), the worktree is auto-created and the agent inherits CLAUDE.md from the chosen base branch — see [`impl-execute` SKILL.md Step 6b](../../.claude/skills/impl-execute/SKILL.md).

## Run tests safely

The main worktree's Compose stack bind-mounts paths from the **main worktree** into the running api/worker/migrate containers. Writes through those containers — `docker cp`, `docker compose exec ... > /app/migrations/...` — land in the main worktree, not the sibling. Use `make test-worktree` instead:

```bash
# From inside the sibling worktree (cd /private/tmp/relyloop-my-feature first):
make test-worktree                                              # pytest backend/tests/unit/ -v
make test-worktree CMD="pytest backend/tests/integration -v"    # override the command
make test-worktree CMD="alembic upgrade head"                   # also works for non-test commands
```

The script (`scripts/run-tests-in-worktree.sh`) auto-detects both worktree paths, validates that the main repo's `secrets/database_url` AND `secrets/postgres_password` exist (both required — the `postgres_reachable()` skip gate at [`backend/tests/conftest.py:50-72`](../../backend/tests/conftest.py#L50-L72) checks for BOTH env vars before declaring Postgres reachable), mounts the sibling's source tree into a one-shot `relyloop/api:${RELYLOOP_GIT_SHA:-dev}` container, joins the existing Compose network so postgres / redis / elasticsearch / opensearch are reachable by hostname, and runs the command. The one-shot container is removed on exit (`--rm`); the container's own mutable layer doesn't persist. If either required secret is missing, the script exits with a clear error pointing at `bash scripts/install.sh` for regeneration — operators who have ever run `make up` already have both files.

Optionally, when `$MAIN_REPO/secrets/cluster_credentials.yaml` is present and non-empty, the script mounts it at `/run/secrets/cluster_credentials` (matching `docker-compose.yml` lines 102/160) so cluster-credential-dependent tests like the overlap-probe AC tests in [`backend/tests/integration/test_studies_api.py:827-944`](../../backend/tests/integration/test_studies_api.py#L827-L944) execute against a real cluster inside the one-shot container. When the file is absent, empty, or unreadable, the mount is silently omitted and cluster-credential-dependent tests fall back to their existing test-side skip gates (`@es_required` decorator, the FR-6 helper guard at [`backend/tests/integration/test_es_overlap_probe_helpers.py:170-203`](../../backend/tests/integration/test_es_overlap_probe_helpers.py#L170-L203)) — no spurious failures, no misleading "Postgres not reachable" skip messages.

For commands that need quoted args (e.g., `pytest -k 'foo bar'`), use `--` instead of `--cmd` so bash array semantics preserve the quoting:

```bash
bash scripts/run-tests-in-worktree.sh -- pytest -k 'foo bar'
```

### Adding a new `*_FILE` env var to the Compose stack

When a contributor adds a new `*_FILE` env var to [`docker-compose.yml`](../../docker-compose.yml), the same PR MUST update three places to keep `make test-worktree` consistent with the long-running stack:

1. [`scripts/run-tests-in-worktree.sh`](../../scripts/run-tests-in-worktree.sh) — add a prereq check (fail-loud `[[ -r "$FILE" ]]` for required secrets; `[[ -r && -s ]]` mount-if-present probe for optional secrets) and add the `-e` + `-v` pair to the `ARGV` block.
2. [`CLAUDE.md`](../../CLAUDE.md) §"Running tests against a sibling worktree (one-shot container recipe)" — add the matching `-e` + `-v` lines to the fenced bash block (optional mounts use the `CLUSTER_CREDS_ARGS=()` array-splice pattern, NOT inline backslash-continued comments which would break operator copy-paste).
3. This runbook — extend the §"Run tests safely" prerequisites paragraph above to mention the new env var and its semantics.

Without all three updates, worktree-tested suites that depend on the new env var will silently skip — the exact failure mode that `infra_test_worktree_missing_integration_envs` (PR landing this contract) was created to prevent.

### Residual root-file risk (until `bug_dockerfile_venv_root_owned_after_user_switch` ships its fix)

The script passes `--user root` to `docker run` as a workaround for the Dockerfile bug captured at [`docs/02_product/planned_features/bug_dockerfile_venv_root_owned_after_user_switch/`](../02_product/planned_features/bug_dockerfile_venv_root_owned_after_user_switch/idea.md). The container therefore writes as root. `PYTHONDONTWRITEBYTECODE=1` prevents Python from writing `__pycache__/` directories into the bind-mounted source paths. But any command run inside the container that writes to a bind-mounted path (`/app/backend`, `/app/migrations`, `/app/scripts`) will land **root-owned files on the host**. In normal pytest usage this doesn't happen (pytest's `.pytest_cache` lands in `/app/` which is not bind-mounted), but if you pass `--cmd "pytest --cov ..."` or any command that writes to source, the coverage files / output files land root-owned in your sibling worktree's `backend/`, `migrations/`, or `scripts/`. Mitigations:

- For pytest cache: `make test-worktree CMD="pytest backend/tests/unit/ -v -o cache_dir=/tmp/.pytest_cache"`.
- For coverage: redirect coverage output to `/tmp/` (e.g., `--cov-report=html:/tmp/coverage-html`).
- For any other write-side-effect command: target a non-bind-mounted path inside the container.

If you accidentally leave root-owned files in the sibling worktree, `sudo chown -R $USER:$USER <path>` reclaims them. The Dockerfile fix (see the bug idea above) removes the need for this workaround entirely.

Pass `--dry-run` to inspect the constructed `docker run` argv without executing it:

```bash
bash scripts/run-tests-in-worktree.sh --dry-run | head -20
```

## What can leak — read CLAUDE.md

See [`CLAUDE.md` §"Working in sibling worktrees"](../../CLAUDE.md#working-in-sibling-worktrees) for the full Compose-anchored host paths catalog (writable mounts that silently propagate to the main worktree vs. read-only mounts that fail loudly with `EROFS`). Three rules:

1. **Direct writes from the sibling worktree** (Edit, Write, `git`, plain Unix commands) are always safe — they touch only the sibling's files.
2. **Container-mediated writes** (`docker cp`, `docker exec`, `docker compose cp`, `docker compose exec`) targeting a bind-mounted in-container path land in the **main worktree's** host source, not the sibling's. Use `make test-worktree` for any command that needs the runtime image's tools.
3. **`make test-worktree` is the safe shortcut.** It spins up a one-shot container with the sibling's source tree bind-mounted, so writes from inside the container that target `/app/backend/` etc. land in the sibling, not the main checkout.

## Cleanup

When the feature is merged (or the experimental branch is no longer needed):

```bash
# From the main checkout:
git worktree remove /private/tmp/relyloop-my-feature
git branch -D feature/my-feature       # if the branch was squash-merged

# If the worktree is locked or has untracked files, audit first:
git worktree list
git -C /private/tmp/relyloop-my-feature status -s
# Only --force after explicit confirmation — locked worktrees may hold uncommitted work.
```

`impl-execute` Step 9.3 ("Agent worktree sweep") handles the common case of stale `.claude/worktrees/agent-*` directories left behind by the parallel-test-agents pattern. Named worktrees at `/private/tmp/...` are operator-managed — `impl-execute` Step 0a's worktree pre-flight audit surfaces them with their age (`stat -f %m`) but never force-removes without operator approval.
