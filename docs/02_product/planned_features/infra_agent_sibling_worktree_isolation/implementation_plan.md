# Implementation Plan — Sibling-worktree isolation guidance in CLAUDE.md (Phase 1)

**Date:** 2026-05-25
**Status:** Complete (PR #249 admin-merged 2026-05-25 as squash commit `22f878f`; Phase 1 + Phase 2 shipped; Phase 3 deferred per `phase3_idea.md`)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):**
- [`CLAUDE.md`](../../../../CLAUDE.md) — Absolute Rules #2 (secrets via mounted files), #7 (Conventional Commits), §"Bug Fix Protocol" (regression test discipline)
- [`docker-compose.yml`](../../../../docker-compose.yml) — canonical source of bind-mount truth (lines 28, 40, 76, 77, 112, 119, 120, 125, 167)
- [`.claude/skills/impl-execute/SKILL.md`](../../../../.claude/skills/impl-execute/SKILL.md) — Step 0a / 6b / 9.3 (worktree lifecycle — cross-referenced, NOT duplicated)

---

## 0) Planning principles

- **Docs-only scope.** No production Python code, no migrations, no API routes, no UI. The "implementation" is one prose section + one regression test file.
- **Spec is the contract.** Every story task traces to an FR or AC from [`feature_spec.md`](feature_spec.md). The spec already converged through 3 GPT-5.5 cycles; the plan does not re-litigate spec decisions.
- **Auto-inheritance is the rollout mechanism.** Per spec §16, Claude Code reads `<pwd>/CLAUDE.md` on session start, so sibling worktrees branched off `main` after this PR merges automatically pick up the new section. No prompt-template injection step.
- **Regression tests are bounded.** Per spec FR-7, the 5 tests cover historically-observed failure modes only — section presence, ordering, no bare `DATABASE_URL=postgresql://`, catalog-row attribution, exactly-one fenced bash block. Line-number staleness in the catalog citations is a PR-review concern (OQ-2 deferred), not a test concern.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Story | Notes |
|---|---|---|---|
| FR-1 (new `## Working in sibling worktrees` section in CLAUDE.md, between Common Pitfalls and Bug Fix Protocol) | Epic 1 / Phase 1 | Story 1.1 | Section structure + opening framing paragraph. Tested by Story 1.2 tests #1 + #2. |
| FR-2 (Compose-anchored host paths catalog with writability column + per-path service citations) | Epic 1 / Phase 1 | Story 1.1 | Six rows: `./migrations/`, `./alembic.ini`, `./samples/`, `./data/postgres/`, `./data/redis/`, `./data/repo-clones/`. Tested by Story 1.2 test #4. |
| FR-3 (operation-mode-based safe-paths rule: direct writes safe; container-mediated writes hazardous) | Epic 1 / Phase 1 | Story 1.1 | Three named safe-direct examples + two forbidden command shapes. Content correctness is PR-review only. |
| FR-4 (one-shot container shell recipe with `*_FILE`-mounted DB secret) | Epic 1 / Phase 1 | Story 1.1 | Exactly one fenced bash block. `--mount` or `-v ...:ro` accepted. Tested by Story 1.2 tests #3 + #5. |
| FR-5 (cross-reference to impl-execute Step 0a / 6b / 9.3) | Epic 1 / Phase 1 | Story 1.1 | One-line pointer. PR-review only. |
| FR-6 (forward-pointer to deferred phase2_idea.md / phase3_idea.md) | Epic 1 / Phase 1 | Story 1.1 | One-line pointer. The `phase2_idea.md` and `phase3_idea.md` files already exist (written during spec-gen Step 10); this story only adds the in-CLAUDE.md link to them. PR-review only. |
| FR-7 (5-test regression suite at `backend/tests/unit/docs/test_claude_md_sections.py`) | Epic 1 / Phase 1 | Story 1.2 | All 5 tests, sharing a module-level fixture. |
| AC-8 (`phase2_idea.md` + `phase3_idea.md` exist, follow `feature_templates/idea-template.md`, contain Origin pointer + D-1/D-2 content) | Epic 1 / Phase 1 | Story 1.3 | Verification-only story — the files already exist (created during spec-gen Step 10); Story 1.3 audits their content shape against AC-8. |

All seven FRs + AC-8 covered. No deferred-phase FRs in this plan — Phase 2 (capability B) and Phase 3 (capability C) are tracked separately in `phase2_idea.md` and `phase3_idea.md` per spec D-1.

## 2) Delivery structure

Three stories in one epic. Story 1.1 writes the prose; Story 1.2 writes the regression tests; Story 1.3 verifies the deferred-phase tracking artifacts (`phase2_idea.md`, `phase3_idea.md`) satisfy AC-8. The split gives a clean test-then-verify gate between content delivery and PR-ready state.

### Conventions (project-specific)

- **Conventional Commits format** — story commits use `docs(worktree-isolation): ...` (Story 1.1, Story 1.3) or `test(worktree-isolation): ...` (Story 1.2) prefixes per CLAUDE.md Rule #7. Scope is `worktree-isolation` (matching the abbreviated branch name).
- **Pre-commit hooks must not be bypassed** — no `--no-verify`. Story 1.1 changes only Markdown so `ruff` / `mypy` / `prettier` skip those files. Story 1.2 adds a Python file (`backend/tests/unit/docs/test_claude_md_sections.py`) so `ruff` AND `mypy` (via `uv run`) will lint and type-check it — both MUST pass (the test file is part of the typechecked tree, and Story 1.2's DoD already calls `make lint` and `make typecheck` to confirm). Regardless of which hooks skip vs. run, the always-on hooks (`Detect hardcoded secrets`, `check for added large files`, `mixed line ending`, `Conventional Commits format check`) execute on every commit and must pass.
- **The new test file's imports** follow the `backend/tests/unit/scripts/test_dashboard_truncation.py:14-16` pattern for resolving the repo root: `_REPO_ROOT = Path(__file__).resolve().parents[4]`. Same parent count works because both `unit/scripts/` and `unit/docs/` are 4 levels deep from repo root.
- **No new Python source code in `backend/app/`** — therefore no impact on `[tool.coverage.report].fail_under = 80` (the 80% gate measures source-line coverage in the production app tree, not the test directory itself).

### AI Agent Execution Protocol

The standard protocol from the template applies, but several steps are no-ops for a docs-only PR:

0. **Load context first**: Read [`feature_spec.md`](feature_spec.md), [`docker-compose.yml`](../../../../docker-compose.yml), and [`CLAUDE.md`](../../../../CLAUDE.md) lines 352–380 (the surrounding sections) before starting Story 1.1.
1. **Read scope**: verify the spec's FR-1 through FR-7 plus AC-1 through AC-8.
2. **Implement backend first** — *N/A, no backend changes.*
3. **Run backend tests** — Story 1.2 runs `.venv/bin/pytest backend/tests/unit/docs/ -v` after writing the tests.
4. **Implement frontend** — *N/A, no UI changes.*
5. **Run E2E scope** — *N/A, no UI to test.*
6. **Update docs/checklists** — `state.md` gets a one-line "recent changes" entry as part of impl-execute Step 8.6 finalization, not as a per-story task.
7. **Verify migration round-trip** — *N/A, no schema change.*
8. **Attach evidence** in PR description: `pytest backend/tests/unit/docs/ -v` output (5 tests pass), grep evidence that the section exists at the expected position in CLAUDE.md.

---

## Epic 1 — CLAUDE.md sibling-worktree section + regression suite

### Story 1.1 — Add `## Working in sibling worktrees` section to CLAUDE.md

**Outcome:** Future autonomous agents reading CLAUDE.md on session start receive the bind-mount-anchors-to-main pitfall guidance + safe-paths rule + one-shot container recipe, addressing the failure mode that PR #216 surfaced. The section satisfies FR-1 through FR-6.

**New files**

(None.)

**Modified files**

| File | Change |
|---|---|
| `CLAUDE.md` (project root) | Insert a new top-level `## Working in sibling worktrees` section between line 367 (end of `## Common Pitfalls`) and line 368 (start of `## Bug Fix Protocol`). Section length budget: ~50–80 lines. Verified surrounding section ordering: `## Common Pitfalls` (352) → `## Working in sibling worktrees` (new) → `## Bug Fix Protocol` (368 → shifts to ~430) → `## Tangential discoveries — capture as idea files immediately` (currently 381) → `## Local-stub hygiene — never leave commit-eligible debug artifacts in the repo` (currently 443). |

**Endpoints** — N/A (docs-only).

**Key interfaces** — N/A (docs-only).

**Pydantic schemas** — N/A.

**UI element inventory** — N/A (no UI; CLAUDE.md is markdown read by agents).

**State dependency analysis** — N/A.

**Section content blueprint** (the implementer is free to refine prose, but the structure and content tokens below are the AC contract):

```markdown
## Working in sibling worktrees

When an autonomous agent works in a sibling git worktree (e.g.,
`/private/tmp/relyloop-<slug>`) while the operator's main checkout
(`/Users/ericstarr/relyloop`) has the Docker Compose stack running, the
shared Docker bind mounts defined in [`docker-compose.yml`](docker-compose.yml)
all anchor to the **main worktree**, not the sibling. Writes through a
running shared container can land bytes in the wrong worktree silently
(for writable mounts) or fail with `EROFS` (for read-only mounts). This
was surfaced concretely by the `chore_reconciler_terminal_closed_no_poll`
agent run ([PR #216](https://github.com/SoundMindsAI/relyloop/pull/216),
merged 2026-05-23), where a migration file written via `docker cp` into
a shared container's `/app/migrations/` appeared as an untracked file in
the operator's main worktree.

### Compose-anchored host paths

The Compose stack at [`docker-compose.yml`](docker-compose.yml) binds
these host paths into one or more service containers. Writes through a
running shared container to the in-container target resolve to **the main
worktree's** host path.

| Host path | Writability | Service(s) | Failure mode (container-mediated write) |
|---|---|---|---|
| `./migrations/` | writable | `migrate` ([docker-compose.yml:76](docker-compose.yml#L76)), `api` ([docker-compose.yml:119](docker-compose.yml#L119)) | bytes silently propagate to main worktree's `./migrations/` |
| `./alembic.ini` | read-only (`:ro`) | `migrate` ([docker-compose.yml:77](docker-compose.yml#L77)), `api` ([docker-compose.yml:120](docker-compose.yml#L120)) | container-mediated writes fail with `EROFS` / read-only filesystem; the file is anchored to the main worktree but cannot be modified through the shared container |
| `./samples/` | read-only (`:ro`) | `api` ([docker-compose.yml:125](docker-compose.yml#L125)) | container-mediated writes fail with `EROFS` / read-only filesystem; the file is anchored to the main worktree but cannot be modified through the shared container |
| `./data/postgres/` | writable | `postgres` ([docker-compose.yml:28](docker-compose.yml#L28)) | bytes silently propagate to main worktree's `./data/postgres/` |
| `./data/redis/` | writable | `redis` ([docker-compose.yml:40](docker-compose.yml#L40)) | bytes silently propagate to main worktree's `./data/redis/` |
| `./data/repo-clones/` | writable | `api` ([docker-compose.yml:112](docker-compose.yml#L112)), `worker` ([docker-compose.yml:167](docker-compose.yml#L167)) | bytes silently propagate to main worktree's `./data/repo-clones/` |

> If you edit `docker-compose.yml`, re-verify the line citations above in
> the same PR. The unit test at
> `backend/tests/unit/docs/test_claude_md_sections.py` does not enforce
> line-number freshness — it asserts only that the catalog rows for
> `./migrations/`, `./alembic.ini`, and `./samples/` do not list
> `worker`, that the row for `./data/repo-clones/` does list `worker`,
> and that the section's shell example contains no bare `DATABASE_URL=`.

### Safe paths

**Direct writes from the sibling worktree's filesystem are always safe.**
The `Edit`, `Write`, and `git` tools (and any plain Unix command run
outside a container) write to the sibling's own copy of the file. This
includes paths whose **base name** matches a Compose bind source:
`/private/tmp/<slug>/backend/`, `/private/tmp/<slug>/ui/`,
`/private/tmp/<slug>/docs/`, `/private/tmp/<slug>/migrations/0042_foo.py`,
`/private/tmp/<slug>/samples/products.json`, and
`/private/tmp/<slug>/alembic.ini` are all sibling-local. The Compose
stack's bind mounts target the **main worktree's** `./migrations/`, not
"any worktree's `migrations/`".

**Writes through an already-running shared Compose service container
resolve to the main worktree's bind source** — silently for writable
mounts, loudly with `EROFS` for read-only mounts. Forbidden command
shapes (whether invoked from a sibling worktree or anywhere else):

- `docker cp <local> <container>:<bind-mounted-path>`
- `docker compose cp <local> <service>:<bind-mounted-path>`
- `docker exec <container> sh -c '... > <bind-mounted-path>'`
- `docker compose exec <service> sh -c '... > <bind-mounted-path>'`

The hazard is the bind source the running container resolves to, not the
command form. Any debug stubs created during sibling-worktree work are
still subject to the "Local-stub hygiene" rule below.

### Running tests against a sibling worktree (one-shot container recipe)

Use a one-shot `docker run` invocation that mounts the **sibling
worktree's** source tree and joins the existing Compose network:

```bash
# Run from the sibling worktree's root (e.g., /private/tmp/relyloop-<slug>).
# $MAIN_REPO is the operator's main checkout (typically /Users/ericstarr/relyloop).
# The DB-secret mount honors CLAUDE.md Rule #2: never bare DATABASE_URL=, always
# the *_FILE-mounted pattern that matches docker-compose.yml lines 68 / 95 / 153.
MAIN_REPO=/Users/ericstarr/relyloop
docker run --rm \
  --network relyloop_default \
  -e DATABASE_URL_FILE=/run/secrets/database_url \
  -v "$MAIN_REPO/secrets/database_url:/run/secrets/database_url:ro" \
  -v "$PWD/backend:/app/backend" \
  -v "$PWD/migrations:/app/migrations" \
  -v "$PWD/scripts:/app/scripts" \
  -v "$PWD/pyproject.toml:/app/pyproject.toml:ro" \
  -v "$PWD/uv.lock:/app/uv.lock:ro" \
  -v "$PWD/alembic.ini:/app/alembic.ini:ro" \
  -v "$PWD/docker-compose.yml:/app/docker-compose.yml:ro" \
  -v "$PWD/Makefile:/app/Makefile:ro" \
  -v "$PWD/samples:/app/samples:ro" \
  "relyloop/api:${RELYLOOP_GIT_SHA:-dev}" \
  pytest backend/tests/unit/ -v
```

### Worktree lifecycle (cross-reference)

This section covers the **runtime data path** (what's safe to write to
from inside a sibling worktree). For worktree **lifecycle** — audit
before launching, spawn parallel test agents with `Agent({ isolation:
"worktree" })`, and sweep stale worktrees after a feature merges — see
[`impl-execute` SKILL.md](.claude/skills/impl-execute/SKILL.md) Step 0a,
Step 6b, and Step 9.3. The two coverages are complementary, not
redundant.

### Deferred capabilities

Two follow-on capabilities are tracked as deferred-phase ideas in the
feature's planned-features folder, picked up when the friction recurs:

- [`phase2_idea.md`](docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase2_idea.md) — a `scripts/run-tests-in-worktree.sh` (or `make test-worktree` target) that wraps the recipe above.
- [`phase3_idea.md`](docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase3_idea.md) — per-worktree `DATABASE_URL_FILE` override following the `*_FILE`-mounted-secret pattern (locked by D-2 in the spec).
```

**Tasks**

1. **Read context.** Read [`feature_spec.md`](feature_spec.md) §1, §2, §3, §7 (FR-1 through FR-6), and §12 (AC-1 through AC-6). Read [`CLAUDE.md`](../../../../CLAUDE.md) lines 350–380 to confirm the insertion point is between `## Common Pitfalls` (line 352) and `## Bug Fix Protocol` (line 368). Re-verify [`docker-compose.yml`](../../../../docker-compose.yml) bind-mount lines 28, 40, 76, 77, 112, 119, 120, 125, 167 are still at those positions; if not, update the catalog citations accordingly.
2. **Insert the section.** Use the content blueprint above as the starting template. The implementer may refine prose and formatting, but MUST preserve:
   - The exact `## Working in sibling worktrees` heading (FR-1, AC-1).
   - The opening paragraph linking to [`docker-compose.yml`](docker-compose.yml) as the authoritative bind-mount source (FR-1).
   - The 6-row catalog rendered as a **Markdown table** with writability column and per-path service citations (FR-2, AC-2). The catalog MUST be a table (not a bulleted list) — the test parser in Story 1.2 targets the table format specifically. Citation link shape is the verbose form `[docker-compose.yml:<line>](docker-compose.yml#L<line>)` (repo-root-relative path, since CLAUDE.md is at repo root). For each read-only entry, the failure-mode cell MUST include both facts: "`EROFS` / read-only filesystem" AND "the file is anchored to the main worktree but cannot be modified through the shared container" (FR-2).
   - The operation-mode-based safe-paths rule with at least 3 named safe-direct examples and 2 named forbidden command shapes (FR-3, AC-3).
   - Exactly one fenced ` ```bash` code block (FR-4, AC-4) containing the one-shot container recipe. The recipe must mount `backend/`, `migrations/`, `scripts/`, `pyproject.toml`, `uv.lock`, `alembic.ini`, `docker-compose.yml`, `Makefile`, `samples/`. The recipe must include `-e DATABASE_URL_FILE=/run/secrets/database_url` AND a read-only bind mount of `$MAIN_REPO/secrets/database_url` to `/run/secrets/database_url`. The recipe must NOT contain the literal `DATABASE_URL=postgresql://`.
   - The lifecycle cross-reference to `impl-execute` Step 0a / 6b / 9.3 (FR-5, AC-5).
   - The deferred-phases forward-pointer to `phase2_idea.md` and `phase3_idea.md` (FR-6, AC-6).
3. **Verify section ordering locally.** Run `grep -n "^## " CLAUDE.md` and confirm the ordering matches AC-1's expected sequence (`Common Pitfalls` → `Working in sibling worktrees` → `Bug Fix Protocol` → `Tangential discoveries...` → `Local-stub hygiene...`).
4. **Verify markdown link validity.** Run `grep -E '\[.*\]\([^)]*\)' CLAUDE.md` against the new section and spot-check that the `docker-compose.yml#L<line>` anchors and the `phase2_idea.md` / `phase3_idea.md` / `impl-execute` SKILL.md paths resolve (the `Read` tool against each link target should succeed).
5. **Commit.** One commit on the feature branch with message `docs(worktree-isolation): add Working in sibling worktrees section to CLAUDE.md`.

**Definition of Done (DoD)**

- [ ] `CLAUDE.md` contains the `## Working in sibling worktrees` section exactly once (verified by Story 1.2 test #1 once written, OR by manual `grep -c "^## Working in sibling worktrees$" CLAUDE.md` returning `1`).
- [ ] Section appears between `## Common Pitfalls` and `## Bug Fix Protocol` (verified by Story 1.2 test #2 once written, OR by manual `grep -n "^## " CLAUDE.md` ordering check).
- [ ] The section's catalog has 6 rows with the expected service attributions per AC-2: no `worker` in `./migrations/` / `./alembic.ini` / `./samples/` rows; `worker` present in `./data/repo-clones/` row.
- [ ] The section's shell example contains no bare `DATABASE_URL=postgresql://` (verified by Story 1.2 test #3 once written).
- [ ] The section contains exactly one fenced ` ```bash` block (verified by Story 1.2 test #5 once written).
- [ ] The section's forward-pointer to `phase2_idea.md` and `phase3_idea.md` resolves to the existing files in the feature directory.
- [ ] No bypass of pre-commit hooks; commit message follows Conventional Commits with `docs(worktree-isolation):` prefix.

---

### Story 1.2 — Add 5-test regression suite at `backend/tests/unit/docs/test_claude_md_sections.py`

**Outcome:** A regression suite that catches the five historically-observed failure modes for the new section: deletion, re-ordering, re-introduction of bare `DATABASE_URL=`, mis-attribution of `worker` to `./migrations/` / `./alembic.ini` / `./samples/`, and duplication of the shell recipe. Satisfies FR-7 and AC-7.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/docs/__init__.py` | Empty package marker file (0 bytes), matching the existing `backend/tests/unit/scripts/__init__.py` pattern (verified during plan-gen Step 2 — it is 0 bytes). **Justification against the spec's "narrow artifact set" wording:** package marker files are a mechanical Python convention required by this repo's existing test layout (every sibling `backend/tests/unit/<subdir>/` carries one); adding `docs/` without an `__init__.py` would be the deviation from convention, not the adherence to it. The spec's "no code changes" intent (§3) excludes production code, not pytest scaffolding. |
| `backend/tests/unit/docs/test_claude_md_sections.py` | Five regression tests + module-level fixture that reads `CLAUDE.md` once and slices the section body. |

**Modified files**

(None — the test file is purely additive. No `conftest.py` change needed; the existing fixture pattern from `backend/tests/unit/scripts/test_dashboard_truncation.py:14-16` is duplicated module-locally.)

**Endpoints** — N/A.

**Key interfaces**

The test file is small; only the fixture deserves a documented signature:

```python
# backend/tests/unit/docs/test_claude_md_sections.py
import pytest
from pathlib import Path

# CLAUDE.md is at repo root. backend/tests/unit/docs/ is 4 levels deep — same
# parent count as backend/tests/unit/scripts/test_dashboard_truncation.py:14.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"
_SECTION_HEADER = "## Working in sibling worktrees"


@pytest.fixture(scope="module")
def claude_md_text() -> str:
    """Read CLAUDE.md once; tests share the text."""
    return _CLAUDE_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def section_body(claude_md_text: str) -> str:
    """Return the body between `## Working in sibling worktrees` and the next `## ` heading."""
    ...  # see Tasks below for exact extraction logic
```

**Pydantic schemas** — N/A.

**UI element inventory** — N/A.

**State dependency analysis** — N/A.

**Tasks**

1. **Create the package marker.** `backend/tests/unit/docs/__init__.py` as an empty file (matches `backend/tests/unit/scripts/__init__.py`, which is also 0 bytes).
2. **Write `backend/tests/unit/docs/test_claude_md_sections.py`** with five tests:

   - `test_working_in_sibling_worktrees_section_exists(claude_md_text)` — assert `claude_md_text.count("## Working in sibling worktrees\n") == 1`. Fails on 0 (deletion) or 2+ (accidental copy-paste).
   - `test_section_ordering_between_pitfalls_and_bugfix(claude_md_text)` — find the line indices of `## Common Pitfalls`, `## Working in sibling worktrees`, and `## Bug Fix Protocol` (using `claude_md_text.split("\n").index(...)` after stripping). Assert the new section's index is strictly between the other two.
   - `test_section_has_no_bare_database_url_assignment(section_body)` — assert `re.search(r"DATABASE_URL=postgresql://", section_body, re.IGNORECASE) is None`. Catches re-introduction of a bare DB env var (CLAUDE.md Rule #2 regression). The pattern is intentionally `DATABASE_URL=postgresql://` — prose like "the `DATABASE_URL=...` anti-pattern" is allowed because it omits `postgresql://`.
   - `test_section_leakypath_catalog_attribution(section_body)` — locate the catalog table by finding the line that opens with `| Host path |` (the canonical table header — locked in Story 1.1 Task 2 as a Markdown table, not a bulleted list). Parse the rows that follow into a `dict[str, str]` keyed by the first cell's `./<path>/` token, mapping to the row's joined text. **First, assert all four required keys exist in the parsed dict**: `./migrations/`, `./alembic.ini`, `./samples/`, `./data/repo-clones/`. If any key is missing, fail with a specific message naming the missing key — this catches silent deletion of a catalog row. Then, for the rows keyed `./migrations/`, `./alembic.ini`, and `./samples/`, assert the row's text does NOT contain `worker` (case-insensitive). For the row keyed `./data/repo-clones/`, assert the row's text DOES contain `worker`. This targets specific table rows, NOT a section-wide regex sweep (per spec FR-7 implementation note — section prose legitimately mentions `worker` outside the catalog).
   - `test_section_has_exactly_one_fenced_bash_block(section_body)` — count occurrences of the literal `\`\`\`bash` (three backticks + word `bash`) and assert exactly one. Catches accidental copy-paste of competing recipes.

3. **Implement the `section_body` fixture extraction** as follows: find the line containing `## Working in sibling worktrees`. Scan forward; collect lines until the next line matching `^## ` (start of a top-level heading) OR end-of-file. Return the joined body (excluding the header line itself, excluding the next-heading line).

4. **Run the suite locally.**
   ```bash
   .venv/bin/pytest backend/tests/unit/docs/ -v
   ```
   All 5 tests MUST pass against the post-Story-1.1 `CLAUDE.md`.

5. **Verify each test fails on its mutation** (local sanity check; not committed). Temporarily mutate `CLAUDE.md` to each failure mode and confirm the corresponding test fails:
   - Delete the section heading → test #1 fails.
   - Move the section below `## Bug Fix Protocol` → test #2 fails.
   - Add `DATABASE_URL=postgresql://foo` inside the recipe → test #3 fails.
   - Change the `./migrations/` row to include `worker` → test #4 fails.
   - Add a second ` ```bash` block → test #5 fails.
   Revert the mutations after each check. Document the verification in the PR description as evidence of FR-7 mutation coverage.

6. **Commit.** One commit on the feature branch with message `test(worktree-isolation): add 5-test regression suite for sibling-worktree section`.

**Definition of Done (DoD)**

- [ ] `backend/tests/unit/docs/test_claude_md_sections.py` exists with 5 tests + module-level fixtures matching the spec FR-7 signatures.
- [ ] `backend/tests/unit/docs/__init__.py` exists (empty, 0 bytes).
- [ ] `.venv/bin/pytest backend/tests/unit/docs/ -v` reports 5 passed in well under 1 second.
- [ ] Each test fails on its corresponding mutation (verified per Task 5; PR description includes the mutation-test evidence).
- [ ] `make test-unit` (the full unit-test suite) is green — the new test file does not regress existing tests.
- [ ] `make lint` and `make typecheck` are green — the new file follows ruff + mypy conventions (type hints on every function, no missing imports).
- [ ] No bypass of pre-commit hooks; commit message follows Conventional Commits with `test(worktree-isolation):` prefix.

---

### Story 1.3 — Verify deferred-phase tracking artifacts satisfy AC-8

**Outcome:** AC-8 is satisfied: `phase2_idea.md` and `phase3_idea.md` exist in the feature directory, follow [`feature_templates/idea-template.md`](../feature_templates/idea-template.md), each includes an Origin pointer back to this spec, and each restates the relevant deferred decisions (D-1 for both files; D-2 specifically for phase 3). The files were authored during spec-gen Step 10; this story is the explicit verification gate that they meet the AC-8 contract — without it, AC-8 has no story owner and would be silently skipped during impl-execute finalization.

**New files** — None. (Files already exist; verification only.)

**Modified files** — None expected. If verification surfaces gaps (missing Origin pointer, missing D-1/D-2 restatement, template-section drift), the story corrects the gaps in the existing files. The corrections must respect the spec's no-new-content principle: only ensure the files conform to the AC-8 contract; do not expand scope into new deferred-capability content.

**Endpoints** — N/A.

**Key interfaces** — N/A.

**Pydantic schemas** — N/A.

**Tasks**

1. **Read both files.**
   ```bash
   # Inputs to verify
   docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase2_idea.md
   docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase3_idea.md
   ```
2. **Compare against template.** Read [`docs/02_product/planned_features/feature_templates/idea-template.md`](../feature_templates/idea-template.md) (verified to exist; was read during plan-gen Step 1). For each phase file, confirm the following template-mandated sections are present (the template's exact wording may have stable variants; section header presence is what's checked):
   - Front-matter: `**Date:**`, `**Status:**`, `**Priority:**`, `**Origin:**`, `**Depends on:**`
   - Body sections: `## Problem`, `## Proposed capabilities`, `## Scope signals`, `## Why <deferred / not yet prioritized>`, `## Relationship to other work`
3. **Verify the Origin pointer** in each file references `feature_spec.md` at this feature's directory (e.g., `[feature_spec.md](feature_spec.md)` or `feature_spec.md §3` — any link or text reference that points a future reader back to the source spec satisfies AC-8's "Origin pointer to the spec file" requirement).
4. **Verify decision-log inheritance.** AC-8 requires both phase idea files to restate "the deferred decisions (D-1 phase split, D-2 secrets convention)". Both files MUST cite both decisions:
   - `phase2_idea.md` MUST restate **D-1** (Phase 1 = capability A only; capabilities B and C deferred to separate phase ideas) AND **D-2** (per-worktree `DATABASE_URL` overrides MUST use the `*_FILE`-mounted-secret pattern; no bare env vars). D-2 is directly relevant to phase 2 because the proposed `scripts/run-tests-in-worktree.sh` mounts `$MAIN_REPO/secrets/database_url` as a `*_FILE` Docker secret — the same constraint Phase 3 inherits. A passing reference in the phase 2 file (e.g., "matching CLAUDE.md Rule #2 / D-2" beside the secret-mount step) is sufficient.
   - `phase3_idea.md` MUST restate **D-1** AND **D-2**, both citations explicit. D-2 is the central design constraint for phase 3.

   Both citations must be textually identifiable — search for the strings "D-1" and "D-2" (or fully-qualified equivalents like "decision D-1" / "D-2 (secrets convention)") in each file.
5. **If any gap is found in Tasks 2-4, fix the file in-place.** The fix must be minimal: add the missing front-matter field, add the missing section header with the briefest body that satisfies the template, or add the missing D-1/D-2 citation. Do not expand the file's scope.
6. **Commit (if and only if changes were made).** Single commit: `docs(worktree-isolation): align phase2/phase3 idea files with AC-8 contract`. If no changes were needed, skip the commit and proceed.

**Definition of Done (DoD)**

- [ ] `phase2_idea.md` contains the 5 front-matter fields and 5 body section headers required by the idea template (per Task 2).
- [ ] `phase3_idea.md` contains the same 5 front-matter fields and 5 body section headers.
- [ ] Both files contain an Origin pointer (link or named reference) back to this directory's `feature_spec.md`.
- [ ] Both `phase2_idea.md` and `phase3_idea.md` restate BOTH D-1 (phase split) AND D-2 (secrets convention) — verifiable by grepping each file for the strings "D-1" and "D-2".
- [ ] If any commit was made, the message follows Conventional Commits with `docs(worktree-isolation):` prefix.
- [ ] No bypass of pre-commit hooks.

---

## Epic 2 — Phase 2: test-runner automation (added 2026-05-25 via on-PR scope expansion)

### Story 2.1 — Write `scripts/run-tests-in-worktree.sh` + `make test-worktree` target + smoke test

**Outcome:** FR-8, FR-9, FR-10 satisfied. The script mechanizes the FR-4 recipe; the Makefile target is the operator-facing entrypoint; the smoke test asserts argument parsing and command construction without depending on a running Docker daemon (CI hermeticity preserved).

**New files**

| File | Purpose |
|---|---|
| `scripts/run-tests-in-worktree.sh` | Auto-detect main + sibling worktree paths, validate `secrets/database_url`, build the `docker run` argv with the 9 canonical bind mounts + DB-secret mount, support `--dry-run` (print argv only) and `--cmd "<command>"` override flags. Default command: `pytest backend/tests/unit/ -v`. Image: `relyloop/api:${RELYLOOP_GIT_SHA:-dev}`. Network: `${COMPOSE_PROJECT_NAME:-relyloop}_default`. Sub-200 LOC bash. |
| `backend/tests/unit/scripts/test_run_tests_in_worktree.py` | 4 pytest tests covering the dry-run argv shape, missing-secret error path, not-in-worktree error path, and `--cmd` override propagation. All tests invoke the script via `subprocess.run` with `--dry-run` — no real `docker` calls. Pattern reference: `backend/tests/unit/scripts/test_dashboard_truncation.py:14` for the `_REPO_ROOT = Path(__file__).resolve().parents[4]` resolution. |

**Modified files**

| File | Change |
|---|---|
| `Makefile` | Add a `test-worktree` target near the existing `test-unit` / `test-integration` group. The target invokes `bash scripts/run-tests-in-worktree.sh $(if $(CMD),--cmd "$(CMD)")` so `make test-worktree CMD="pytest backend/tests/integration -v"` propagates the override. |

**Endpoints / Pydantic schemas / Key interfaces** — N/A (shell script + Makefile target, not Python module).

**UI element inventory / State dependency analysis / Legacy behavior parity** — N/A (no UI).

**Tasks**

1. **Read context.** Re-read [`docker-compose.yml`](../../../../docker-compose.yml) lines 28, 40, 76, 77, 112, 119, 120, 125, 167 to confirm the canonical bind-mount targets match. Re-read CLAUDE.md `### Running tests against a sibling worktree` recipe block (Story 1.1's output) to confirm the script's argv exactly mirrors the documented recipe. Read [`scripts/install.sh`](../../../../scripts/install.sh) for the existing bash style + the `set -euo pipefail` convention.
2. **Write `scripts/run-tests-in-worktree.sh`.** Use `set -euo pipefail`. Parse `--dry-run` and `--cmd "<command>"` flags via a simple `while [[ $# -gt 0 ]]; do case "$1" in ...` loop. Resolve `WORKTREE_ROOT=$(git rev-parse --show-toplevel)` and exit-fail with a clear stderr message if the command fails. Resolve `MAIN_REPO=$(git worktree list | awk '{print $1; exit}')`. Validate `[ -r "$MAIN_REPO/secrets/database_url" ]` and exit-fail otherwise. Build the `docker run` argv as a bash array. In `--dry-run` mode, `printf '%s\n' "${ARGV[@]}"`; otherwise `exec docker "${ARGV[@]}"`. End with `chmod +x` (committed via `git update-index --chmod=+x` if needed).
3. **Add the `test-worktree` Makefile target.** Read the existing `Makefile` to find the right neighborhood (likely between `test-contract` and `up`). Use `bash scripts/run-tests-in-worktree.sh $(if $(CMD),--cmd "$(CMD)")` so empty `CMD` falls through to the script's default. Add `.PHONY: test-worktree` to the existing `.PHONY` list.
4. **Write the smoke test file.** 4 tests as specified in spec §7 FR-10. Each test uses `subprocess.run([str(_REPO_ROOT / "scripts/run-tests-in-worktree.sh"), "--dry-run", ...], capture_output=True, text=True, env={...})`. Manipulate the environment to simulate the missing-secret + not-in-worktree paths (e.g., `cwd=tmp_path` for the latter; setting a `RELYLOOP_FORCE_MISSING_SECRET=1` env var that the script honors, OR move the secret file with `monkeypatch` in a fixture).
5. **Run the smoke test.** `.venv/bin/pytest backend/tests/unit/scripts/test_run_tests_in_worktree.py -v --tb=short`. All 4 tests pass.
6. **Pre-commit gate.** `make fmt && make lint && make typecheck && .venv/bin/ruff format --check backend/`. All green.
7. **Commit.** `feat(worktree-isolation): scripts/run-tests-in-worktree.sh + make test-worktree target + smoke test`.

**Definition of Done (DoD)**

- [ ] `scripts/run-tests-in-worktree.sh` exists and is executable (`-rwxr-xr-x`).
- [ ] `make test-worktree` runs the script (verified by Story 2.3's operator-path step).
- [ ] `backend/tests/unit/scripts/test_run_tests_in_worktree.py` has 4 tests, all passing.
- [ ] Smoke test runs in <2s and does not require a Docker daemon (verified by inspecting test sources — no `docker` invocation).
- [ ] `make lint` + `make typecheck` + `.venv/bin/ruff format --check backend/` all pass.

---

### Story 2.2 — Runbook + CLAUDE.md shortcut subsection + remove `phase2_idea.md`

**Outcome:** FR-11, FR-12 satisfied. Human operators have a runbook entry point; agents reading CLAUDE.md see the `make test-worktree` shortcut alongside the canonical recipe; the now-shipped capability B is removed from deferred tracking.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/parallel-worktrees.md` | ≤80-line human-facing operating procedure: when to use sibling worktrees, how to create one, how to launch an agent, how to run tests via `make test-worktree`, cross-reference to CLAUDE.md data-path constraints and impl-execute lifecycle steps, cleanup. |

**Modified files**

| File | Change |
|---|---|
| `CLAUDE.md` | (a) Insert a new `### Shortcut: \`make test-worktree\`` subsection immediately before `### Running tests against a sibling worktree (one-shot container recipe)` inside the `## Working in sibling worktrees` section. The subsection is prose only (no new fenced code blocks — FR-7 test #5 stays satisfied). (b) Update the `### Deferred capabilities` subsection: remove the `phase2_idea.md` bullet (capability B shipped); keep the `phase3_idea.md` bullet. (c) Add a `parallel-worktrees.md` row to the `## Key Runbooks` table at the bottom of the file. |

**Deleted files**

| File | Reason |
|---|---|
| `docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase2_idea.md` | Capability B is no longer deferred — it shipped in Story 2.1. Phase 2's design intent is fully captured in the Phase 2 expansion section of `feature_spec.md` (§3) and in the new code itself. Keeping the idea file would create a stale "this is deferred" claim. |

**Tasks**

1. **Write the runbook.** Use the existing runbook style (see `docs/03_runbooks/local-dev.md` if it exists yet, otherwise mirror the docstring shape from `.claude/skills/impl-execute/SKILL.md`). Sections: Overview → When to use a sibling worktree → Create + launch → Run tests via `make test-worktree` → Cross-references → Cleanup. Max 80 lines per FR-11.
2. **Insert the CLAUDE.md shortcut subsection.** One paragraph: explains that `make test-worktree` wraps the recipe below, supports `CMD="<override>"`, and points at `scripts/run-tests-in-worktree.sh` for the implementation. NO new fenced code blocks (preserves FR-7 test #5 invariant).
3. **Update the CLAUDE.md `### Deferred capabilities` subsection.** Delete the `phase2_idea.md` bullet. Keep the `phase3_idea.md` bullet. Optionally tighten the surrounding prose to reflect that one capability has shipped.
4. **Update the CLAUDE.md `## Key Runbooks` table.** Add a new row: `| Parallel-worktree workflow (sibling checkouts, make test-worktree, leak prevention) | [`docs/03_runbooks/parallel-worktrees.md`] (PR #249) |` matching the surrounding table style.
5. **Delete `phase2_idea.md`.** `git rm docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase2_idea.md`.
6. **Verify the FR-7 regression suite still passes.** `.venv/bin/pytest backend/tests/unit/docs/ -v` — all 5 tests green.
7. **Pre-commit gate.** `make lint && make typecheck` (Python untouched, but verify nothing regresses).
8. **Commit.** `docs(worktree-isolation): runbook + CLAUDE.md shortcut + remove shipped phase2_idea`.

**Definition of Done (DoD)**

- [ ] `docs/03_runbooks/parallel-worktrees.md` exists, ≤80 lines, follows the project runbook style.
- [ ] CLAUDE.md `## Working in sibling worktrees` section gained a `### Shortcut: \`make test-worktree\`` subsection in the correct position; the `### Deferred capabilities` subsection lost the phase2 bullet; the section still passes all 5 regression tests in `backend/tests/unit/docs/`.
- [ ] CLAUDE.md `## Key Runbooks` table has a new row for the parallel-worktrees runbook.
- [ ] `docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/phase2_idea.md` is deleted.
- [ ] No bypass of pre-commit hooks.

---

### Story 2.3 — Operator-path verification: run `make test-worktree` end-to-end

**Outcome:** AC-11 satisfied. The CLAUDE.md Step 3 mandatory operator-path verification for new Makefile targets runs end-to-end against the live Compose stack: `make test-worktree` spins up a one-shot container, runs the in-container `pytest` command, and exits 0. The operator's main-worktree paths are NOT modified (no leak).

**New files** — None.

**Modified files** — None.

**Tasks**

1. **Verify the Compose stack is healthy.** `docker compose ps` shows all services `Up <duration> (healthy)`. If not, `make up`.
2. **Verify `secrets/database_url` exists in the main repo.** `ls -la secrets/database_url`.
3. **Snapshot leaky-path state before the run.** `git status` baseline + `ls migrations/ samples/ alembic.ini data/postgres/ data/redis/ data/repo-clones/` checksums (or just `git status` — any new untracked files post-run would be a leak).
4. **Run `make test-worktree`.** Default invocation; this hits the script's default command `pytest backend/tests/unit/ -v`. Capture exit code + a sample of the output.
5. **Run `make test-worktree CMD="pytest backend/tests/unit/docs/ -v"`.** Override-command verification — should exit 0 and the script's progress line should show the override command.
6. **Verify no leak.** `git status` post-run should show the SAME state as before — no new untracked files in `./migrations/`, `./samples/`, `./alembic.ini`, `./data/*/`. If anything appears, it's a leak — the script has a bind-mount bug.
7. **Document the verification in the PR description.** Add the captured exit codes + the leak-check result.

**Definition of Done (DoD)**

- [ ] `make test-worktree` exits 0 against the live stack.
- [ ] `make test-worktree CMD=...` exits 0 with the override command visible in the script's progress output.
- [ ] `git status` is unchanged post-run (no leak into the operator's main worktree).
- [ ] Evidence captured in the PR description's "Test plan" section.

---

## UI Guidance

**No frontend scope.** This feature does not add, move, or remove any UI element. The "audience" of the new CLAUDE.md section is autonomous agents (and humans browsing the repo root in their editor); CLAUDE.md is markdown, not a rendered UI. The plan-level UI Guidance subsections (insertion point markup, analogous markup patterns, visual consistency, interaction behavior, handler functions, navigation placement, tooltips, legacy behavior parity, client-side persistence) are intentionally omitted with explicit acknowledgment that this is correct for a docs-only PR.

**Legacy behavior parity** — no user-facing component >100 LOC is being deleted or migrated in this plan. Section omitted per template guidance.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/docs/`
- Scope: assertions over `CLAUDE.md` content shape (section presence, ordering, content-token invariants)
- Tasks:
  - [ ] Write `test_working_in_sibling_worktrees_section_exists`
  - [ ] Write `test_section_ordering_between_pitfalls_and_bugfix`
  - [ ] Write `test_section_has_no_bare_database_url_assignment`
  - [ ] Write `test_section_leakypath_catalog_attribution`
  - [ ] Write `test_section_has_exactly_one_fenced_bash_block`
- DoD:
  - [ ] All 5 tests pass against the post-Story-1.1 CLAUDE.md.
  - [ ] Each test fails on its specific mutation (verified per Story 1.2 Task 5).

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: N/A — no DB, no service workflow, no migration in this feature.
- Tasks: none.
- DoD: N/A.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: N/A — no API endpoints in this feature.
- Tasks: none.
- DoD: N/A.

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: N/A — no UI surface in this feature.
- Tasks: none.
- DoD: N/A.

### 3.5 Existing test impact audit

No existing test references `CLAUDE.md` content by structural pattern. Verified by:

```bash
grep -rln "Working in sibling worktrees\|Common Pitfalls\|Bug Fix Protocol" backend/tests/ ui/ 2>/dev/null
```

(Returns nothing — no test files reference these section headers. `backend/tests/unit/test_probes.py:210` and `backend/tests/unit/workers/test_poll_cron_kwargs.py:35` reference "CLAUDE.md Rule #N" by number in comments only, not as test assertions; they will not be affected by adding a new section.)

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/test_probes.py:210` | `# CLAUDE.md Rule #11` comment | 1 | No change needed — comment refers to Rule #11 in the existing Absolute Rules list, which is unaffected. |
| `backend/tests/unit/workers/test_poll_cron_kwargs.py:35` | `# CLAUDE.md Rule #2` comment | 1 | No change needed — comment refers to Rule #2 in the existing Absolute Rules list. |
| `backend/tests/unit/scripts/test_dashboard_truncation.py:6` | `# CLAUDE.md "Tangential discoveries"` comment | 1 | No change needed — comment refers to an existing section that is preserved. |

### 3.5 Migration verification

N/A — no schema change.

### 3.6 CI gates

- [ ] `make test-unit` passes (includes the new `backend/tests/unit/docs/` directory automatically — pytest discovers it via standard collection).
- [ ] `make lint` passes on the new test file.
- [ ] `make typecheck` passes on the new test file (mypy --strict — every function has type hints; imports resolve).
- [ ] `make test-integration` — runs (no DB integration in this feature) but exists as the standard backend CI step; should remain green.
- [ ] `make test-contract` — runs (no contract tests added) but should remain green.
- [ ] `cd ui && pnpm test` — N/A; not run by the backend pipeline. The repo's PR workflow runs both; both should remain green since no frontend changes are made.

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update on impl-execute finalization (Step 8.6), not per-story. One-line "recent changes" entry: `2026-05-XX (PR #N) — infra_agent_sibling_worktree_isolation Phase 1 shipped: new CLAUDE.md section + 5-test regression suite. Phase 2 + 3 deferred to phase*_idea.md.`

**`architecture.md`** — no update needed. This feature adds operational guidance, not an architectural change.

**`CLAUDE.md`** — this IS the feature's product. Story 1.1 IS the CLAUDE.md update.

### 4.1 Architecture docs (`docs/01_architecture`)

No updates. The bind-mount facts are implicit in `docker-compose.yml`; the new section makes them visible to agents without adding architectural surface.

### 4.2 Product docs (`docs/02_product`)

- [x] `phase2_idea.md` exists in the feature directory (created during spec-gen Step 10).
- [x] `phase3_idea.md` exists in the feature directory (created during spec-gen Step 10).
- [x] `pipeline_status.md` exists in the feature directory (created during spec-gen Step 12; impl-execute finalization will update the Plan + Implementation sections).
- [ ] On finalization (impl-execute Step 8.6), move the feature folder from `docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/` to `docs/00_overview/implemented_features/<YYYY_MM_DD>_infra_agent_sibling_worktree_isolation/` — BUT only when ALL phases ship. Per the [`/pipeline` orchestrator's PARTIAL-state rule](../../../../.claude/skills/pipeline/SKILL.md), a folder with surviving `phase*_idea.md` files stays in `planned_features/` until every deferred phase completes. Since Phase 2 and Phase 3 are deferred (and `phase*_idea.md` files exist), the folder stays in `planned_features/` after this PR; only the Plan + Implementation sections of `pipeline_status.md` get updated. The folder graduates to `implemented_features/` only after Phase 3 ships (likely never if the friction never recurs).

### 4.3 Runbooks (`docs/03_runbooks`)

No new runbook. The new CLAUDE.md section is itself agent-facing operating guidance, not an ops procedure for humans on call.

### 4.4 Security docs (`docs/04_security`)

No update. The §10 threat scenarios in the spec are bounded to the new section's anti-patterns; no new secret, no new threat model entry.

### 4.5 Quality docs (`docs/05_quality`)

No update. Coverage gate unchanged (80%); test layer convention unchanged.

**Documentation DoD**

- [ ] `pipeline_status.md` Plan + Implementation sections updated on impl-execute finalization.
- [ ] `state.md` "recent changes" gets one new line on impl-execute finalization.
- [ ] Feature folder stays in `planned_features/` (not moved to `implemented_features/`) because Phase 2 + Phase 3 `phase*_idea.md` files remain — the orchestrator's PARTIAL-state rule applies.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None. This feature is purely additive — adds one section + one test file. No existing code is restructured, deduplicated, or moved.

### 5.2 Planned refactor tasks

(None.)

### 5.3 Refactor guardrails

(N/A.)

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `docker-compose.yml` bind-mount lines stable at 28 / 40 / 76 / 77 / 112 / 119 / 120 / 125 / 167 | Story 1.1 catalog citations | Verified 2026-05-25 by direct read | Stale line citations in the new section. Mitigation: the catalog's inline reminder ("If you edit `docker-compose.yml`, re-verify the line citations above in the same PR") sets the discipline; PR review enforces it. |
| `impl-execute` SKILL.md Step 0a / 6b / 9.3 stable as cited | Story 1.1 cross-reference | Verified 2026-05-25 (lines 468, 278, 937) | Stale cross-reference in the new section. Mitigation: PR review of any future `impl-execute` SKILL.md edit must check that the step numbers cited from CLAUDE.md still resolve. |
| `phase2_idea.md` and `phase3_idea.md` exist at the cited paths | Story 1.1 forward-pointer | Created during spec-gen Step 10 (2026-05-25) | Broken markdown link in the new section. Mitigation: Task 4 of Story 1.1 spot-checks every link resolves via the `Read` tool. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Line numbers in the catalog drift on a future `docker-compose.yml` edit and aren't refreshed | M | L | Inline reminder in the section; PR review of any Compose edit. The unit tests do NOT enforce this (OQ-2 deferred). |
| The new section is removed in a future doc reorg without anyone noticing | L | M | Story 1.2 test #1 fails; CI blocks the reorg PR until the section is restored. |
| A future doc edit accidentally re-introduces a bare `DATABASE_URL=postgresql://` in the shell example | L | H (if shipped) | Story 1.2 test #3 fails; CI blocks the PR. |
| Story 1.2 test #4's catalog-row parser breaks on a legitimate table-format change | L | M | Story 1.1 Task 2 locks the catalog as a Markdown table (not a bulleted list); the test parser targets that fixed format. If a future PR converts the catalog to a different shape, that PR must also update the test parser in the same commit — caught at PR review (the test would fail in CI before merge regardless). |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Agent in sibling worktree writes via `docker cp` to `/app/migrations/` in `api`/`migrate` container | Agent ignores or hasn't loaded the new section | Bytes silently land in main worktree's `./migrations/`; agent sees success | Operator notices the untracked file at PR time; `git restore` from main worktree, then agent re-does the write via the one-shot container recipe (FR-4). This is exactly the PR #216 incident the feature documents — the new section is the long-term prevention, not the recovery path. |
| Agent in sibling worktree writes via `docker exec api sh -c '... > /app/samples/x'` (read-only mount) | Agent ignores the section's read-only-mount note | Write fails immediately with `EROFS` / "Read-only file system" | Agent reads the error, consults the new section, uses the one-shot container recipe instead. Loud failure → fast recovery. |
| Two concurrent sibling worktrees generate migrations with colliding rev_ids against shared Postgres | A second parallel-feature flow surfaces the friction | Alembic fails with "duplicate rev_id" at CI time | Document in `phase3_idea.md` "Why deferred" — recovery today is "rebase the second branch and regenerate the migration"; long-term recovery is Phase 3's per-worktree DB override. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — write the CLAUDE.md section. Commit.
2. **Story 1.2** — write the 5-test regression suite. Commit.
3. **Story 1.3** — verify `phase2_idea.md` / `phase3_idea.md` satisfy AC-8 (and patch if any gap is found). Commit only if changes were made.

### Parallelization opportunities

- Story 1.2 **completion** depends on Story 1.1 completion (the tests must pass against the section, so they cannot be marked done until the section exists). Story 1.2 **authoring** could begin earlier as a TDD-style failing suite — the test code can be written from the spec FR-7 contract alone — but for a 3-story plan executed sequentially by a single agent the time savings are negligible.
- Story 1.3 is fully independent of Story 1.1 and Story 1.2 (it audits files that already exist). It could be executed first, last, or in parallel with either of the other stories without altering correctness. The "last" sequencing chosen above is a convention (verification last) rather than a hard dependency.

---

## 8) Rollout and cutover plan

- **Rollout stages:** single-PR merge to `main`. No staged rollout — docs-only.
- **Feature flag strategy:** N/A.
- **Migration/cutover steps:** N/A.
- **Reconciliation/repair strategy:** N/A (no state to repair).
- **Auto-inheritance to sibling worktrees:** per spec §16, Claude Code reads `<pwd>/CLAUDE.md` on session start. Every sibling worktree branched off `main` after this PR merges inherits the section. Edge case: long-lived feature branches that haven't rebased on `main` won't see the section until they rebase — covered by the existing `impl-execute` Step 0a worktree pre-flight discipline.
- **In-flight agent caveat:** agents already running with cached system context at merge time will not see the new section until restart. Operator-managed; no automated mitigation in this PR.

---

## 9) Execution tracker

### Current sprint

- [x] Story 1.1 — Add `## Working in sibling worktrees` section to CLAUDE.md (commit `2c79bc32`)
- [x] Story 1.2 — Add 5-test regression suite at `backend/tests/unit/docs/test_claude_md_sections.py` (commit `dc630ae4`)
- [x] Story 1.3 — Verify deferred-phase tracking artifacts satisfy AC-8 (verified in session; no in-place edits needed)
- [x] Story 2.1 — Write `scripts/run-tests-in-worktree.sh` + `make test-worktree` + smoke test (commit `b964ef20`)
- [x] Story 2.2 — Runbook + CLAUDE.md shortcut subsection + remove shipped `phase2_idea.md` (commit `b964ef20`)
- [x] Story 2.3 — Operator-path verification: `make test-worktree CMD="pytest backend/tests/unit/docs/ -v"` exited 0 against the live stack; zero leak; both default and CMD-override paths verified
- [x] Final Gemini adjudication (commit `e2dcf333`) + final GPT-5.5 cycle 3 converged (commits `bdb35e59`, `a0131ab2`)

### Blocked items

(None.)

### Done this sprint

(None yet — plan is Draft as of write time.)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking each story complete, attach evidence for:

**Story 1.1:**

- [ ] `grep -c "^## Working in sibling worktrees$" CLAUDE.md` returns `1`.
- [ ] `grep -n "^## " CLAUDE.md` shows the section between `## Common Pitfalls` and `## Bug Fix Protocol`.
- [ ] No bare `DATABASE_URL=postgresql://` in the section (`grep -n "DATABASE_URL=postgresql" CLAUDE.md` returns nothing in the new section).
- [ ] Exactly one ` ```bash` fence in the section body.
- [ ] Catalog table contains all 6 paths with writability column.
- [ ] Pre-commit hooks all pass; commit message is `docs(worktree-isolation): ...`.

**Story 1.2:**

- [ ] `backend/tests/unit/docs/__init__.py` exists and is empty.
- [ ] `backend/tests/unit/docs/test_claude_md_sections.py` exists with 5 tests.
- [ ] `.venv/bin/pytest backend/tests/unit/docs/ -v` reports 5 passed.
- [ ] Mutation evidence in PR description: each of the 5 tests fails on its targeted mutation (verified per Story 1.2 Task 5).
- [ ] `make test-unit` is green.
- [ ] `make lint` and `make typecheck` are green.
- [ ] Pre-commit hooks all pass; commit message is `test(worktree-isolation): ...`.

**Story 1.3:**

- [ ] Both `phase2_idea.md` and `phase3_idea.md` exist at the cited paths and contain the 5 template front-matter fields + 5 template body section headers.
- [ ] Each file's Origin pointer resolves back to this directory's `feature_spec.md`.
- [ ] Both `phase2_idea.md` and `phase3_idea.md` cite both D-1 (phase split — capability A only; B and C deferred) and D-2 (per-worktree `DATABASE_URL` overrides MUST use `*_FILE`-mounted-secret pattern). Verify by grepping each file for the strings "D-1" and "D-2".
- [ ] If any in-place edit was needed to satisfy AC-8, the commit follows Conventional Commits with `docs(worktree-isolation):` prefix.

---

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count**: spec §8.1 endpoint table is `N/A` (docs-only feature). Plan has no endpoint tables. ✓ Matches.

2. **Spec ↔ plan error code coverage**: spec §8.5 error code catalog is `N/A` (no API endpoints). Plan has no error codes. ✓ Matches.

3. **Spec ↔ plan FR coverage**: All 7 FRs + AC-8 traced in §1 above. FR-1 through FR-6 → Story 1.1; FR-7 → Story 1.2; AC-8 → Story 1.3. ✓ Complete.

4. **Story internal consistency**:
   - Story 1.1 modifies one file (`CLAUDE.md`); Story 1.2 creates two files (`backend/tests/unit/docs/__init__.py`, `backend/tests/unit/docs/test_claude_md_sections.py`); Story 1.3 modifies zero or two files (`phase2_idea.md`, `phase3_idea.md` — only if AC-8 gaps surface). No ownership conflicts: Story 1.3's potential modifications target files that already exist and that no other story touches.
   - All three stories' DoD reference the FRs and ACs they trace to (Story 1.1 → FR-1/2/3/4/5/6 + AC-1/2/3/4/5/6; Story 1.2 → FR-7 + AC-7; Story 1.3 → AC-8).
   - Modified file `CLAUDE.md` exists (verified by reading it at session start).
   - New file paths `backend/tests/unit/docs/__init__.py` and `backend/tests/unit/docs/test_claude_md_sections.py` follow the existing `backend/tests/unit/scripts/` convention (verified by `ls backend/tests/unit/scripts/`).
   - Story 1.3's potentially-modified files (`phase2_idea.md`, `phase3_idea.md`) exist (verified — both were created during spec-gen Step 10 in this session).

5. **Test file count and assignment**: One new test file, assigned to Story 1.2's DoD. ✓ No orphans.

6. **Gate arithmetic**: No epic/phase gates with numeric assertions (this is a 3-story epic; the "gate" is implicit — all three stories DoD-complete = epic done). ✓ Consistent.

7. **Open questions resolved**: Spec §19 lists no open questions remaining at spec-finalization time (all three OQs locked via recommended-defaults under Auto Mode during spec-gen). ✓ Plan has nothing to inherit.

8. **Frontend UI Guidance completeness**: No frontend scope → UI Guidance section explicitly states "No frontend scope" with rationale. ✓ Correct omission per template guidance.

9. **Plan ↔ codebase verification**: Verified during plan generation (see verification ledger in §11.13 below).

10. **Infrastructure path verification**: No migration directory, no router registration, no Alembic revision — feature is docs-only. ✓ N/A.

11. **Frontend data plumbing verification**: N/A (no frontend).

12. **Persistence scope consistency**: N/A (no client-side storage).

13. **Enumerated value contract audit**: N/A (no filters, badges, sort keys, dropdowns).

14. **Admin control / ceiling enforcement audit (MVP4+)**: N/A — RelyLoop is MVP1, no admin model.

15. **Audit-event coverage audit (MVP2+)**: N/A — RelyLoop is MVP1, no `audit_log` table.

### Verification ledger

| Claim | Verified by | Status |
|---|---|---|
| `CLAUDE.md` exists at repo root | `Read` tool on `/Users/ericstarr/relyloop/CLAUDE.md` succeeded at session start | Verified |
| `## Common Pitfalls` at line 352, `## Bug Fix Protocol` at line 368 | `grep -n "^## " CLAUDE.md` during spec-gen | Verified |
| Bind-mount lines 28 / 40 / 76 / 77 / 112 / 119 / 120 / 125 / 167 in `docker-compose.yml` | Direct read during spec-gen | Verified |
| `impl-execute` SKILL.md Step 0a at line 468, Step 6b at line 278, Step 9.3 at line 937 | `grep -n "Worktree pre-flight\|Parallel test agents\|Agent worktree sweep" .claude/skills/impl-execute/SKILL.md` during spec-gen | Verified |
| `backend/tests/unit/scripts/test_dashboard_truncation.py:14` uses `Path(__file__).resolve().parents[4]` for repo root | Read during plan-gen Step 2 | Verified |
| `backend/tests/unit/scripts/__init__.py` is empty (0 bytes) — pattern for the new `docs/__init__.py` | `ls backend/tests/unit/scripts/` showed `__init__.py  0B` during plan-gen Step 2 | Verified |
| Coverage gate is 80%, configured at `pyproject.toml:225` | `grep -n "fail_under" pyproject.toml` during plan-gen Step 2 | Verified |
| Conventional Commits hook accepts `docs(worktree-isolation):` and `test(worktree-isolation):` | `worktree-isolation` is lowercase + hyphens; matches the regex `^(feat|fix|chore|docs|infra|refactor|test|style|perf|build|ci)(\([a-z0-9-]+\))?(!)?:` | Verified (also empirically confirmed by the spec-stage commit that landed earlier in this session) |
| `phase2_idea.md` and `phase3_idea.md` exist at `docs/02_product/planned_features/infra_agent_sibling_worktree_isolation/` | Created during spec-gen Step 10 (this session) | Verified |
| `pipeline_status.md` exists at the same path | Created during spec-gen Step 12 (this session) | Verified |
| Pre-commit hook `Regenerate MVP1 dashboard` triggers on `planned_features/` folder changes | Observed during spec-gen commit | Verified |

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR is mapped to stories/tasks/tests/docs updates (see §1).
- [x] Every story includes New files, Modified files, Endpoints, Key interfaces, Tasks, and DoD (N/A sections explicitly omitted with rationale).
- [x] Test layers are explicitly scoped — unit only; integration / contract / E2E explicitly marked N/A with rationale.
- [x] Documentation updates across docs/01-05 are planned and owned (most are "no update needed"; `pipeline_status.md` + `state.md` updates happen on impl-execute finalization).
- [x] Lean refactor scope: explicitly "None — feature is purely additive."
- [x] Epic/phase gates: implicit (3-story epic; the "gate" is "all three stories DoD-complete").
- [x] Story-by-Story Verification Gate is included (§10).
- [x] Plan consistency review (§11) has been performed with no unresolved findings.
- [ ] **Cross-model review (GPT-5.5)** — to be run before this plan is moved from Draft to Ready for Execution.

### Cross-model review adjudication log

- **2026-05-25 — Cycle 1 (10 findings):** 1 High-severity contract violation (link shape `[:NN]` vs spec-required `[docker-compose.yml:NN]`), 4 Medium structural/correctness findings (opening paragraph missing `docker-compose.yml` link; AC-8 untracked; FR-2 read-only failure-mode text understated; test #4 needed row-presence assertion), 5 Low findings (table-format lock-in; `__init__.py` justification; irrelevant dashboard-regen risk; ruff/mypy wording; sequencing language). 9 fully accepted; 1 partially reframed (`__init__.py` kept with justification because the existing `backend/tests/unit/scripts/__init__.py` is the canonical 0-byte precedent — adding `docs/` without one would deviate from convention). Major contract changes: link shape corrected; AC-8 promoted to a new Story 1.3; FR-2 read-only failure-mode wording expanded; test #4 row-presence assertion added; catalog locked as Markdown table format (drops the spec's table-or-list flexibility at plan level).
- **2026-05-25 — Cycle 2 (2 findings):** 1 Blocking (Story 1.3 required only phase3_idea.md to restate D-2, but spec AC-8 says both files restate both decisions; Pass A+B), 1 Polish (stale "2-story epic" wording in §12 Definition of plan done). Both fully accepted. Resolution: broadened Story 1.3's Task 4 + DoD + §10 verification gate to require both files cite both D-1 and D-2; updated §12 to say 3-story epic. Note: both phase idea files written during spec-gen Step 10 already satisfy the broadened contract — phase2_idea.md cites D-2 via "matching CLAUDE.md Rule #2 / D-2" in its Phase-2 script secret-mount step; phase3_idea.md cites both decisions explicitly. So Story 1.3 will verify-only with no expected in-place edits.
