# Sibling-worktree isolation for parallel agent feature shipping

**Date:** 2026-05-23
**Status:** Idea — tangential observations from the autonomous `chore_reconciler_terminal_closed_no_poll` agent run (PR #216, merged 2026-05-23)
**Priority:** P2 — only matters when we run parallel-feature agent work; the workaround the agent eventually used worked reliably but was verbose.
**Origin:** Autonomous agent shipped `chore_reconciler_terminal_closed_no_poll` end-to-end in a sibling git worktree at `/private/tmp/relyloop-reconciler-no-poll` while the operator's main checkout (`/Users/ericstarr/relyloop`) had a different feature branch (`feature/chore-study-default-stop-conditions`) in flight. The agent flagged two ergonomic gaps in its final report.
**Depends on:** None.

## Problem

Running an autonomous agent in a sibling git worktree while the operator's main checkout has the Docker Compose stack up exposes two surfaces that aren't designed for parallel work:

### 1. Docker bind mounts anchor to the main worktree, not the sibling

`docker-compose.yml` binds host paths like `/Users/ericstarr/relyloop/migrations/` into the API and worker containers. When an agent working in `/private/tmp/relyloop-reconciler-no-poll/` uses `docker cp` (or `docker exec` + redirection) to write files into a bind-mounted in-container path, the write lands in the **host bind source — i.e., the main worktree** — not the sibling worktree where the agent's code lives.

Concretely: the reconciler agent wrote `migrations/versions/0017_proposals_last_polled_at.py` into the running Postgres container's `/app/migrations/versions/` path. The host bind source is `/Users/ericstarr/relyloop/migrations/versions/`, so the file leaked into the operator's main worktree as an untracked file. Harmless this run (the leaked file was byte-identical to the version eventually merged via PR #216), but it pollutes `git status` and could mislead `git add .` patterns on the operator's other branch.

### 2. Running backend tests from a sibling worktree without the shared stack is awkward

The agent eventually settled on a one-shot container workaround that mounted the worktree's `backend/`, `migrations/`, `scripts/`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `docker-compose.yml`, `Makefile`, and `samples/` into a fresh `relyloop/api:dev` container on the compose network. This worked reliably but was verbose (8+ `-v` flags per invocation) and re-discovered each time the agent needed to run a backend test.

The alternative paths each have problems:

- **Use the shared stack directly**: the containers see the main worktree's code via the bind mount, not the agent's edits. Useless for testing in-progress sibling-worktree changes.
- **Run tests outside Docker via the local venv**: `.venv` symlinks in the sibling worktree point back to the main `.venv`, which has macOS-pinned interpreter paths embedded in the activate scripts. Works for basic Python imports but breaks for anything depending on relative paths or virtualenv-relative tooling.
- **Bring up a second Compose stack**: collides with the main stack on `127.0.0.1:8000`, `:3000`, `:9200`, `:9201`.

## Proposed capabilities

### A. Add a "worktree-aware agent briefing" subsection to CLAUDE.md or the agent-template

A short block in `CLAUDE.md` (or in the briefing template the operator uses when launching autonomous agents) covering:

- The bind-mount anchor pitfall: the shared Docker stack's bind mounts all point to the operator's main worktree, NOT the sibling. Verified in [`docker-compose.yml`](../../../../docker-compose.yml): `migrate` mounts `./migrations:/app/migrations` (line 76) and `./alembic.ini:/app/alembic.ini:ro` (line 77); `api` mounts `./data/repo-clones:/var/lib/relyloop/repos` (line 112), `./migrations:/app/migrations` (line 119), `./alembic.ini:/app/alembic.ini:ro` (line 120), and `./samples:/app/samples:ro` (line 125); `worker` mounts only `./data/repo-clones:/var/lib/relyloop/repos` (line 167); `postgres` mounts `./data/postgres:/var/lib/postgresql/data` (line 28); `redis` mounts `./data/redis:/data` (line 40). **Do not use `docker cp` or `docker exec` + redirection to write files into bind-mounted paths.** (Service attribution corrected during /spec-gen 2026-05-25: the original idea-brief mis-attributed `./migrations`, `./alembic.ini`, and `./samples` to `worker`; the `worker` service only binds `./data/repo-clones`.)
- The "safe paths" catalog — sibling-only host paths that never leak: `/private/tmp/<worktree>/backend/`, `/private/tmp/<worktree>/ui/`, `/private/tmp/<worktree>/docs/`. Leaky paths (the agent must NOT write here via `docker cp` / `docker exec` from a sibling): `./migrations/`, `./samples/`, `./data/postgres/`, `./data/redis/`, `./data/repo-clones/`, `./alembic.ini`.
- A pointer to the recommended pattern for running migrations / tests against the sibling worktree (capability B below).

**Coordination with shipped content** (added since this idea was written 2026-05-23): the existing [`impl-execute` skill](../../../../.claude/skills/impl-execute/SKILL.md) already covers worktree **lifecycle** at three points — Step 0a "Worktree pre-flight" (audit + recommend removals before a feature run), Step 6b "Parallel test agents" (`Agent({ isolation: "worktree" })` for layered test writing), Step 9.3 "Agent worktree sweep" (post-merge cleanup of `.claude/worktrees/agent-*`). Capability (A) is purely additive — it documents the **runtime data path** pitfall (bind-mount leak surface) that lifecycle audits don't catch. The two are complementary, not redundant.

Scope: ~30–50 lines added to `CLAUDE.md` (likely under a new "Working in sibling worktrees" subsection or appended to "Common Pitfalls"). No code changes.

### B. `scripts/run-tests-in-worktree.sh` (or a `make test-worktree` target)

A single shell entrypoint that:

1. Detects the current worktree's absolute path.
2. Spins up a one-shot container with the worktree's `backend/`, `migrations/`, `scripts/`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `Makefile`, `samples/`, and `ui/` (if the test needs it) mounted in.
3. Connects to the existing Compose network so Postgres / Redis / ES / OpenSearch are reachable.
4. Uses a worktree-specific Alembic schema or database name (e.g., `relyloop_worktree_${worktree_hash}`) so migrations don't collide with the main checkout's DB state.
5. Runs the requested test command (`pytest`, `alembic upgrade head`, etc.) and exits.

Scope: ~80-120 LOC shell script; one new `Makefile` target. No backend or frontend code changes.

### C. Optional: separate Alembic test database per worktree

The deepest fix. The Alembic round-trip verification in the agent flow (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`) runs against the shared Postgres. If the main worktree's branch has a migration in flight and the sibling worktree also has one, the rev_id space could collide. Mitigation: a per-worktree `DATABASE_URL` override that points at a worktree-scoped DB (derived from the worktree path hash).

**Constraint (locked at spec time):** CLAUDE.md Rule #2 forbids bare `DATABASE_URL` env vars — the current production / dev path is `DATABASE_URL_FILE` (mounted secret at `./secrets/database_url`, verified at [`docker-compose.yml:68,95,153`](../../../../docker-compose.yml#L68)). Any per-worktree override MUST follow the same `*_FILE`-mounted-secret pattern (e.g., a `./secrets/database_url.worktree-<hash>` file per worktree, OR a flag on the script-B entrypoint that writes a temporary `*_FILE` mount on the fly). See D-2 below.

Scope: ~20 LOC in the test-bootstrap path; needs design review with the Alembic conventions in `CLAUDE.md` Rule #5 AND the secrets convention in Rule #2.

## Scope signals

- **Backend:** none for (A); none for (B); minor for (C).
- **Frontend:** none.
- **Migration:** none.
- **Config:** none for (A); none for (B); new env override for (C).
- **Audit events:** N/A.
- **Tests:** (B) ships with one smoke test (running unit tests through the script from a temp worktree).

## Why deferred

We've successfully shipped exactly one feature this way (the reconciler agent run). The friction is real but bounded; the workaround the agent landed on worked reliably. If we plan to do more parallel-feature shipping with autonomous agents, capability (A) is cheap (~30 min) and worth doing proactively. Capability (B) waits for a second parallel-agent run that hits the same friction. Capability (C) waits for a migration-collision incident.

**Status as of 2026-05-25:** between this idea's date (2026-05-23) and now, the [`impl-execute`](../../../../.claude/skills/impl-execute/SKILL.md) skill picked up worktree-lifecycle coverage (Step 0a + 6b + 9.3 — see "Coordination" note in capability A above). Those don't replace this idea — they cover when worktrees are listed/cleaned, not what's safe to write to from inside them — but they reduce capability (A)'s scope to the bind-mount + safe-paths bullet specifically.

## Decisions to lock at spec time

- **D-1 (phase split):** Phase 1 ships **capability (A) only** — a `CLAUDE.md` "Working in sibling worktrees" subsection covering the bind-mount pitfall + safe-paths catalog. Capabilities (B) and (C) are deferred to separate `chore_` ideas that get captured if-and-when the friction recurs. Rationale: (A) is ~30 min of work, immediately useful, and the missing piece relative to the worktree lifecycle coverage already shipped in [`impl-execute`'s Step 0a / 6b / 9.3](../../../../.claude/skills/impl-execute/SKILL.md). (B) waits for a second parallel-agent test-execution event; (C) waits for a migration-collision incident. Matches the rationale in "Why deferred" above.
- **D-2 (secrets convention for capability C, if it ever ships):** Any per-worktree `DATABASE_URL` override MUST use the `*_FILE`-mounted-secret pattern (CLAUDE.md Rule #2). No bare env vars. The most likely concrete shape: a `./secrets/database_url.worktree-<hash>` file generated on the fly by the script-B entrypoint, mounted into the one-shot container via Docker's secrets primitive or a temp bind mount.

## Open questions for /spec-gen

- **OQ-1:** Where in `CLAUDE.md` should the new content live? **Recommended default:** a new top-level "Working in sibling worktrees" section between "Common Pitfalls" and "Bug Fix Protocol", because the content is more than a pitfall (it's a small operational pattern) but doesn't need its own architecture-doc page.
- **OQ-2:** Should the safe/leaky path catalog be a static prose list, OR a generated table from `docker-compose.yml` (e.g., a `make doctor-worktree` target that diffs bind-mount sources against the current `pwd`)? **Recommended default:** static prose list in v1; tooling waits until the second parallel-agent event.
- **OQ-3:** Does capability (A) need an inline "what to do instead" recipe for the agent — i.e., the verbose 8+ `-v` flag pattern the reconciler agent landed on? **Recommended default:** yes — include a fenced shell example so future agents don't re-derive it.

## Relationship to other work

- **Predicated on** the worktree-based autonomous agent flow (no formal predecessor; established ad-hoc by the `chore_reconciler_terminal_closed_no_poll` run, PR #216 merged 2026-05-23).
- **Complements shipped impl-execute coverage** (added since this idea was written): Step 0a worktree pre-flight + Step 6b parallel-test-agent worktrees + Step 9.3 post-merge worktree sweep cover *lifecycle*. Capability (A) adds *runtime data path* guidance not covered by those steps.
- **Possible future coordination:** if we ever build a "managed agents in the cloud" path (per the conversation that surfaced these observations), capabilities (B) and (C) become moot for cloud-hosted runs but still useful for local parallel work.
