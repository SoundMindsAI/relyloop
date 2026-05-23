# Implementation Plan — `test_migrations.py` dynamic head lookup

**Date:** 2026-05-23
**Status:** Complete (PR #219 squash-merged as `63cb7c41` on 2026-05-23)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) Absolute Rule #5 (migrations include `downgrade()` and round-trip cleanly); [`docs/05_quality/testing.md`](../../../05_quality/testing.md) (integration test layer).

---

## 0) Planning principles

- **Spec traceability first** — every story maps to one or more FR IDs from `feature_spec.md`.
- **Single phase, single PR** — the chore is ~15 LOC; further sub-phasing would be ceremony noise.
- **No new test infrastructure** — the helper is exercised by the two existing integration tests; the spec explicitly rejects adding a mocked unit test (see spec §14 + §19 decision log 2026-05-23).
- **Fail-loud** — the helper raises on the multi-head edge case rather than silently picking the first head (per spec FR-1 + AC-1b).
- **Preserve the skip gate** — the existing `pytestmark = pytest.mark.skipif(not _postgres_reachable(), ...)` continues to gate the module without modification (spec FR-3).

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Notes |
|---|---|---|
| FR-1 (dynamic head helper, with single-head assertion) | Epic 1 / Story 1.1 | New private `_current_head()` helper in `backend/tests/integration/test_migrations.py`. |
| FR-2 (replace hardcoded assertions + collapse comment chain) | Epic 1 / Story 1.2 | Two assertion call-sites + the per-migration changelog comments above them. |
| FR-3 (no regression in skip behavior) | Epic 1 / Story 1.1 | Helper is called inside test bodies only, downstream of the module-level `pytestmark`. No changes to skip logic. |

No deferred phases — the spec defines a single phase (spec §3 "Phase boundaries: single phase, single PR").

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** One epic, two stories.

### Story-level detail requirements

Stories are test-only (no API surface, no migrations, no UI). Per the template: stories that are purely test-only "may omit Endpoints/Schemas sections but must still include New/Modified files and Tasks/DoD." Following that rule.

### Conventions (applies to every story)

- All Python additions follow the project's typing conventions (`from __future__ import annotations` already at the top of the target file; explicit return types; `mypy --strict` clean).
- No subprocess-by-string — every external command is invoked via a fixed `list[str]` argv (matches the existing `_alembic()` helper at [`test_migrations.py:79-87`](../../../../backend/tests/integration/test_migrations.py#L79)).
- No defensive try/except around `subprocess.check_output` — failure means the toolchain is broken and should propagate loudly (spec FR-1).
- The helper is private (`_current_head`, leading underscore) — no need to extend any module-level `__all__` (the file has none).

### AI Agent Execution Protocol (applies to every story)

Per template Step 0–9, plus the chore's narrower scope (no backend services, no frontend, no migrations):

0. Read [`architecture.md`](../../../../architecture.md) (skim only — the chore touches no service the architecture doc describes) and [`state.md`](../../../../state.md) (confirm Alembic head, recent migrations, active branch).
1. Read story scope, FRs, ACs from the spec.
2. **Backend-only:** modify `backend/tests/integration/test_migrations.py`. No models, no migrations, no routers, no schemas.
3. Run `make test-unit` (must remain green — chore must not regress unrelated tests).
4. Skip frontend (no UI scope).
5. Skip E2E (no UI scope).
6. Update no docs in MVP1 release notes — the spec §15 says docs/01-05 require no updates. State.md gets a single-line entry at finalization (per template §4.0).
7. Skip migration round-trip (no schema change). The chore's WHOLE POINT is to make this verification not require a sympathy edit in test_migrations.py.
8. PR description must attach: `make lint`, `make typecheck`, `make test-unit`, `make test-integration` evidence, plus a one-line note for AC-4 manual verification (stub migration shipped + ran tests + removed stub + ran tests again).
9. At finalization (separate PR after merge): update `state.md` recent-changes section + move folder to `implemented_features/2026_05_23_chore_migration_test_head_brittleness/`.

---

## Epic 1 — Dynamic head resolution in `test_migrations.py`

### Story 1.1 — Add `_current_head()` helper with single-head invariant

**Outcome:** A private helper in `backend/tests/integration/test_migrations.py` returns the current Alembic head revision id by invoking `uv run alembic heads`, and raises `AssertionError` if the project enters a multi-head state. The helper is callable only at test-body execution time (not at module import).

**FR coverage:** FR-1, FR-3. AC coverage (verified by Story 1.2 + manual inspection): AC-1, AC-1b, AC-5, AC-6.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`backend/tests/integration/test_migrations.py`](../../../../backend/tests/integration/test_migrations.py) | Add `_current_head() -> str` private helper between the existing `_sync_database_url()` helper (line ~93) and the `fresh_db` fixture (line ~95). Helper invokes `uv run alembic heads` via the existing subprocess pattern, asserts exactly one non-empty output line, and returns the first whitespace-separated token of that line. |

**Endpoints**

N/A — test file only.

**Key interfaces**

```python
# backend/tests/integration/test_migrations.py

def _current_head() -> str:
    """Resolve the current Alembic head revision id at test-body execution time.

    Invokes ``uv run alembic heads`` from the repo root and parses the first
    whitespace-separated token of the single output line as the head id.
    Asserts the chain has exactly one head — if a future branch lands and
    Alembic emits multiple head lines, silently picking the first would mask
    a real schema-design issue. Raise ``AssertionError`` instead.

    Must be called inside test bodies, NOT at module import. The module-level
    ``pytestmark = pytest.mark.skipif(not _postgres_reachable(), ...)`` only
    runs at collection time; an import-time invocation would bypass it.
    """
    result = _alembic("heads").stdout
    lines = [line for line in result.splitlines() if line.strip()]
    assert len(lines) == 1, (
        f"Expected exactly one Alembic head, got {len(lines)}: {lines!r}. "
        "Run `alembic merge` to consolidate."
    )
    return lines[0].split()[0]
```

**Pydantic schemas**

N/A.

**Tasks**

1. Read the current state of `backend/tests/integration/test_migrations.py` to locate the helper insertion point (after `_sync_database_url()` at ~L93, before the `fresh_db` fixture at ~L95). Confirm `subprocess` is already imported (it is, line 33).
2. Add the `_current_head()` helper exactly as shown in **Key interfaces**. Match the existing module's docstring style (one-line summary + blank line + multi-paragraph body).
3. Do NOT modify the `pytestmark` skip gate (spec FR-3).
4. Run `make lint` (ruff) — green.
5. Run `make typecheck` (mypy --strict) — green; the helper is typed `() -> str`.
6. Run `make test-unit` — green. The helper isn't unit-tested directly (spec §14 decision); the suite must not regress unrelated tests.

**Definition of Done (DoD)**

- [ ] `_current_head()` exists in `backend/tests/integration/test_migrations.py` between `_sync_database_url()` and the `fresh_db` fixture.
- [ ] Helper signature is `_current_head() -> str` (typed, no kwargs).
- [ ] Helper raises `AssertionError` with an `alembic merge`-naming message if `subprocess.check_output` returns more than one non-empty line. **Verified by inspection at code review** (AC-1b is an inspection-level AC per spec §18 — the project does not currently have multi-head migrations to exercise it in CI).
- [ ] Helper does NOT appear in any top-level assignment, default-argument expression, decorator argument, or other code path that runs at module-collection time. **Verified by `grep` for the helper name outside test-body function definitions** (AC-6, anti-regression).
- [ ] No changes to `pytestmark`, `_postgres_reachable()`, or `_alembic()` (FR-3 scope hygiene).
- [ ] `make lint` / `make typecheck` / `make test-unit` green locally.

### Story 1.2 — Replace hardcoded assertions and collapse the changelog comment chain

**Outcome:** Both `assert row[0] == "0017"` sites in `backend/tests/integration/test_migrations.py` resolve the head dynamically via `_current_head()`. The growing per-migration changelog comment chain above each assertion is replaced with a single anchor comment pointing at the helper's docstring. Adding a new migration requires zero edits in this file.

**FR coverage:** FR-2. AC coverage: AC-2, AC-3, AC-4.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`backend/tests/integration/test_migrations.py`](../../../../backend/tests/integration/test_migrations.py) | At ~L132 (inside `test_upgrade_head_creates_alembic_version`): replace `assert row[0] == "0017"` with `assert row[0] == _current_head()`. Replace the preceding ~10-line per-migration changelog comment (currently spanning lines ~123–131) with a single anchor comment of the form `# Head is resolved dynamically via _current_head() — see helper docstring.`. At ~L157 (inside `test_round_trip`): same assertion replacement; same comment collapse for the ~3-line preceding comment block (lines ~155–156). |

**Endpoints**

N/A.

**Key interfaces**

None — Story 1.2 only consumes the helper introduced in Story 1.1.

**Pydantic schemas**

N/A.

**Tasks**

1. Re-read [`backend/tests/integration/test_migrations.py`](../../../../backend/tests/integration/test_migrations.py) to confirm the exact line numbers and surrounding comment text after Story 1.1's helper insertion (line numbers may shift by a few lines depending on the helper's exact placement and docstring length).
2. In `test_upgrade_head_creates_alembic_version`: replace the multi-line `# Baseline is "0001" per migrations/versions/0001_baseline.py. ...` comment block with the single anchor line `# Head is resolved dynamically via _current_head() — see helper docstring.`. Then change `assert row[0] == "0017"` to `assert row[0] == _current_head()`.
3. In `test_round_trip`: replace the multi-line `# Head: 0017 (chore_reconciler_terminal_closed_no_poll adds proposals.last_polled_at).` comment block with the same single anchor line. Then change `assert row[0] == "0017"` to `assert row[0] == _current_head()`.
4. Run `make lint` — green.
5. Run `make typecheck` — green.
6. Run `make test-unit` — green.
7. Run `make test-integration` against the local Compose Postgres (or the CI service container). Both `test_upgrade_head_creates_alembic_version` and `test_round_trip` MUST pass with `_current_head()` resolving to `"0017"`.
8. **AC-4 manual verification (mandatory, document in PR description):**
   - Create a stub migration at `migrations/versions/0018_chore_sympathy_edit_check.py` with a minimal shape: `revision = "0018"`, `down_revision = "0017"`, `def upgrade(): op.execute("SELECT 1")`, `def downgrade(): pass`.
   - Run `make test-integration` — both `test_upgrade_head_creates_alembic_version` and `test_round_trip` MUST pass without ANY edit to `test_migrations.py`.
   - Delete `migrations/versions/0018_chore_sympathy_edit_check.py`.
   - Run `make test-integration` again — both tests MUST pass against the original `"0017"` head.
   - Paste the four-step shell transcript into the PR description.
9. `grep -rn '"0017"' backend/tests/` — confirm no remaining matches in `backend/tests/integration/test_migrations.py` (the `migrations/versions/0017_proposals_last_polled_at.py` match is expected and intentionally not touched, per spec §3 Out of scope).

**Definition of Done (DoD)**

- [ ] Both `assert row[0] == "0017"` instances at `test_migrations.py:132` and `:157` are replaced with `assert row[0] == _current_head()`. **Verified by `grep -c 'assert row\[0\] == _current_head()' backend/tests/integration/test_migrations.py` returning exactly `2` (the two call sites), and `grep -c '^def _current_head() -> str:' backend/tests/integration/test_migrations.py` returning exactly `1` (the helper definition).** Total `_current_head()` token count via raw `grep -c "_current_head()"` will be higher (~5) because the two anchor comments also contain the token — that's expected, not a regression.
- [ ] No remaining hardcoded `"0017"` literal in `backend/tests/integration/test_migrations.py`. **Verified by `grep -n '"0017"' backend/tests/integration/test_migrations.py` returning no output.** The match in `migrations/versions/0017_proposals_last_polled_at.py` is out of scope (Alembic's own `revision: str = ...` declaration).
- [ ] Per-migration changelog comment chains collapsed to a single anchor comment at each call site (the detailed changelog continues to live in `migrations/versions/*.py` docstrings + `docs/00_overview/implemented_features/`).
- [ ] `make test-integration` passes against the current chain (head `0017`). **AC-2 + AC-3 exercised.**
- [ ] AC-4 manual stub-migration verification documented in the PR description with the four-step shell transcript (create stub → tests pass → delete stub → tests pass). **AC-4 exercised.**
- [ ] No changes to `pytestmark`, `_postgres_reachable()`, `_alembic()`, the `fresh_db` fixture, or any test in `TestOptunaSchema`.

---

## UI Guidance (required for frontend-facing work)

**N/A — this chore has no frontend scope.** No user-facing components are added, moved, or deleted. The Legacy Behavior Parity table is omitted accordingly: no user-facing component >100 LOC is being deleted or migrated in this plan.

---

## 3) Testing workstream (required)

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Scope: N/A for this chore. The spec §14 + §19 decision log (2026-05-23) explicitly rejects adding a mocked unit test for `_current_head()` — mocking `subprocess.check_output` to test the parsing logic creates a mock-divergence failure mode without exceeding the coverage the two existing integration tests already provide. Trade-off accepted.
- Tasks: none.
- DoD: existing unit suite remains green (`make test-unit`).

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: the two **existing** tests in [`test_migrations.py`](../../../../backend/tests/integration/test_migrations.py) — `TestBaselineMigration::test_upgrade_head_creates_alembic_version` and `TestBaselineMigration::test_round_trip` — must continue to pass. No new tests added.
- Tasks:
  - [ ] Run `make test-integration` after Story 1.2 against the current chain (head `0017`). Both tests pass with `_current_head()` resolving to `"0017"`.
  - [ ] AC-4 stub-migration verification (described in Story 1.2 task 8).
- DoD:
  - [ ] Both pre-existing integration tests pass.
  - [ ] AC-4 manual verification documented in the PR description.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: N/A — no API surface.
- Tasks: none.
- DoD: existing contract suite remains green (`make test-contract`).

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: N/A — no UI surface.
- Tasks: none.
- DoD: existing E2E suite remains green (not run as part of this PR; CI gates it).

### 3.5 Existing test impact audit (required for refactors and UI changes)

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_migrations.py` | `assert row[0] == "0017"` | 2 | Replace with `assert row[0] == _current_head()` (Story 1.2). |
| `backend/tests/integration/test_migration_0016.py` | `assert ... row[0] == "0016"` | 2 (L180 + similar) | **No change.** This file legitimately pins to revision `0016` by using `_alembic("downgrade", "0016")` + `_alembic("upgrade", "0016")` to assert post-migration column shape — the right pattern for per-migration shape tests (spec §3 Out of scope). |
| `migrations/versions/0017_proposals_last_polled_at.py` | `revision: str = "0017"` | 1 | **No change.** Alembic's own source-of-truth declaration; out of scope. |
| All other files under `backend/tests/` | `"0017"` | 0 | None. (`grep -rn '"0017"' backend/tests/` returns only the two matches in `test_migrations.py`.) |

### 3.5 Migration verification (if schema changes)

N/A — this chore makes no schema changes. (The whole point of the chore is to remove the sympathy-edit tax on future migration verifications.)

### 3.6 CI gates

- [ ] `make lint` (ruff) — green
- [ ] `make typecheck` (mypy --strict) — green
- [ ] `make test-unit` — green
- [ ] `make test-integration` — green against the local Compose Postgres or the CI service container (`.github/workflows/pr.yml` Postgres service)
- [ ] `make test-contract` — green (no new contract tests; verifies unrelated regressions)
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` — green (no UI changes; verifies unrelated regressions)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files (required for every implementation plan)

**`state.md`** — update at finalization:
- [ ] Add a one-line entry under "Recent changes" pointing at the chore PR.
- [ ] No active-branch change (the finalization PR cleans up the branch).
- [ ] Alembic head does NOT move — this chore makes no schema changes.

**`architecture.md`** — no updates required. The chore is a test-file refactor; no new services, layers, data flows, or design decisions. Skipping this checklist item.

**`CLAUDE.md`** — no updates required. No new conventions, rules, env vars, or build commands. Skipping this checklist item.

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] No updates required. (Spec §15.)

### 4.2 Product docs (`docs/02_product`)

- [ ] No updates required for the planned-features folder beyond finalization. At finalization, the folder moves to `docs/00_overview/implemented_features/2026_05_23_chore_migration_test_head_brittleness/`.

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] No updates required. The new helper is self-documenting via its docstring; no operator-facing behavior changes.

### 4.4 Security docs (`docs/04_security`)

- [ ] No updates required.

### 4.5 Quality docs (`docs/05_quality`)

- [ ] No updates required. `testing.md`'s description of the integration test layer is unchanged.

**Documentation DoD**

- [ ] `state.md` updated at finalization with a one-line recent-changes entry.
- [ ] `architecture.md`, `CLAUDE.md` unchanged (intentional — confirmed in §15 of the spec).
- [ ] docs/01–05 unchanged (intentional — confirmed in §15 of the spec).

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals

- **Eliminate the 2-lines-per-migration sympathy-edit tax** on `backend/tests/integration/test_migrations.py`. (Single explicit goal.)

### 5.2 Planned refactor tasks

- [ ] Backend refactor: replace two hardcoded head literals with a dynamic helper (Story 1.1 + Story 1.2).
- [ ] Frontend refactor: none.
- [ ] Remove dead/legacy branches: collapse the per-migration changelog comment chain (Story 1.2) — the changelog itself isn't dead, but the comment chain in `test_migrations.py` duplicates content that lives in `migrations/versions/*.py` and `docs/00_overview/implemented_features/`.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by the two existing integration tests (`test_upgrade_head_creates_alembic_version` and `test_round_trip`) continuing to pass.
- [ ] AC-4 manual verification (stub migration → tests pass → stub removed → tests pass) proves the no-sympathy-edit property.
- [ ] `make lint` / `make typecheck` remain green.
- [ ] No expansion of product scope. The chore is explicitly bounded: ~15 LOC, one file, no per-migration shape tests touched.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `uv` installed and on PATH in the integration-test runner | Story 1.1 helper invocation | Implemented (CI's `pr.yml` uses `uv` already; the existing `_alembic()` helper at `test_migrations.py:79-87` already requires it) | Helper raises `FileNotFoundError` on hosts where `uv` is missing — same failure mode the pre-existing helpers already have. Out of scope to harden further. |
| Alembic's `heads` subcommand returns `<id> (head)` on stdout | Story 1.1 parsing logic | Implemented (documented Alembic behavior, stable across versions in use) | If Alembic ever changes the output format, the parser breaks. Recovery: update the parser. Low likelihood given Alembic's API stability. |
| Single-head migration chain | Story 1.1 single-head assertion | Implemented (the project has only had linear migrations to date; no `alembic merge` has been needed) | If a future branch introduces multi-head state, the helper raises a clear `AssertionError` naming the fix (`alembic merge`). This is preferred over silently picking the first head. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The helper gets invoked at module-import time by a future contributor (e.g., as a default argument or top-level constant) | Low | Module fails at collection time on hosts that skip the integration tests — defeats the purpose of `pytestmark` | FR-3 explicitly forbids module-import-time invocation; the helper has a docstring stating this; the DoD verifies via `grep` that the helper name only appears inside test-body function definitions. |
| Hard-pinning the Story 1.1 line number for the helper insertion proves brittle (e.g., the file has been edited between when this plan was written and when execution runs) | Medium | Story 1.1 task 1 picks the wrong insertion line and breaks the file structure | Story 1.1 task 1 re-reads the file before inserting; the spec describes the insertion point relationally ("between `_sync_database_url()` and `fresh_db` fixture") rather than by absolute line number. |
| `make test-integration` runs in CI but the local operator runs it from a host where Postgres is internal-only and unreachable | Low | Local verification skips; the CI run is the only verification path | This is the existing reality per [`local-dev.md` §"Local-vs-CI test layers"](../../../03_runbooks/local-dev.md); not a regression introduced by this chore. The implementer should rely on CI for AC-2/AC-3 verification if their local Postgres is unreachable, and run the AC-4 stub-migration step against the local Compose stack via `make up` first. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| `uv run alembic heads` exits non-zero | Broken `alembic.ini`, corrupt migration chain, missing `uv` | `subprocess.CalledProcessError` propagates out of the test; test fails loudly | Manual — fix the toolchain or migration chain |
| `alembic heads` returns multiple non-empty lines (multi-head state) | A future merge migration or unmerged branch introduces a second head | `_current_head()` raises `AssertionError` with a message naming `alembic merge` | Manual — run `alembic merge` to consolidate, then re-run tests |
| `alembic heads` returns empty output | Migration chain is broken / no revisions exist | `_current_head()` raises `AssertionError` (the `len(lines) == 1` check covers `len(lines) == 0` too) | Manual — investigate the migration chain |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — add the helper. No dependency on existing tests beyond the file's structure.
2. **Story 1.2** — replace the two assertions + collapse the comment chains. Depends on Story 1.1 (the call sites need the helper to exist).

Story 1.1 and Story 1.2 can be bundled into a single commit if preferred — they are tightly coupled and the diff is small. Splitting them into two commits is preferred for reviewability (the helper definition + the call-site swap are conceptually distinct).

### Parallelization opportunities

None — the two stories are sequential by data dependency.

## 8) Rollout and cutover plan

- **Rollout stages:** N/A — test-only change, no production behavior, no staged rollout.
- **Feature flag strategy:** N/A.
- **Migration/cutover steps:** N/A — no schema changes.
- **Reconciliation/repair strategy:** N/A — no external systems.

## 9) Execution tracker (copy/paste section)

### Current sprint

- [ ] Story 1.1 — add `_current_head()` helper with single-head invariant
- [ ] Story 1.2 — replace the two hardcoded assertions and collapse the comment chains
- [ ] AC-4 manual verification (stub migration → tests pass → stub removed → tests pass)
- [ ] CI green (lint + typecheck + unit + integration + contract + Docker build + frontend)
- [ ] Gemini Code Assist review adjudicated
- [ ] Final GPT-5.5 cross-model review on the merged diff

### Blocked items

None.

### Done this sprint

- (populated during execution)

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files modified match story scope (`Modified files` tables — single file: `backend/tests/integration/test_migrations.py`).
- [ ] No endpoint contract changes (chore is test-only).
- [ ] Key interface (Story 1.1's `_current_head()`) implemented with the exact signature documented in **Key interfaces**.
- [ ] Required tests pass at every layer where applicable:
  - [ ] `make test-unit` — green (no new unit tests; suite must not regress)
  - [ ] `make test-integration` — green for both `test_upgrade_head_creates_alembic_version` and `test_round_trip` (or skipped with a documented reason if Postgres is unreachable locally — CI is then the authoritative gate)
  - [ ] `make test-contract` — green (no new contract tests; suite must not regress)
  - [ ] `cd ui && pnpm test` — green (no UI changes; suite must not regress)
- [ ] No migration round-trip evidence required (no schema change).
- [ ] AC-4 stub-migration verification documented in the PR description with a four-step shell transcript.
- [ ] No docs/01–05 updates required (per spec §15).

## 11) Plan consistency review (required before execution)

Performed inline during plan generation. Findings:

1. **Spec ↔ plan FR coverage:** All three FRs (FR-1, FR-2, FR-3) covered by Story 1.1 + Story 1.2. ✅
2. **Spec ↔ plan AC coverage:** AC-1, AC-1b, AC-2, AC-3, AC-4, AC-5, AC-6 all mapped to either a test pass, an inspection check, or the manual stub-migration verification (per spec §18). ✅
3. **Spec ↔ plan endpoint count:** Both are zero. Trivially consistent. ✅
4. **Spec ↔ plan error code coverage:** Both are zero. Trivially consistent. ✅
5. **Test file count:** zero new test files; only the existing two integration tests are exercised. Matches §3 testing workstream inventory. ✅
6. **Open questions resolved:** Spec §19 reports zero open questions. ✅
7. **Plan ↔ codebase verification:**
   - File path `backend/tests/integration/test_migrations.py` exists ✅
   - The two `assert row[0] == "0017"` sites exist at L132 + L157 ✅ (verified by `grep -n '"0017"' backend/tests/integration/test_migrations.py` returning exactly those two matches)
   - `subprocess` is imported at L33 ✅
   - Existing `_alembic()` helper at L79-87 uses the same `["uv", "run", "alembic", *args]` invocation convention the new helper follows ✅
   - `pytestmark` skip gate at L69-76 is unmodified by the plan ✅
   - Alembic head is `0017` (verified by `ls migrations/versions/ | tail -1` showing `0017_proposals_last_polled_at.py`) ✅
8. **Infrastructure path verification:**
   - Migration directory: `migrations/versions/` (verified by `ls migrations/versions/`). NOT `backend/alembic/versions/` or `backend/app/db/migrations/versions/`. ✅
   - Test directory: `backend/tests/integration/` (verified by `ls backend/tests/integration/test_migrations.py`). ✅
9. **Enumerated value contract audit:** N/A — no filters, no dropdowns, no sort controls, no badges, no API enums. ✅
10. **Admin control / ceiling enforcement audit:** N/A — MVP1 has no admin/tenant model. ✅
11. **Audit-event coverage audit:** N/A — MVP1 has no `audit_log` table; chore touches no business state regardless. ✅
12. **Persistence scope:** N/A — no client-side storage.
13. **Legacy behavior parity:** N/A — no user-facing component >100 LOC is being deleted or migrated.

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates. (FR-1 → Story 1.1; FR-2 → Story 1.2; FR-3 → Story 1.1 + DoD asserts.)
- [x] Every story includes New files (zero, explicit), Modified files, Tasks, and DoD. (Endpoints / Schemas omitted per template rule — story is test-only.)
- [x] Test layers explicitly scoped (Unit: N/A by spec decision; Integration: existing tests; Contract/E2E: N/A).
- [x] Documentation updates across docs/01-05 are planned (zero updates, explicit per spec §15; `state.md` gets one line at finalization).
- [x] Lean refactor scope and guardrails explicit.
- [x] Phase/epic gates measurable (Story 1.2 DoD includes the AC-4 verification).
- [x] Story-by-Story Verification Gate included (§10).
- [x] Plan consistency review (§11) performed with no unresolved findings.
