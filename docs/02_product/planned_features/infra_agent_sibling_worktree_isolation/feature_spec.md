# Feature Specification — Sibling-worktree isolation guidance in CLAUDE.md (Phase 1)

**Date:** 2026-05-25
**Status:** Draft
**Owners:** Eric Starr (Product + Engineering)
**Related docs:**
- [`idea.md`](idea.md) (origin brief)
- [`implementation_plan.md`](implementation_plan.md) (TBD — generated next stage)
- [`docker-compose.yml`](../../../../docker-compose.yml) (canonical source of bind-mount truth)
- [`.claude/skills/impl-execute/SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md) Step 0a / 6b / 9.3 (complementary worktree-lifecycle coverage already shipped)

---

## 1) Purpose

- **Problem:** Autonomous agents running in a sibling git worktree (e.g., `/private/tmp/relyloop-<slug>`) while the operator's main checkout (`/Users/ericstarr/relyloop`) has the Compose stack up can silently leak files into the main worktree via Docker bind mounts. Surfaced concretely by the `chore_reconciler_terminal_closed_no_poll` agent run (PR #216, merged 2026-05-23): the agent wrote a migration file via `docker cp` into a running Compose-service container's `/app/migrations/` path (either `api` or `migrate` — both bind that path; `postgres` itself only binds `./data/postgres/`); the host bind source is `./migrations/` in the main worktree, so the file appeared as untracked there. Harmless that run; a footgun in general.
- **Outcome:** Add a tight "Working in sibling worktrees" section to `CLAUDE.md` between `## Common Pitfalls` and `## Bug Fix Protocol` that catalogs which host paths are bind-mounted by the Compose stack (and therefore leak to the main worktree when written via `docker cp` / `docker exec`), names the safe alternatives, and gives one concrete shell recipe for running commands against a sibling worktree without leaking. Future agents read this on session start and avoid the footgun without re-deriving it.
- **Non-goal:** Build any tooling (no `scripts/run-tests-in-worktree.sh`, no `make doctor-worktree`, no per-worktree `DATABASE_URL_FILE` plumbing). Those are capabilities B and C from the idea — deferred per D-1.

## 2) Current state audit

### Existing implementations

- [`CLAUDE.md`](../../../../CLAUDE.md) — root project conventions. Structure verified: `## Common Pitfalls` (line 352), `## Bug Fix Protocol` (line 368), `## Tangential discoveries — capture as idea files immediately` (line 381), `## Local-stub hygiene — never leave commit-eligible debug artifacts in the repo` (line 443). No existing "Working in sibling worktrees" section — grep returned no matches.
- [`docker-compose.yml`](../../../../docker-compose.yml) — canonical bind-mount source. Lines verified by direct read (idea cites were off; spec lines below are corrected):
  - `migrate` (init container): `./migrations:/app/migrations` (line 76), `./alembic.ini:/app/alembic.ini:ro` (line 77)
  - `api`: `./data/repo-clones:/var/lib/relyloop/repos` (line 112), `./migrations:/app/migrations` (line 119), `./alembic.ini:/app/alembic.ini:ro` (line 120), `./samples:/app/samples:ro` (line 125)
  - `worker`: `./data/repo-clones:/var/lib/relyloop/repos` (line 167) — **only** this mount; the idea incorrectly attributed `./migrations` / `./alembic.ini` / `./samples` to the worker
  - `postgres`: `./data/postgres:/var/lib/postgresql/data` (line 28)
  - `redis`: `./data/redis:/data` (line 40)
- [`.claude/skills/impl-execute/SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md) — Step 0a "Worktree pre-flight" (line 468), Step 6b "Parallel test agents" (line 278), Step 9.3 "Agent worktree sweep" (line 937). All three exist as cited in the idea. They cover worktree **lifecycle** (audit / spawn / sweep) — not **runtime data path** safety, which is this spec's contribution.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| (none — adding a brand-new section, not moving any URL) | — | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| (none — no `CLAUDE.md` structural tests exist; no markdownlint config in repo) | — | — | — |

The new section will be validated by (a) content review at PR time (Story acceptance criteria), and (b) a small five-test regression suite (`backend/tests/unit/docs/test_claude_md_sections.py`) covering the historically-observed failure modes per §7 FR-7: section existence, ordering between Common Pitfalls and Bug Fix Protocol, absence of bare `DATABASE_URL=postgresql://`, correct service attribution for `./migrations/` / `./alembic.ini` / `./samples/` (not `worker`), and exactly-one fenced `bash` block.

### Existing behaviors affected by scope change

- **Agent operating manual (CLAUDE.md as-read on session start):** Current: contains no guidance on sibling worktrees; agents derive the bind-mount pitfall on first encounter, sometimes after leaking files. New: agents reading `CLAUDE.md` on session start receive the safe/leaky path catalog + the one-shot recipe before they touch a bind-mounted path. Decision needed: no — this is purely additive.

---

## 3) Scope

### In scope

- A single new `## Working in sibling worktrees` section in [`CLAUDE.md`](../../../../CLAUDE.md), inserted between `## Common Pitfalls` (currently ends at line 367) and `## Bug Fix Protocol` (currently starts at line 368).
- The section content:
  1. One-paragraph framing of the bind-mount-anchors-to-main pitfall, with a verified citation to `docker-compose.yml`.
  2. A **leaky paths** table listing every host path bind-mounted by the Compose stack (with `docker-compose.yml:<line>` citations).
  3. A **safe paths** rule of thumb (anything under `/private/tmp/<worktree>/` that isn't a Compose bind source).
  4. A fenced shell example showing the one-shot container pattern the reconciler agent landed on (mounts the sibling worktree's `backend/`, `migrations/`, `scripts/`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `docker-compose.yml`, `Makefile`, and `samples/` into a fresh `relyloop/api:dev` container on the Compose network).
  5. A one-line pointer to `impl-execute` Step 0a / 6b / 9.3 for worktree lifecycle (complementary, not redundant).
  6. A one-line forward-pointer noting that capabilities B (`scripts/run-tests-in-worktree.sh`) and C (per-worktree `DATABASE_URL_FILE`) are deferred to separate `chore_`/`infra_` ideas (with file links once those ideas exist post-spec).
- A five-test regression suite at `backend/tests/unit/docs/test_claude_md_sections.py` covering: section existence, section ordering between Common Pitfalls and Bug Fix Protocol, absence of bare `DATABASE_URL=postgresql://` in the section body, correct service attribution in the leaky-paths catalog (the catalog rows for `./migrations/` / `./alembic.ini` / `./samples/` do not list `worker`; the row for `./data/repo-clones/` does list `worker`), and exactly one fenced `bash` block in the section. These are intentionally bounded to the historically-observed failure modes — not a full content schema check (line-number staleness is deferred per OQ-2).

**Note on artifact set vs. idea's "no code changes" phrasing:** The idea brief said Phase 1 is "no code changes." This spec adds **one** pytest file (`backend/tests/unit/docs/test_claude_md_sections.py`) plus the `phase2_idea.md` / `phase3_idea.md` / `pipeline_status.md` tracking files in this feature's directory. The regression test exists because every change in this repo follows the Bug Fix Protocol's "regression test for every fix" rule (`CLAUDE.md` §"Bug Fix Protocol" step 4) and the spec-gen Step 10 mandate for deferred-phase tracking — they're process-required artifacts, not capability creep. The spirit of the idea's "no code changes" was "no production code changes" and that remains true: nothing in `backend/app/`, `ui/src/`, `migrations/`, or `scripts/` is modified.

### Phase 2 expansion — added 2026-05-25 after operator approval

After Phase 1 stories shipped on PR #249, the operator approved expanding scope to include capability B (the test-runner script) on the same branch — the implement-over-defer rubric applies cleanly because the design forks are all pre-locked (D-1 phase boundary, D-2 secrets pattern, FR-4 mount-set + image-tag + network), no operator-judgment forks remain. Phase 3 (capability C) stays deferred per `phase3_idea.md` Backlog priority because three operator-judgment forks remain unresolved (secret-file shape, DB naming, cleanup trigger). The Phase 2 additions in scope:

- A `scripts/run-tests-in-worktree.sh` entrypoint that mechanizes the one-shot container recipe from FR-4. The script auto-detects the sibling worktree (`git rev-parse --show-toplevel`) and the main worktree (`git worktree list | awk '{print $1; exit}'`), validates that `$MAIN_REPO/secrets/database_url` exists, mounts the canonical 9 source paths, joins the existing Compose network, and forwards CLI args to a configurable command (default: `pytest backend/tests/unit/`).
- A `make test-worktree` Makefile target wrapping the script. Operators can override the command via `make test-worktree CMD="pytest backend/tests/integration -v"`.
- A `--dry-run` mode on the script that prints the constructed `docker run` command without executing it. This is what the script's smoke test asserts against.
- A smoke test at `backend/tests/unit/scripts/test_run_tests_in_worktree.py` covering argument parsing, the `--dry-run` command-construction output, and clear-error paths for missing prerequisites (no `secrets/database_url`, no Compose network, not in a worktree). The test does NOT actually run Docker — it shells out to the script with `--dry-run` and asserts on stdout. CI hermeticity preserved.
- A runbook at `docs/03_runbooks/parallel-worktrees.md` (≤80 lines) explaining the parallel-worktree workflow end-to-end: launching an agent in a sibling worktree, using `make test-worktree`, what the leaky-paths catalog means in operator terms, when to escalate.
- Updates to the CLAUDE.md `## Working in sibling worktrees` section to reference `make test-worktree` as the canonical shortcut (the existing fenced recipe stays for transparency — operators benefit from understanding what the script does internally). A new `### Shortcut: \`make test-worktree\`` subsection sits before the existing `### Running tests against a sibling worktree` recipe subsection.
- Delete `phase2_idea.md` — capability B is no longer deferred. `phase3_idea.md` stays.

### Out of scope

- Per-worktree `DATABASE_URL_FILE` override (capability C from the idea) — deferred. Phase 3 `phase3_idea.md` stays for when a migration-collision incident motivates it.
- A `make doctor-worktree` target or any other tooling that introspects `docker-compose.yml` to generate the path catalog dynamically (OQ-2 recommended default: static prose list in v1).
- Edits to `architecture.md` or `state.md` content beyond the standard end-of-feature `state.md` "recent changes" entry. The new content lives in `CLAUDE.md` only — that's the file agents auto-read on every session.
- Any changes to `docker-compose.yml`. (Phase 2 DOES touch `Makefile` and `scripts/` per the expansion above; only `docker-compose.yml` remains untouched.)

### API convention check

N/A — this is a docs-only feature. No new endpoints, no router files touched, no request/response shapes defined. The §8 endpoint surface section below is filled with `N/A` accordingly.

### Phase boundaries (multi-phase)

- **Phase 1 (this spec):** Capability A only — the new `CLAUDE.md` section + a five-test regression suite covering the historically-observed failure modes. Rationale: ~30-50 LOC of docs + ~80-120 LOC of test code (one test file, five tests sharing a single section-body fixture) = ~30-45 min of work, immediately useful, addresses the proven failure mode (PR #216 leak) and the convergence-quality failure modes surfaced by cycle-1 GPT-5.5 review. D-1 lock from idea.
- **Phase 2 (deferred — `phase2_idea.md`):** Capability B — `scripts/run-tests-in-worktree.sh` (one-shot container wrapper with worktree-aware bind mounts) + a `make test-worktree` target. Rationale: waits for a second parallel-agent test-execution event. The recipe shipped as a prose example in Phase 1's shell block is the design seed; Phase 2 codifies it.
- **Phase 3 (deferred — `phase3_idea.md`):** Capability C — per-worktree `DATABASE_URL_FILE` override following the `*_FILE`-mounted-secret pattern (CLAUDE.md Rule #2). Rationale: waits for a migration-collision incident between concurrent worktrees. D-2 from idea pre-locks the secrets-convention constraint.

**Deferred phase tracking:** `phase2_idea.md` and `phase3_idea.md` will be created in this feature's directory as part of Phase 1's `impl-execute` Step 10, so the deferred work is discoverable by future `/pipeline status` runs.

## 4) Product principles and constraints

- **Forward-only, no legacy preservation** — the new section is additive; no existing CLAUDE.md content is rewritten or "preserved-for-later" with HTML-commented stubs.
- **Cite the source-of-truth file** — every leaky-path bullet must include a `docker-compose.yml:<line>` link so the catalog is auditable and any reader can verify in 30 seconds.
- **Stay narrow** — Phase 1 ships **one** new `CLAUDE.md` section + **one** new pytest file (`test_claude_md_sections.py`) containing five focused regression tests. No tooling, no Makefile, no shell script, no spec-time decisions about Phase 2 / 3 implementation details beyond locking the secrets-convention constraint (D-2).
- **Compatible with shipped impl-execute coverage** — the new section explicitly cross-references Step 0a / 6b / 9.3 so readers don't think this is a competing or duplicate concern. Lifecycle is impl-execute; runtime data path is this section.

### Anti-patterns

- **Do not** auto-generate the path catalog by parsing `docker-compose.yml` at runtime — this is OQ-2's deferred tooling (Phase 2 candidate, not Phase 1). A static prose list with cited line numbers is simpler, reviewable in PR, and stays correct because the regression test asserts the section exists (drift to a wrong line number would be caught by reviewer eyeballs at the next CLAUDE.md edit, not by automation in Phase 1).
- **Do not** suggest workarounds that violate CLAUDE.md Rule #2 (the secrets-via-files pattern). The shell example for the one-shot container **must not** pass a bare `DATABASE_URL=postgresql://...` env var. It **must** mount the existing `./secrets/database_url` file from the main repo into `/run/secrets/database_url` in the one-shot container — either via `--mount type=bind,src=$MAIN_REPO/secrets/database_url,dst=/run/secrets/database_url,readonly` (long form) or via `-v $MAIN_REPO/secrets/database_url:/run/secrets/database_url:ro` (shorthand; both are accepted by `docker run` and produce identical results) — and pass `-e DATABASE_URL_FILE=/run/secrets/database_url`, exactly mirroring `docker-compose.yml` lines 68 / 95 / 153. The settings layer at `backend/app/core/settings.py` then resolves the URL from the mounted file (CLAUDE.md Rule #2 / D-2).
- **Do not** write through any already-running shared Compose service container to a bind-mounted path. Forbidden command shapes (whether the agent invokes them from a sibling worktree or anywhere else): `docker cp <local> <container>:<bind-mounted-path>`, `docker compose cp <local> <service>:<bind-mounted-path>`, `docker exec <container> sh -c '... > <bind-mounted-path>'`, `docker compose exec <service> sh -c '... > <bind-mounted-path>'`. The hazard differs by bind-mount writability:
  - **Writable bind mounts** (`/app/migrations/`, `/var/lib/postgresql/data/`, `/data/` inside the Redis container, `/var/lib/relyloop/repos/`) silently propagate the write to the operator's main-worktree host path. This is the most dangerous failure mode — the agent sees a successful write but the bytes land in the wrong worktree.
  - **Read-only bind mounts** (`/app/alembic.ini:ro`, `/app/samples:ro`) reject the write inside the container with a "Read-only file system" / `EROFS` error. Failure is loud, not silent, but the agent must still understand that "the write didn't go where I expected" rather than retrying with `sudo` or a different command.
  In either case the right move is the same: don't write through a shared container; use the one-shot container recipe in FR-4 instead.
- **Do not** insert the new section as a sub-bullet under `## Common Pitfalls`. It's its own top-level `##` section because (a) it's an operational pattern with multiple bullets and a code block, not a one-liner pitfall, and (b) OQ-1's recommended default placed it as a sibling between Pitfalls and Bug Fix Protocol.
- **Do not** introduce a fourth Docker mount that didn't exist before just to make sibling-worktree work "cleaner" — that's Phase 2's scope, and changing `docker-compose.yml` in Phase 1 would require coordinating with every operator who has an existing stack running.
- **Do not** write the section in language that conflicts with the "Tangential discoveries" rule (line 381) or the "Local-stub hygiene" rule (line 443). All three sit adjacent and should reinforce each other; the new section's "what to do instead" recipe must explicitly mention that any debug stubs created during sibling-worktree work are still subject to the Local-stub-hygiene rule.

## 5) Assumptions and dependencies

- **Dependency:** None at the code level. The work is one file edit + one test file.
- **Dependency (informational):** `impl-execute` Step 0a / 6b / 9.3 must exist as cited (verified by direct read of [`SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md)). If those step numbers change in a future `impl-execute` revision, the cross-references in the new section must be updated in the same PR.
- **Dependency (informational):** `docker-compose.yml` bind-mount line numbers are the source of truth for the leaky-paths table. If a future PR adds, removes, or renumbers a bind mount, the leaky-paths table must be updated in the same PR. The regression test does **not** enforce line-number correctness — it asserts the section exists and a small set of historically-observed failure tokens are absent (per FR-7). A full line-number-validity test was considered and rejected for Phase 1: it would be brittle (bind-mount line numbers shift on every `docker-compose.yml` edit) and the alternative (parsing YAML and comparing to the table) is exactly what OQ-2 deferred to Phase 2.
- **Assumption (downstream actor inheritance, promoted to a §16 rollout fact):** Claude Code's CLAUDE.md auto-loader reads `<pwd>/CLAUDE.md` on session start. Worktrees have their own `pwd` (a separate working directory pointing at the worktree path), so spawned parallel agents from [`impl-execute` Step 6b](../../../../.claude/skills/impl-execute/SKILL.md) (`Agent({ isolation: "worktree" })`) automatically read the sibling worktree's copy of `CLAUDE.md` on their session start. The new section therefore propagates to every sibling worktree branched off `main` after the Phase 1 PR merges, without requiring any prompt-template change. The full rollout statement (including the long-lived-feature-branch edge case and its mitigation) lives in §16 below — surfacing it as a real rollout fact rather than burying it as an "assumption with risk: zero."
- **Risk if missing:** Zero for external code dependencies (the work is one CLAUDE.md edit + one test file). The downstream actor inheritance described above is verified by reading Claude Code's session-start behavior, not an assumption we're hoping holds.

## 6) Actors and roles

- Primary actor(s): autonomous agent (Claude) reading `CLAUDE.md` on session start; secondarily, human operator reading `CLAUDE.md` when launching a parallel work session.
- Role model: N/A — RelyLoop MVP1 is single-tenant + no auth.
- Permission boundaries: N/A — docs-only.

### Authorization

N/A — single-tenant install, no auth surface (MVP1; multi-tenant lands at MVP4).

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md). MVP1 has no audit-event surface, and even at MVP2+ a docs-only change wouldn't emit audit events (the rule applies to state-mutating endpoints / service functions).

## 7) Functional requirements

### FR-1: New `## Working in sibling worktrees` section in CLAUDE.md

- Requirement:
  - The system **MUST** contain a top-level `## Working in sibling worktrees` section in [`CLAUDE.md`](../../../../CLAUDE.md), inserted between `## Common Pitfalls` and `## Bug Fix Protocol`.
  - The section **MUST** open with a one-paragraph framing that names the bind-mount-anchors-to-main pitfall, cites the originating incident (`chore_reconciler_terminal_closed_no_poll`, PR #216), and links to [`docker-compose.yml`](../../../../docker-compose.yml) as the authoritative bind-mount source.
- Notes: Insertion position is fixed by FR-1 — implementers cannot pick a different position. OQ-1 lock.

### FR-2: Compose-anchored host paths catalog

- Requirement:
  - The section **MUST** include a table (preferred) or bulleted list with one entry per host path that is bind-mounted by the Compose stack. "Compose-anchored" replaces the looser term "leaky" — most of these paths are write-leak sources, but two (`./alembic.ini`, `./samples/`) are read-only mounts where the container-mediated write fails loudly rather than leaking silently. Both classes belong in the catalog; the catalog **MUST** show the writability state per entry.
  - Every entry **MUST** include a `[docker-compose.yml:<line>](docker-compose.yml#L<line>)` link to the verifying line in the Compose file. (The link path is repo-root-relative — `docker-compose.yml#L<line>`, **not** `../docker-compose.yml#L<line>` — because `CLAUDE.md` is itself at repo root.)
  - The catalog **MUST** include all six entries verified in §2: `./migrations/`, `./alembic.ini`, `./samples/`, `./data/postgres/`, `./data/redis/`, `./data/repo-clones/`. Adding paths not in this list is allowed if a future `docker-compose.yml` edit introduces them; removing one without removing the corresponding mount is forbidden.
  - The catalog **MUST** state, for each path: (a) the Compose service(s) that mount the bind source with `docker-compose.yml` line citations, (b) the writability state (writable / read-only). Paths mounted by multiple services **MUST** list every owning service: `./migrations/` is mounted writable by both `migrate` and `api`; `./alembic.ini` is mounted **read-only (`:ro`)** by both `migrate` and `api`; `./samples/` is mounted **read-only (`:ro`)** by `api` only; `./data/repo-clones/` is mounted writable by both `api` and `worker`. Service attribution **MUST** match `docker-compose.yml` — the idea's original attribution (worker for migrations/alembic/samples) was wrong and **MUST NOT** be reproduced. In particular, the `worker` service **MUST NOT** be attributed to `./migrations/`, `./alembic.ini`, or `./samples/`; FR-7 includes a regression check for this exact failure mode.
  - For each writable entry, the catalog **MUST** state the failure mode plainly: "container-mediated writes silently propagate to the main worktree." For each read-only entry, the catalog **MUST** state: "container-mediated writes fail with `EROFS` / read-only filesystem; the file is anchored to the main worktree but cannot be modified through the shared container."
- Notes: Verified attribution and writability are in §2 "Existing implementations". The writability distinction is the substantive sharpening from GPT-5.5 cycle 2 finding #2 — without it, the catalog overstated the write-leak hazard for `:ro` mounts.

### FR-3: Safe-paths rule of thumb

- Requirement:
  - The section **MUST** state the safe-paths rule explicitly, framed by operation mode (not by file path):
    - **Direct writes to the sibling worktree's filesystem are always safe.** From a sibling worktree at `/private/tmp/<slug>/`, the `Edit`, `Write`, and `git` tools (and any plain Unix command run from outside a container) write to the sibling's own copy of the file. This includes paths whose **base name** happens to match a Compose bind source — `/private/tmp/<slug>/migrations/0042_foo.py`, `/private/tmp/<slug>/samples/products.json`, `/private/tmp/<slug>/alembic.ini`, and `/private/tmp/<slug>/data/postgres/` are all sibling-local files; editing them does not affect the main worktree. The Compose stack's bind mount targets the **main worktree's** `./migrations/`, not "any worktree's `migrations/`".
    - **Writes that pass through an already-running shared Compose service container resolve to the main worktree's bind source** — silently for writable mounts (`/app/migrations/`, `/var/lib/postgresql/data/`, `/data/`, `/var/lib/relyloop/repos/`), loudly with an `EROFS` error for read-only mounts (`/app/alembic.ini`, `/app/samples/`). Forbidden command shapes (whether invoked from a sibling worktree or anywhere else): `docker cp <local> <container>:<bind-mounted-path>`, `docker compose cp <local> <service>:<bind-mounted-path>`, `docker exec <container> sh -c '... > <bind-mounted-path>'`, `docker compose exec <service> sh -c '... > <bind-mounted-path>'`. The hazard is the bind source the running container resolves to, not the command form.
  - The rule **MUST** give at least three concrete examples of safe direct sibling-worktree writes (`/private/tmp/<slug>/backend/`, `/private/tmp/<slug>/ui/`, `/private/tmp/<slug>/docs/`) and at least two concrete examples of forbidden container-mediated writes (`docker cp` and `docker compose exec` redirection).
- Notes: OQ-2 lock — static prose, not dynamically generated. The semantic correction here (sibling-local `migrations/` is safe to edit directly; only container-mediated writes leak) is the substantive sharpening from GPT-5.5 cycle 1 finding #7.

### FR-4: One-shot container recipe (the "what to do instead")

- Requirement:
  - The section **MUST** include exactly one fenced `bash` example showing the one-shot container pattern that worked reliably in the reconciler agent run.
  - The example **MUST** use the existing `relyloop/api:${RELYLOOP_GIT_SHA:-dev}` image (no separate Dockerfile). The tag fallback `:-dev` matches `docker-compose.yml` lines 54, 81, and 136.
  - The example **MUST** mount the sibling worktree's source tree (`backend/`, `migrations/`, `scripts/`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `docker-compose.yml`, `Makefile`, `samples/`) — these are the directories the reconciler agent settled on; the spec locks the exact set so future agents don't re-derive it.
  - The example **MUST** join the existing Compose network (so the one-shot container can reach `postgres`, `redis`, `elasticsearch`, `opensearch` by hostname) — `--network relyloop_default` (or whatever the operator's `COMPOSE_PROJECT_NAME` resolves to; the canonical example uses `relyloop_default`).
  - The example **MUST NOT** introduce a bare `DATABASE_URL=postgresql://...` env var.
  - The example **MUST** provide database connectivity via the `*_FILE`-mounted-secret pattern (CLAUDE.md Rule #2 / D-2). The exact mechanism: pass `-e DATABASE_URL_FILE=/run/secrets/database_url` **AND** mount the main repo's existing secret file. Either syntax is acceptable: `--mount type=bind,src=$MAIN_REPO/secrets/database_url,dst=/run/secrets/database_url,readonly` (long form) OR `-v $MAIN_REPO/secrets/database_url:/run/secrets/database_url:ro` (shorthand) — both produce a read-only bind mount of the host secret file, matching how `api` / `worker` / `migrate` resolve the secret at `docker-compose.yml` lines 68, 95, and 153. `$MAIN_REPO` is the operator's actual main checkout path (typically `/Users/ericstarr/relyloop`). `backend/app/core/settings.py` reads the mounted file via its `*_FILE` accessor.
  - The example **SHOULD** include a comment line above the `--mount` for the secret pointing out the Rule #2 constraint, so future readers see the rationale without having to re-derive it.
- Notes: OQ-3 lock — yes, include the recipe. The DB-secret mechanics in this FR are the substantive sharpening from GPT-5.5 cycle 1 finding #4.

### FR-5: Cross-reference to impl-execute lifecycle steps

- Requirement:
  - The section **MUST** include a one-line pointer to [`impl-execute` Step 0a, Step 6b, and Step 9.3](../../../../.claude/skills/impl-execute/SKILL.md) noting they cover worktree **lifecycle** (audit / spawn / sweep) while this section covers **runtime data path** safety — explicitly stating the two are complementary.
- Notes: Coordinates with shipped content per the idea's "Coordination" note.

### FR-6: Forward-pointer to deferred phases

- Requirement:
  - The section **MUST** include a one-line forward-pointer noting that capabilities B and C (the `scripts/run-tests-in-worktree.sh` automation and per-worktree `DATABASE_URL_FILE` overrides) are tracked as `phase2_idea.md` and `phase3_idea.md` in this feature's directory, and will be picked up when the friction recurs.
- Notes: Ensures future readers know the deferred work isn't lost.

### FR-7: Regression checks (section presence + historically-observed failure tokens)

- Requirement:
  - A new test file **MUST** live at `backend/tests/unit/docs/test_claude_md_sections.py` (new test file; new directory under `backend/tests/unit/`, consistent with the existing `backend/tests/unit/scripts/` convention) and follow the project's unit test conventions (pytest, no DB, no network).
  - The file **MUST** include the following five discrete tests, sharing a single module-level fixture that reads `CLAUDE.md` once and slices the section body between the `## Working in sibling worktrees` header and the next top-level `## ` header:
    1. `test_working_in_sibling_worktrees_section_exists` — assert the literal line `## Working in sibling worktrees` appears exactly once in `CLAUDE.md`. Multiple occurrences (accidental copy-paste) and zero occurrences (accidental deletion during a future doc reorg) **MUST** both fail. **Why:** locks the section's existence (the primary invariant).
    2. `test_section_ordering_between_pitfalls_and_bugfix` — assert `## Common Pitfalls`, `## Working in sibling worktrees`, and `## Bug Fix Protocol` appear in that order in `CLAUDE.md`. **Why:** locks OQ-1's placement decision; a future reorg that puts the section elsewhere would invalidate cross-references in the rest of `CLAUDE.md`.
    3. `test_section_has_no_bare_database_url_assignment` — assert the section body does **not** contain the regex pattern `DATABASE_URL=postgresql://` (case-insensitive). **Why:** catches a future doc edit that re-introduces a bare env var in the shell example (Rule #2 violation; the specific failure mode this section is teaching agents to avoid). Note: the pattern is intentionally specific to `DATABASE_URL=postgresql://...` — a prose phrase like "the `DATABASE_URL=...` anti-pattern" is allowed because it doesn't include `postgresql://`.
    4. `test_section_leakypath_catalog_attribution` — locate the Compose-anchored paths catalog within the section body (delimited by the catalog's table header or list-start marker, NOT the whole section body — see implementation note below) and assert: (a) the rows for `./migrations/`, `./alembic.ini`, and `./samples/` do **not** list `worker` as an owning service; (b) the row for `./data/repo-clones/` **does** list `worker`. **Why:** catches re-introduction of the idea's original wrong attribution AND catches accidental removal of the legitimate worker mention for `data/repo-clones`. **Implementation note:** the test must target the catalog rows specifically (not perform a section-wide `worker.*migrations` regex sweep) because the section's prose legitimately mentions both `worker` (in the data/repo-clones row + lifecycle cross-reference) and `migrations` (in the safe-paths rule + recipe). Recommended implementation: parse the catalog table by Markdown-table delimiters (e.g., locate the line `| Path | Service(s) | Writability | docker-compose.yml |` or the equivalent list format chosen by the implementer) and assert per-row. A simpler implementation that finds each path's row and checks the immediately-following service-cell text is also acceptable.
    5. `test_section_has_exactly_one_fenced_bash_block` — count fenced code blocks opening with the literal token ` ```bash` (three backticks + the word `bash`) inside the section body and assert exactly one. **Why:** FR-4 mandates exactly one recipe; copy-paste or competing recipes have historically caused agents to follow the wrong one.
  - The tests **MUST NOT** assert specific `docker-compose.yml` line numbers, specific path strings beyond the patterns enumerated above, or any property that would shift on a normal `docker-compose.yml` edit. Line-number staleness remains a PR-review concern (OQ-2 deferred).
- Notes: This is the substantive sharpening from GPT-5.5 cycle 1 findings #5 and #6 (expand from header-only to historical-failure-mode coverage) and cycle 2 finding #4 (test #4 retargeted from broad section-wide regex to specific catalog-row inspection to eliminate the false-positive risk against legitimate prose). The 5 tests collectively run in well under one second.

### Phase 2 — FR-8 through FR-12 (added 2026-05-25 via on-PR scope expansion)

### FR-8: `scripts/run-tests-in-worktree.sh` script

- Requirement:
  - A new shell script **MUST** live at `scripts/run-tests-in-worktree.sh`, executable (`chmod +x`), with the standard `#!/usr/bin/env bash` shebang and `set -euo pipefail` for fail-fast semantics.
  - The script **MUST** auto-detect the sibling worktree's absolute path via `git rev-parse --show-toplevel` from the script's invocation `pwd`. If the script is not invoked from inside a git worktree, it **MUST** exit with a clear error message naming the missing prerequisite (no silent failure).
  - The script **MUST** auto-detect the main worktree's absolute path via `git worktree list | awk '{print $1; exit}'`. Per git convention, the main worktree is always listed first.
  - The script **MUST** validate `$MAIN_REPO/secrets/database_url` exists and is readable BEFORE invoking `docker run`. Missing-secret produces a clear error mentioning CLAUDE.md Rule #2 and pointing at the secret-generation step in `scripts/install.sh`.
  - The script **MUST** join the existing Compose network. Default network name: `relyloop_default` (per `docker compose --project-name relyloop` convention). The script **SHOULD** allow override via the `COMPOSE_PROJECT_NAME` environment variable (resolved as `${COMPOSE_PROJECT_NAME:-relyloop}_default`).
  - The script **MUST** mount the 9 source paths locked in spec FR-4 (`backend/`, `migrations/`, `scripts/`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `docker-compose.yml`, `Makefile`, `samples/`) PLUS the project-root `CLAUDE.md` file (added during Phase 2 operator-path verification — the doc-checker test at `backend/tests/unit/docs/test_claude_md_sections.py` reads `CLAUDE.md` at `_REPO_ROOT/CLAUDE.md`, and without the mount the test ERRORs inside the container). Mount target paths under `/app/` to match the production image layout. The DB-secret mount uses `-v "$MAIN_REPO/secrets/database_url:/run/secrets/database_url:ro"` and the script passes `-e DATABASE_URL_FILE=/run/secrets/database_url`.
  - The script **MUST** include the workarounds for `bug_dockerfile_venv_root_owned_after_user_switch` until that Dockerfile bug ships its fix: `--user root` on the docker run AND `-e PYTHONDONTWRITEBYTECODE=1` env var. Rationale: the production image's `/app/.venv` package-metadata files are owned by root (Dockerfile line 107 `RUN uv sync --frozen --no-dev` runs before the `USER relyloop` switch at line 109), which blocks `uv run`'s implicit sync from rewriting `relyloop-0.1.0.dist-info/INSTALLER`. `--user root` bypasses the permission check; `PYTHONDONTWRITEBYTECODE=1` prevents the root-user container from writing `__pycache__/` directories into the bind-mounted host paths (backend/, migrations/, scripts/) where they would leak as root-owned files on the host. Both workarounds become deletable once the Dockerfile bug ships its fix.
  - The script **MUST** support a `--dry-run` flag that prints the constructed `docker run` argv to stdout without executing it. Format: one argument per line, ordered as it would appear in the command. The smoke test asserts against this output.
  - The script **MUST** support a `--cmd "<command>"` flag (default: `pytest backend/tests/unit/ -v`) to override the in-container command. Positional args after `--cmd` parsing pass through.
  - The script **MUST** use the `relyloop/api:${RELYLOOP_GIT_SHA:-dev}` image (matching `docker-compose.yml` lines 54 / 81 / 136).
  - The script **SHOULD** print a one-line "running tests in container <container-id-prefix>..." progress line before invoking `docker run`, and a "exited with code N" line after — operators see what's happening.
- Notes: Mechanizes FR-4's recipe. All design forks pre-locked by D-1 (Phase scope), D-2 (secrets pattern), and FR-4 (mount set + image tag + network).

### FR-9: `make test-worktree` Makefile target

- Requirement:
  - A new target `test-worktree` **MUST** live in the top-level `Makefile`. It invokes `scripts/run-tests-in-worktree.sh` and forwards a configurable `CMD` Make variable.
  - Default invocation `make test-worktree` runs the script with no `--cmd` (the script's own default of `pytest backend/tests/unit/ -v` applies).
  - Override invocation `make test-worktree CMD="pytest backend/tests/integration -v"` passes the override through to the script's `--cmd` flag.
  - The target **MUST** print a help-line if the operator runs `make test-worktree --help` or `make help` (if a `help` target exists; otherwise skip).
- Notes: Thin wrapper. Operator-path verification (CLAUDE.md Step 3 mandate) requires running `make test-worktree` end-to-end against the live stack and confirming the in-container pytest passes.

### FR-10: Smoke test for the script

- Requirement:
  - A new test file at `backend/tests/unit/scripts/test_run_tests_in_worktree.py` **MUST** cover:
    1. `test_dry_run_outputs_canonical_argv` — invokes the script with `--dry-run` via `subprocess.run`, asserts stdout contains the expected `docker run --rm --network ...` argv with all 9 source bind mounts AND the `DATABASE_URL_FILE` env var AND the `relyloop/api:dev` image (or whatever `$RELYLOOP_GIT_SHA` resolves to in the test env).
    2. `test_errors_on_missing_secret_file` — temporarily move/hide `$MAIN_REPO/secrets/database_url` (via env-var override or by running the script in a tempdir that pretends to be a fake main repo), invoke with `--dry-run`, assert non-zero exit + stderr message mentioning the missing secret.
    3. `test_errors_when_not_in_worktree` — invoke the script from a path that's not inside a git worktree (e.g., `/tmp/<scratch>`), assert non-zero exit + stderr message naming the prerequisite.
    4. `test_cmd_override_appears_in_argv` — invoke with `--dry-run --cmd "pytest foo"`, assert the constructed argv ends with `pytest foo` (or split equivalent), NOT the default.
  - Tests **MUST NOT** actually run `docker` — all assertions are against `--dry-run` stdout. CI hermeticity preserved (the existing CI smoke job's Docker dependency is already covered by the operator-path verification, not by these unit tests).
  - Pattern reference: `backend/tests/unit/scripts/test_dashboard_truncation.py` for the repo-root resolution and the `subprocess.run` style.
- Notes: 4 tests minimum (the implementer shipped 6 — adding `test_required_bind_mounts_all_present` for granular per-mount assertions and `test_cmd_override_requires_value` for the `--cmd` usage-error path). ≤250 LOC total. Sub-second runtime.

### FR-11: Runbook `docs/03_runbooks/parallel-worktrees.md`

- Requirement:
  - A new markdown runbook at `docs/03_runbooks/parallel-worktrees.md`, ≤100 lines (relaxed from the original ≤80 cap after Phase 2 GPT-5.5 review added a "Residual root-file risk" subsection covering the `bug_dockerfile_venv_root_owned_after_user_switch` workaround's side effects), **MUST** explain the parallel-worktree workflow end-to-end for human operators:
    1. When to use a sibling worktree (parallel-agent shipping, experimental feature branches that don't disturb the main stack).
    2. How to create a sibling worktree (`git worktree add /private/tmp/relyloop-<slug> -b <branch>`).
    3. How to launch an autonomous agent inside it (no canonical entry-point yet; operator-managed).
    4. How to run tests safely (`make test-worktree` from inside the sibling).
    5. Cross-reference to the CLAUDE.md "Working in sibling worktrees" section for the data-path constraints, and to `impl-execute` Step 0a / 6b / 9.3 for the lifecycle steps.
    6. Cleanup (`git worktree remove`, `git branch -D`).
  - The runbook **MUST** be linked from CLAUDE.md's "Key Runbooks" table at the bottom of the file.
- Notes: Human-facing operating procedure. The CLAUDE.md section is agent-facing; this runbook is the matching human-facing surface.

### FR-12: CLAUDE.md section reference to `make test-worktree`

- Requirement:
  - The CLAUDE.md `## Working in sibling worktrees` section **MUST** gain a new sub-heading `### Shortcut: \`make test-worktree\`` immediately before the existing `### Running tests against a sibling worktree (one-shot container recipe)` sub-heading. The shortcut subsection explains in one paragraph that `make test-worktree` wraps the recipe below, supports `CMD=` override, and points at `scripts/run-tests-in-worktree.sh` for the implementation.
  - The existing `\`\`\`bash` recipe **MUST** remain intact — it's the operator's transparency window into what the script does. FR-7 test #5 (exactly one fenced bash block) still applies; the new shortcut subsection MUST NOT introduce a second `\`\`\`bash` fence.
  - The `### Deferred capabilities` subsection **MUST** be updated: the `phase2_idea.md` bullet **MUST** be removed (capability B is no longer deferred — it shipped). The `phase3_idea.md` bullet stays.
- Notes: Minor edits to the Phase 1 section. FR-5 cross-reference to impl-execute stays unchanged. FR-7 test #5 invariant preserved (the new subsection is prose only; no new bash fence).

## 8) API and data contract baseline

### 8.1 Endpoint surface

N/A — no endpoints added or modified. This is a docs-only feature.

### 8.2 Contract rules

N/A.

### 8.3 Response examples

N/A.

### 8.4 Enumerated value contracts

N/A — no filters, status badges, sort keys, or dropdowns. The only "values" introduced are the leaky-path strings, which are not validated against any backend allowlist (they are documentation).

### 8.5 Error code catalog

N/A.

## 9) Data model and state transitions

### New/changed entities

N/A — no tables added or modified. No migration required.

### Required invariants

- **Section uniqueness invariant:** `## Working in sibling worktrees` appears exactly once in `CLAUDE.md`. Enforced by FR-7 test #1.
- **Section position invariant:** the new section appears between `## Common Pitfalls` and `## Bug Fix Protocol`. Enforced by FR-7 test #2.
- **Secrets-pattern invariant:** the new section's shell example contains no bare `DATABASE_URL=postgresql://...` env var. Enforced by FR-7 test #3 (catches CLAUDE.md Rule #2 regressions).
- **Service-attribution invariant:** in the Compose-anchored paths catalog, the rows for `./migrations/`, `./alembic.ini`, and `./samples/` do not list `worker` as an owning service, AND the row for `./data/repo-clones/` does list `worker`. Enforced by FR-7 test #4 (catches reintroduction of the original idea-brief error AND accidental removal of the legitimate worker mention).
- **Single-recipe invariant:** the section contains exactly one fenced `bash` code block (the one-shot container recipe). Enforced by FR-7 test #5.

### State transitions

N/A.

### Idempotency/replay behavior

N/A.

## 10) Security, privacy, and compliance

- **Threats:** (1) An agent leaks a sensitive artifact (e.g., a `secrets/` file generated for testing) into the main worktree via a `docker cp` write to a bind-mounted path. (2) An agent's shell example in the new section accidentally exposes a real `OPENAI_API_KEY` if pasted verbatim with a bare env var.
- **Controls:**
  1. The leaky-paths catalog explicitly enumerates the bind sources so agents see them before any `docker cp` invocation.
  2. The FR-4 shell example uses `/run/secrets/database_url` (mounted Docker secret), not a bare env var — anti-pattern documented in §4 above.
  3. The example uses `${RELYLOOP_GIT_SHA:-dev}` for the image tag, so it can't accidentally reference a private/internal registry.
- **Secrets/key handling:** No new secrets. The example references the existing `database_url` Docker secret only.
- **Auditability:** N/A — docs-only.
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Within `CLAUDE.md`, between `## Common Pitfalls` (line 352) and `## Bug Fix Protocol` (line 368). No external UI — `CLAUDE.md` is read by autonomous agents on session start, and by humans browsing the repo root.
- **Labeling taxonomy:** Section title `## Working in sibling worktrees`. Sub-headings within the section (if needed): `### The bind-mount pitfall`, `### Leaky paths catalog`, `### Safe paths`, `### Running commands against a sibling worktree`, `### Worktree lifecycle (cross-reference)`. Implementers may choose to keep the section flat (no sub-headings) if the total length is under ~40 lines.
- **Content hierarchy:** (1) Framing paragraph — what the pitfall is, where it bites. (2) Leaky-paths table — primary reference content; the thing agents will Ctrl-F to. (3) Safe-paths rule — short, just the rule + 2-3 examples. (4) "What to do instead" shell recipe — the one fenced code block, the second thing agents will Ctrl-F to. (5) Lifecycle cross-reference + deferred-phase pointer — closing one-liners.
- **Progressive disclosure:** N/A — `CLAUDE.md` is read top-to-bottom; agents don't "expand" anything.
- **Relationship to existing pages:** Sits between Pitfalls and Bug Fix Protocol. Explicitly cross-references `impl-execute` Step 0a / 6b / 9.3. Does not modify the surrounding sections.

### Tooltips and contextual help

N/A — no UI surface.

### Primary flows

1. **Agent session start.** Agent reads `CLAUDE.md` as part of standard initial context. Encounters the new section before any work. When later told "you're in a sibling worktree" or detects `pwd` outside `/Users/ericstarr/relyloop`, the agent recalls the leaky-paths table and either (a) uses the one-shot container recipe to run tests/migrations against the sibling tree, or (b) keeps all writes inside the sibling worktree's source paths and avoids `docker cp` / `docker exec` redirection into bind-mounted paths.
2. **Human operator launching a parallel agent.** Operator skims `CLAUDE.md` before launching, sees the new section, decides whether the planned work is safe to do in a sibling worktree (matches the new section's recipe) or needs to wait until the main stack is down.

### Edge/error flows

- **Agent already knows about the rule but the citations are stale.** If a future `docker-compose.yml` edit shifts bind-mount line numbers without updating the table, the agent's grounded citation will point at the wrong line. Mitigation: the FR-7 regression test does not cover line-number staleness (rejected as Phase 1 scope — too brittle), so this risk falls on the operator and reviewer at the next `docker-compose.yml` edit. A note to that effect goes in the new section's "Leaky paths catalog" subsection: "If you edit `docker-compose.yml`, re-verify the line numbers below."
- **Section gets accidentally deleted in a future doc reorg.** FR-7 regression test fails in CI; the PR can't merge until the section is restored.
- **Agent reads the section but ignores it.** Out of scope for this spec. The mitigation is the agent's overall instruction-following discipline, not a code gate.

## 12) Given/When/Then acceptance criteria

### AC-1: Section exists in CLAUDE.md between Common Pitfalls and Bug Fix Protocol

- Given the post-merge state of `CLAUDE.md` on `main`
- When a reader greps for `^## Working in sibling worktrees$` and inspects the file structure
- Then the line matches exactly once
- And the matching line appears after `## Common Pitfalls` and before `## Bug Fix Protocol`
- Example values:
  - Command: `grep -n "^## " CLAUDE.md`
  - Expected ordering (relative): `## Common Pitfalls` → `## Working in sibling worktrees` → `## Bug Fix Protocol` → `## Tangential discoveries — capture as idea files immediately` → `## Local-stub hygiene — never leave commit-eligible debug artifacts in the repo`

### AC-2: Compose-anchored host paths catalog has every bind source with verified line citations and writability state

- Given the new section
- When a reader inspects the catalog table/list
- Then the table contains exactly these entries (in any reasonable order), each with a `docker-compose.yml:<line>` citation AND a writability state:
  - `./migrations/` — writable — `migrate` (line 76), `api` (line 119)
  - `./alembic.ini` — read-only (`:ro`) — `migrate` (line 77), `api` (line 120)
  - `./samples/` — read-only (`:ro`) — `api` (line 125)
  - `./data/postgres/` — writable — `postgres` (line 28)
  - `./data/redis/` — writable — `redis` (line 40)
  - `./data/repo-clones/` — writable — `api` (line 112), `worker` (line 167)
- And `./samples/` is **not** attributed to `worker` (the idea's original attribution was wrong)
- And `./migrations/` and `./alembic.ini` are **not** attributed to `worker`
- And the writable rows note the silent-write-propagation failure mode; the read-only rows note the `EROFS` / read-only-filesystem failure mode

### AC-3: Safe-paths rule frames safety by operation mode, not by file path

- Given the new section
- When a reader inspects the "Safe paths" subsection
- Then the rule states that **direct writes** from the sibling worktree's filesystem (via `Edit`, `Write`, `git`, and plain Unix commands run outside containers) are safe even for paths whose **base name** matches a Compose bind source (sibling-local `migrations/`, `alembic.ini`, `samples/`, `data/postgres/`, etc.)
- And the rule states that **writes through an already-running shared Compose service container** to a bind-mounted in-container path land in the main worktree regardless of where the agent's `pwd` is
- And the rule names at least three concrete safe-direct-edit examples (`/private/tmp/<worktree>/backend/`, `/private/tmp/<worktree>/ui/`, `/private/tmp/<worktree>/docs/`)
- And the rule names at least two concrete forbidden command shapes (`docker cp` to a bind-mounted destination AND `docker compose exec` redirection to a bind-mounted destination)

### AC-4: One-shot container recipe uses correct image tag, Compose network, and `*_FILE`-mounted DB secret

- Given the new section
- When a reader inspects the fenced `bash` example
- Then the example uses image `relyloop/api:${RELYLOOP_GIT_SHA:-dev}` (matching `docker-compose.yml` line 54 / 81 / 136)
- And the example joins the existing Compose network (so postgres/redis/elasticsearch/opensearch are reachable by hostname)
- And the example **does not** contain the literal substring `DATABASE_URL=postgresql://` anywhere (enforced by FR-7 test #3)
- And the example **does** pass `-e DATABASE_URL_FILE=/run/secrets/database_url` to the one-shot container
- And the example **does** mount the operator's main-repo secret file as a read-only bind mount to `/run/secrets/database_url`, using either `--mount type=bind,src=$MAIN_REPO/secrets/database_url,dst=/run/secrets/database_url,readonly` (long form) or `-v $MAIN_REPO/secrets/database_url:/run/secrets/database_url:ro` (shorthand) — both are equivalent
- And the example mounts at minimum: `backend/`, `migrations/`, `scripts/`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `docker-compose.yml`, `Makefile`, `samples/`

### AC-5: Cross-reference to impl-execute Step 0a / 6b / 9.3

- Given the new section
- When a reader inspects the closing lines
- Then the section explicitly links to [`impl-execute` Step 0a](../../../../.claude/skills/impl-execute/SKILL.md), Step 6b, and Step 9.3
- And the text frames the relationship as "lifecycle vs. runtime data path" (this section adds the runtime data path coverage that the impl-execute lifecycle steps don't cover)

### AC-6: Forward-pointer to deferred phases (Phase 2 expansion: B is no longer deferred)

- Given the new section's `### Deferred capabilities` subsection
- When a reader inspects it
- Then the subsection lists capability C (per-worktree `DATABASE_URL_FILE`) with a link to `phase3_idea.md` in this feature's directory
- And the subsection does NOT list capability B / `phase2_idea.md` (capability B shipped in Phase 2; `phase2_idea.md` was deleted as part of the Phase 2 expansion)
- And `phase2_idea.md` does NOT exist on disk in this feature's directory after Phase 2 ships

### AC-7: Regression checks fail on the five enumerated failure modes

- Given the test file `backend/tests/unit/docs/test_claude_md_sections.py`
- When a developer runs `.venv/bin/pytest backend/tests/unit/docs/test_claude_md_sections.py -v`
- Then all five tests defined in FR-7 pass against the merged state
- And each test fails on its corresponding mutation:
  - `test_working_in_sibling_worktrees_section_exists` fails if the heading is deleted or duplicated
  - `test_section_ordering_between_pitfalls_and_bugfix` fails if the section is moved to a different position in `CLAUDE.md`
  - `test_section_has_no_bare_database_url_assignment` fails if a future edit adds `DATABASE_URL=postgresql://...` anywhere in the section body
  - `test_section_leakypath_catalog_attribution` fails if the catalog's `./migrations/` / `./alembic.ini` / `./samples/` rows list `worker` as an owning service, OR if the `./data/repo-clones/` row drops the legitimate `worker` mention
  - `test_section_has_exactly_one_fenced_bash_block` fails if the section has zero or more than one ` ```bash` fence
- And each failing test reports the specific failure mode in its assertion message (no opaque "False is not True" diffs)

### AC-8: `phase3_idea.md` exists in this feature's directory after PR merges (Phase 2 expansion: `phase2_idea.md` is deleted because capability B shipped)

- Given the post-merge state of `docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/`
- When a reader lists the directory
- Then `phase3_idea.md` (capability C) exists
- And `phase2_idea.md` does NOT exist (it was deleted when capability B shipped in Phase 2)
- And `phase3_idea.md` follows [`feature_templates/idea-template.md`](../feature_templates/idea-template.md), includes an Origin pointer back to this spec, and re-states both D-1 (phase split) and D-2 (secrets convention)

### AC-9: `scripts/run-tests-in-worktree.sh` constructs the expected `docker run` invocation

- Given the new shell script at `scripts/run-tests-in-worktree.sh`
- When a developer invokes `scripts/run-tests-in-worktree.sh --dry-run` from inside the main worktree (or from a sibling worktree)
- Then the script prints the constructed `docker run` argv to stdout (one argument per line, in canonical order)
- And the argv contains: `--rm`, `--user root` (workaround for `bug_dockerfile_venv_root_owned_after_user_switch`), `--network <relyloop-default-or-override>`, `-e DATABASE_URL_FILE=/run/secrets/database_url`, `-e PYTHONDONTWRITEBYTECODE=1` (same bug workaround — prevents root-owned `__pycache__` leak), exactly 11 `-v` mounts (the DB secret + `CLAUDE.md` + the 9 source paths from FR-4), the `relyloop/api:${RELYLOOP_GIT_SHA:-dev}` image tag, and the default command `uv run pytest backend/tests/unit/ -v` (the `uv run` prefix triggers on-demand dev-dep installation since the production image is built with `--no-dev`)
- And the script exits 0 from `--dry-run` mode

### AC-10: Script fails with clear errors on missing prerequisites

- Given the script
- When invoked with a missing `$MAIN_REPO/secrets/database_url` file
- Then the script exits non-zero with a stderr message that names the missing file AND references CLAUDE.md Rule #2 AND points at `scripts/install.sh` for secret regeneration
- And when invoked from a path outside any git worktree, the script exits non-zero with a stderr message naming the prerequisite (`must be run from inside a git worktree`)

### AC-11: `make test-worktree` end-to-end run passes

- Given the live Compose stack (`make up` healthy) and the new `make test-worktree` target
- When the operator runs `make test-worktree` from inside the main worktree
- Then the script spins up a one-shot container against the Compose network, runs `pytest backend/tests/unit/ -v` inside it, and exits 0
- And the operator's main-worktree `./migrations/`, `./samples/`, `./alembic.ini` are NOT modified by the run (no leak)
- And the smoke-test alternative `make test-worktree CMD="pytest backend/tests/unit/docs/ -v"` invokes the override command (verified by the script's progress line showing the override)

### AC-12: Runbook + CLAUDE.md shortcut subsection are present

- Given `docs/03_runbooks/parallel-worktrees.md`
- When a reader inspects it
- Then the file exists, is ≤80 lines, follows the project's runbook markdown style, and is linked from CLAUDE.md's "Key Runbooks" table
- And CLAUDE.md's `## Working in sibling worktrees` section has a new `### Shortcut: \`make test-worktree\`` subsection immediately before the existing `### Running tests against a sibling worktree (one-shot container recipe)` subsection
- And FR-7 test #5 (exactly one fenced `bash` block in the section) still passes — the new shortcut subsection introduces no new `\`\`\`bash` fence

## 13) Non-functional requirements

- **Performance:** N/A — docs-only.
- **Reliability:** The FR-7 regression test catches accidental deletion. No SLO impact.
- **Operability:** No logging/metrics/alerts. The new section makes the agent operator manual marginally more reliable (fewer footgun events expected in future parallel-agent runs).
- **Accessibility/usability:** N/A — markdown doc, no UI.

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/docs/`):** One new test file `test_claude_md_sections.py` with the **five** tests enumerated in FR-7: `test_working_in_sibling_worktrees_section_exists`, `test_section_ordering_between_pitfalls_and_bugfix`, `test_section_has_no_bare_database_url_assignment`, `test_section_leakypath_catalog_attribution`, `test_section_has_exactly_one_fenced_bash_block`. They share a module-level fixture that reads `CLAUDE.md` once and slices the section body between `## Working in sibling worktrees` and the next `## ` header. Test #4 specifically parses the leaky-paths catalog rows (not the whole section) — see FR-7 for the precise targeting.
- **Integration tests:** N/A — no DB, no service, no workflow.
- **Contract tests:** N/A — no endpoints.
- **E2E tests:** N/A — no UI.

Coverage gate impact: the new test adds a small amount of coverage but the feature itself is docs-only (no Python code is changed), so the 80% gate is not at risk.

## 15) Documentation update requirements

- `docs/01_architecture/`: No updates required. The bind-mount facts are already implicit in `docker-compose.yml`; no architecture-level invariant changes.
- `docs/02_product/`: `pipeline_status.md` (new) + `phase2_idea.md` (new) + `phase3_idea.md` (new) in this feature's directory.
- `docs/03_runbooks/`: No updates required. The new content is agent-facing operating guidance, not an ops procedure.
- `docs/04_security/`: No updates required. The §10 threat scenarios are bounded to the new section's own anti-patterns.
- `docs/05_quality/`: No updates required.
- `CLAUDE.md` (project root): The substantive change — addition of the new section per FR-1 through FR-6.
- `state.md` (project root): Add a one-line "recent changes" entry naming this feature and PR number on merge.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — docs change, ship at merge.
- **Migration/backfill expectations:** None — no schema change.
- **Rollout reach — sibling worktrees auto-inherit on session start.** Claude Code's CLAUDE.md auto-loader reads `<pwd>/CLAUDE.md` at session start. Sibling worktrees have their own `pwd`, so any new agent session (including [`impl-execute` Step 6b](../../../../.claude/skills/impl-execute/SKILL.md) `Agent({ isolation: "worktree" })` spawns) launched in a worktree branched off `main` after the Phase 1 PR merges will read the post-merge `CLAUDE.md` automatically — no prompt-template injection, no manual paste required for the steady-state case. Edge case: a worktree branched off a long-lived feature branch that diverged from `main` before this PR merged would not see the new section until that feature branch rebases on `main`. The mitigation is the existing `impl-execute` Step 0a worktree pre-flight discipline (audit + rebase before launching). No new gate; this is a property of the existing flow, not a new requirement.
- **In-flight agent rollout note.** Agents already running with cached system context at the time of merge will not see the new section until they restart or until the operator pastes the new content into their active context. Because the population of "agents running parallel-worktree work at any given moment" is ~0–1 (this is the operator's local-only flow), no formal staged rollout is needed; the operator should restart any in-flight sibling-worktree agents after merge or paste the new section into their context if asked to touch Docker/container paths.
- **Operational readiness gates:** Standard PR gates: lint, mypy, unit tests, GPT-5.5 review per [`CLAUDE.md`](../../../../CLAUDE.md) "Cross-model review policy", Gemini Code Assist adjudication. No new gates.
- **Release gate:** CI green; Gemini review adjudicated; FR-7 regression tests (all five) passing; `phase2_idea.md` and `phase3_idea.md` files committed in this feature's directory; reviewer approval.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1 | Story 1.1 (write the section in `CLAUDE.md`) | `backend/tests/unit/docs/test_claude_md_sections.py::test_working_in_sibling_worktrees_section_exists` + `::test_section_ordering_between_pitfalls_and_bugfix` | `CLAUDE.md` |
| FR-2 | AC-2 | Story 1.1 | `backend/tests/unit/docs/test_claude_md_sections.py::test_section_leakypath_catalog_attribution` (content review for line citations + writability column at PR time) | `CLAUDE.md` |
| FR-3 | AC-3 | Story 1.1 | (PR review — semantic correctness of the safe-paths rule is content-shaped, not regex-shaped) | `CLAUDE.md` |
| FR-4 | AC-4 | Story 1.1 | `backend/tests/unit/docs/test_claude_md_sections.py::test_section_has_no_bare_database_url_assignment` + `::test_section_has_exactly_one_fenced_bash_block` | `CLAUDE.md` |
| FR-5 | AC-5 | Story 1.1 | (PR review) | `CLAUDE.md` |
| FR-6 | AC-6 | Story 1.1 (write the forward-pointer paragraph inside the new `CLAUDE.md` section) + Story 1.2 (write `phase2_idea.md` + `phase3_idea.md`) | (PR review — verifies the section contains the forward-pointer prose AND the two tracking files exist) | `CLAUDE.md` (forward-pointer text), `docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase2_idea.md`, `phase3_idea.md` |
| FR-7 | AC-7 | Story 1.3 (regression tests) | `backend/tests/unit/docs/test_claude_md_sections.py` (all 5 tests) | (none — test file is the artifact) |
| (out of FR — Step 10 deferred-phase tracking) | AC-8 | Story 1.2 | (PR review + `/pipeline status` smoke) | `docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase2_idea.md`, `phase3_idea.md` |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-8) pass.
- [ ] The unit test layer is green (`make test-unit`), including the new `test_claude_md_sections.py`.
- [ ] `CLAUDE.md` contains the new section and the surrounding section ordering is unchanged.
- [ ] `phase2_idea.md` and `phase3_idea.md` exist in this feature's directory with the deferred-capability content from §3 above.
- [ ] `pipeline_status.md` is updated to show Spec + Plan + Implementation = Complete.
- [ ] `state.md` has a one-line "recent changes" entry pointing to the merge commit.
- [ ] PR has Gemini Code Assist adjudication complete and CI green.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

(None remaining at spec-finalization time — all three of the idea's OQs were locked via recommended-defaults under Auto Mode.)

### Decision log

- **2026-05-23** — D-1 (idea, locked here): Phase 1 ships **capability A only**. Capabilities B (the test-runner script) and C (per-worktree `DATABASE_URL_FILE`) are deferred to `phase2_idea.md` / `phase3_idea.md` and picked up when the friction recurs. Rationale: A is ~30 min of work, immediately useful; B and C wait for second-occurrence triggers (a new parallel-agent test-execution event for B; a migration-collision incident for C). Matches the "Why deferred" rationale in the idea.
- **2026-05-23** — D-2 (idea, locked here): Any future per-worktree `DATABASE_URL` override **MUST** use the `*_FILE`-mounted-secret pattern (CLAUDE.md Absolute Rule #2). No bare env vars. The most likely concrete shape: a `./secrets/database_url.worktree-<hash>` file generated on the fly by the Phase-2 entrypoint, mounted via Docker secrets or a temp bind mount. Pre-locking this constraint at Phase 1 spec time prevents Phase 3 from re-debating it.
- **2026-05-25** — OQ-1 lock (recommended default from idea, accepted under Auto Mode): New section sits between `## Common Pitfalls` and `## Bug Fix Protocol`. Rationale: it's an operational pattern that's bigger than a one-line pitfall but doesn't warrant an architecture-doc page of its own. A top-level `##` keeps it discoverable by Ctrl-F search.
- **2026-05-25** — OQ-2 lock (recommended default): Static prose list of bind-mount paths in Phase 1; dynamic generation (a `make doctor-worktree` target or similar) waits until Phase 2 or later. Rationale: bind-mount additions are infrequent (the current set hasn't changed since `infra_foundation`), and PR review catches drift well enough; dynamic generation would require parsing `docker-compose.yml` and adds maintenance surface for marginal benefit.
- **2026-05-25** — OQ-3 lock (recommended default): Yes, include the one-shot container shell recipe inline. Rationale: agents that don't see the recipe re-derive it from scratch (the reconciler agent's transcript shows ~4 verification cycles before settling on the 8-flag pattern). Locking it in the spec saves future agents 5–10 minutes per parallel-agent session.
- **2026-05-25** — Scope boundary: docker-compose.yml line attribution corrected from the idea's wording. Idea said the worker service had `./migrations`, `./alembic.ini`, and `./samples` bind mounts at lines 119–125; direct read of `docker-compose.yml` shows those lines belong to the `api` service, and the `worker` only mounts `./data/repo-clones` (line 167). Spec uses the verified attribution.
- **2026-05-25** — Test scope boundary: the FR-7 regression suite asserts five things — section presence + ordering + absence of bare `DATABASE_URL=postgresql://` + absence of `worker.*migrations|alembic|samples` attribution + exactly-one fenced `bash` block. It does NOT verify the leaky-paths table cites the right `docker-compose.yml` line numbers — that would be brittle (line numbers shift on every Compose edit) and the alternative (YAML-parsing test) is exactly what OQ-2 deferred. Line-number quality is enforced at PR review time, not by an automated test. Cycle-1 GPT-5.5 review correctly pushed against the original "header-only" formulation; the expanded 5-test suite is the convergence outcome.
- **2026-05-25** — Cycle-1 GPT-5.5 review adjudication summary: 11 findings, all accepted (9 fully, 2 partially/with reframing). Major accepted changes that altered FR contracts: FR-3 reframed from "path-based safety" to "operation-mode-based safety" (a sibling worktree's own `migrations/` is safe to edit directly; container-mediated writes are the hazard); FR-4 sharpened to mandate the explicit `--mount ... src=$MAIN_REPO/secrets/database_url ...` + `-e DATABASE_URL_FILE=...` mechanism rather than the under-specified "use the Docker secret" wording; FR-7 expanded from one test to five covering the actual historical failure modes (wrong content with header still present). Minor accepted changes: link path shape `(docker-compose.yml#L<line>)` not `(../docker-compose.yml#L<line>)`; §1 incident wording de-incorrectly-attributed from "Postgres container" to "API/migrate container"; FR-2 worded for multi-service attribution; anti-patterns expanded to include `docker compose cp` and `docker compose exec`; §16 added an in-flight-agent rollout note; §5 added the spawned-agent CLAUDE.md inheritance assumption.
- **2026-05-25** — Cycle-2 GPT-5.5 review adjudication summary: 5 new findings (none repeats), all accepted (4 fully + 1 reframed). Major accepted changes: (a) catalog reframed from "leaky paths" to "Compose-anchored host paths" with writability state per row — `:ro` mounts (`./alembic.ini`, `./samples/`) fail loudly with `EROFS` rather than silently propagating writes, so the catalog distinguishes the two failure modes; (b) FR-7 test #4 retargeted from broad section-wide `worker.*migrations` regex to specific catalog-row inspection, eliminating the false-positive risk against legitimate prose like the data/repo-clones row's required `worker` mention. Minor accepted changes: §2/§3/§4/§14 all updated to consistently describe the 5-test suite (cycle 1 patched FR-7 and AC-7 but left summary sections stale); `--mount ... readonly` vs `-v ...:ro` shorthand normalized as "either is acceptable" throughout FR-4 / §4 / AC-4; spawned-agent CLAUDE.md inheritance promoted from §5 "assumption with risk: zero" to §16 "rollout reach" — verified by Claude Code's session-start behavior (auto-loader reads `<pwd>/CLAUDE.md`, worktrees have their own `pwd`), not just hoped-for behavior.
- **2026-05-25** — Cycle-3 GPT-5.5 convergence-check adjudication summary: 1 blocking finding, accepted. §17 traceability matrix had two stale references after cycle-2 renames: the FR-2 test-name reference still said `test_section_does_not_attribute_migrations_to_worker` (cycle-2 renamed to `test_section_leakypath_catalog_attribution`); the FR-6 row only listed `phase2_idea.md` / `phase3_idea.md` in the docs column but FR-6 also requires the forward-pointer prose inside `CLAUDE.md`. Both fixed in-place. No new FR contracts altered; this is a pure consistency patch.
