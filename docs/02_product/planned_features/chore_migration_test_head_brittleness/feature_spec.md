# Feature Specification — `test_migrations.py` dynamic head lookup

**Date:** 2026-05-23
**Status:** Draft
**Owners:** Eric Starr (engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`backend/tests/integration/test_migrations.py`](../../../../backend/tests/integration/test_migrations.py)
- [`docs/05_quality/testing.md`](../../../05_quality/testing.md) — integration test layer convention
- [`CLAUDE.md`](../../../../CLAUDE.md) — Absolute Rule #5 (every migration includes `downgrade()` and round-trips cleanly)

---

## 1) Purpose

- **Problem:** Two assertions in [`backend/tests/integration/test_migrations.py`](../../../../backend/tests/integration/test_migrations.py) (lines 132 and 157) pin the Alembic head string to a hardcoded literal (currently `"0017"`). Every new migration bumps the head and breaks both assertions. The failure only manifests in `make test-integration` (which requires a running Postgres and is therefore skipped on the host that runs `make test-unit`-only verification per [`local-dev.md` §"Local-vs-CI test layers"](../../../03_runbooks/local-dev.md)).
- **Outcome:** Replace the two hardcoded `"0017"` literals with a dynamic `_current_head()` helper that shells out to `uv run alembic heads` and returns the current head revision id. Adding a new migration no longer requires a sympathy edit in this file. The verification path remains the same (CI's integration job runs the round-trip test against the canonical migration chain).
- **Non-goal:** Per-migration shape tests like [`backend/tests/integration/test_migration_0016.py`](../../../../backend/tests/integration/test_migration_0016.py). Those intentionally pin to a specific revision via `_alembic("downgrade", "0016") + _alembic("upgrade", "0016")` to assert the post-migration schema shape — that's correct behavior, not the failure mode this chore addresses.

## 2) Current state audit

### Existing implementations

- [`backend/tests/integration/test_migrations.py`](../../../../backend/tests/integration/test_migrations.py) — Alembic round-trip integration tests. Marked `@pytest.mark.integration`; auto-skips on hosts where Postgres isn't TCP-reachable (the common case for `make test-integration` from the operator shell — Compose's Postgres is internal-only per CLAUDE.md "Ports" + `local-dev.md` §"Local-vs-CI test layers"). Has two assertion sites:
  - **L132** inside `TestBaselineMigration::test_upgrade_head_creates_alembic_version`: asserts `row[0] == "0017"` after `alembic upgrade head`.
  - **L157** inside `TestBaselineMigration::test_round_trip`: asserts `row[0] == "0017"` after `downgrade -1 + upgrade head`.
  - Both assertions are preceded by a multi-line comment chain documenting each migration that bumped the head (`# 0001 baseline`, `# 0008–0013 search_vector`, `# 0014 clusters.target_filter`, ..., `# 0017 proposals.last_polled_at`). The comment chain grows by ~2 lines per migration; the chore preserves it for human readers but rewrites the assertion line.
- [`backend/tests/integration/test_migration_0016.py:174-184`](../../../../backend/tests/integration/test_migration_0016.py#L174) — the precedent for tests that legitimately pin to a specific revision: pins via `_alembic("downgrade", "0016")` + `_alembic("upgrade", "0016")` so the assertions about the column shape are tied to that specific migration's effects, regardless of how many later migrations exist. **Not in scope for this chore** — those tests are correctly pinned.
- [`migrations/versions/0017_proposals_last_polled_at.py`](../../../../migrations/versions/0017_proposals_last_polled_at.py) — current head migration. The string `"0017"` appears here as `revision: str = "0017"` (the Alembic-generated identifier); not touched by this chore.

`grep -rn '"0017"' backend/tests/ migrations/` returns exactly three matches: the two assertions on lines 132 + 157 of `test_migrations.py` (in scope) and the `revision: str` declaration in `0017_proposals_last_polled_at.py` (out of scope — Alembic source-of-truth).

### Navigation and link impact

N/A — no UI, no URL changes, no docs link rewrites.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/test_migrations.py` | `assert row[0] == "0017"` | 2 | Replace with `assert row[0] == _current_head()` |

No other test file references the hardcoded literal.

### Existing behaviors affected by scope change

- **Behavior:** Both assertions hardcode the latest revision id. **Current:** Every new migration requires editing both lines. **New:** Both assertions resolve the head dynamically; new migrations require no edit. **Decision needed:** No — the dynamic lookup is strictly less brittle. The comment chain documenting "what each migration adds" stays in the file as human-readable changelog (it's still valuable; just no longer load-bearing for the assertion).

---

## 3) Scope

### In scope

- New private helper `_current_head() -> str` in [`backend/tests/integration/test_migrations.py`](../../../../backend/tests/integration/test_migrations.py), defined once and reused by both test methods.
- Replace the two hardcoded `"0017"` assertions with `_current_head()` calls.
- Replace the growing per-migration changelog comment chain above each assertion with a single anchor comment pointing to `_current_head()`'s docstring. The detailed migration history continues to live in `migrations/versions/*.py` (each migration carries its own docstring) and `docs/00_overview/implemented_features/`; duplicating it inside `test_migrations.py` was the source of the 2-lines-per-migration tax that this chore eliminates.

### Out of scope

- Per-migration shape tests (`test_migration_0016.py`, `test_clusters_target_filter_migration.py`, `test_trials_per_query_metrics_migration.py`, etc.) that legitimately pin to a specific revision. Those use the right pattern already.
- The `revision: str = "0017"` declaration inside `migrations/versions/0017_proposals_last_polled_at.py`. That's Alembic's own source-of-truth; not a duplicate to remove.
- Adding new test coverage. The existing two integration tests already cover the assertion path. The helper is exercised whenever either test runs.
- Refactoring `test_migrations.py`'s `_alembic()` helper or the `pytestmark` skip logic. Out of scope.
- Linting/style sweeps unrelated to the two assertion sites.

### API convention check

N/A — this chore touches only an integration test file. No API endpoints, no router files, no error envelopes.

### Phase boundaries

Single phase, single PR. No phase boundaries.

## 4) Product principles and constraints

- **CLAUDE.md Absolute Rule #5 (every migration must include `downgrade()` and round-trip cleanly).** Preserved: the integration test continues to verify `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` against the canonical chain.
- **Test layer convention** ([`docs/05_quality/testing.md`](../../../05_quality/testing.md)): integration tests are DB-backed and `@pytest.mark.integration`-marked. Preserved.
- **Skip-on-unreachable behavior** ([`test_migrations.py:46-66`](../../../../backend/tests/integration/test_migrations.py#L46)): the module-level `pytestmark` skip logic is unchanged. The dynamic helper does NOT run when the module skips — `_current_head()` is called inside test bodies, downstream of the skip gate.

### Anti-patterns

- **Do not** parse migration filenames from the `migrations/versions/` directory to derive the head — Option B in the idea, explicitly rejected. Alembic owns the revision-graph traversal (downgrades may not be alphabetically ordered if a future branch lands), and `alembic heads` is its source-of-truth output.
- **Do not** add `_current_head()` as a public module-level constant evaluated at import time (`_HEAD = _current_head()`). The helper must be called inside the test body so the `pytestmark` skip gate runs first; otherwise a non-Compose host that doesn't have `uv` installed will fail at import. The skip is module-level (`pytestmark`), so deferring the subprocess call to test-body execution time is correct.
- **Do not** replicate the helper into other migration tests. The per-migration tests (e.g., `test_migration_0016.py`) intentionally pin to a specific revision and should keep their hardcoded string. Only `test_migrations.py`'s "always-at-head" assertions need the dynamic lookup.
- **Do not** keep the per-migration changelog comments above each assertion. They grew by 2 lines per migration — exactly the maintenance tax this chore eliminates. The detailed changelog lives in `migrations/versions/*.py` (each migration's docstring) and `docs/00_overview/implemented_features/`; a single anchor comment pointing to `_current_head()`'s docstring is sufficient at the call site.

## 5) Assumptions and dependencies

- **Assumption:** `uv run alembic heads` is callable from the integration-test environment. Verified — the existing `_alembic()` helper at [`test_migrations.py:79-87`](../../../../backend/tests/integration/test_migrations.py#L79) already shells out as `["uv", "run", "alembic", *args]` from the repo root. The new helper follows the same invocation convention.
- **Dependency:** Alembic's `heads` subcommand prints the current head id followed by `(head)` (e.g., `0017 (head)\n`). Verified — this is documented Alembic behavior and matches every Alembic version the project has used.
- **Dependency:** CI (`.github/workflows/pr.yml`) runs `make test-integration` against a service-container Postgres. No CI changes required.

## 6) Actors and roles

- Primary actor: developer adding a new migration (the future contributor whose merge would have broken the head assertion).
- Role model: N/A — single-tenant install, no auth surface.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2; this chore touches no business state.

---

## 7) Functional requirements

### FR-1: Dynamic head lookup helper

- **Requirement:**
  - The system **MUST** define a private helper `_current_head() -> str` in `backend/tests/integration/test_migrations.py` that returns the current Alembic head revision id by invoking `uv run alembic heads` from the repo root.
  - The helper **MUST** assert that `alembic heads` returns exactly one non-empty line and raise `AssertionError` if the project enters a multi-head state. Rationale: the spec assumes a single linear migration chain (no merge migrations), and silently picking the first head if a future branch lands would mask a real schema-design issue. The error message **MUST** name `alembic merge` as the canonical fix.
  - The helper **MUST** parse the first whitespace-separated token of the (single) line as the revision id (matching Alembic's documented output format `<revision_id> (head)`).
  - The helper **MUST** raise `subprocess.CalledProcessError` if `alembic heads` exits non-zero (no defensive try/except — failure means the toolchain is broken and should fail loudly).
  - The helper **MUST NOT** be invoked at module import time. It is called inside test bodies, downstream of the `pytestmark` skip gate.

### FR-2: Replace hardcoded assertions

- **Requirement:**
  - The system **MUST** replace `assert row[0] == "0017"` at `test_migrations.py:132` with `assert row[0] == _current_head()`.
  - The system **MUST** replace `assert row[0] == "0017"` at `test_migrations.py:157` with `assert row[0] == _current_head()`.
  - The per-migration changelog comments preceding the assertions **MUST** be replaced with a single anchor comment of the form `# Head is resolved dynamically via _current_head() — see helper docstring.` to prevent the comment chain from growing on every future migration. The detailed changelog of which migration shipped what continues to live in `migrations/versions/*.py` and `docs/00_overview/implemented_features/`.

### FR-3: No regression in skip behavior

- **Requirement:**
  - The module-level `pytestmark = pytest.mark.skipif(not _postgres_reachable(), ...)` **MUST** continue to gate every test in the module unchanged.
  - The helper **MUST NOT** be referenced from any code that runs at module collection time (top-level assignments, default arguments, decorator arguments). This ensures that on a host where Postgres is unreachable, the module skips before `_current_head()` is ever invoked.
- **Skip-gate scope (informational, not a new requirement):**
  - Hosts where Postgres is **unreachable** skip the module entirely — no `uv` invocation occurs. ✅
  - Hosts where Postgres is **reachable but `uv` is missing** are not protected by the skip gate. The pre-existing `_alembic()` helper at [`test_migrations.py:79-87`](../../../../backend/tests/integration/test_migrations.py#L79) already shells out as `["uv", "run", "alembic", *args]` and would fail in this case — so `uv` is an existing prerequisite of the integration-test toolchain, not a new one this chore introduces. The chore does not extend the skip gate to cover this case; the existing failure mode is intentional and out of scope.

---

## 8) API and data contract baseline

N/A across all subsections — this chore touches no API surface, no error codes, no enumerated value contracts.

## 9) Data model and state transitions

N/A — no schema changes, no new tables, no migrations, no state machines touched.

## 10) Security, privacy, and compliance

- Threats: none. The helper shells out to a developer-tool binary (`uv run alembic`) with no user-supplied input. No new attack surface.
- Controls: subprocess is invoked with a fixed argv list (no shell, no string interpolation). Matches the existing `_alembic()` helper's pattern.
- Secrets/key handling: N/A.
- Auditability: N/A — integration test, no business state mutation.
- Data retention/deletion/export impact: N/A.

## 11) UX flows and edge cases

N/A — no UI changes.

## 12) Given/When/Then acceptance criteria

### AC-1: Helper resolves current head from `alembic heads`

- **Given** the integration test module is running (Postgres reachable, `uv` installed)
- **When** `_current_head()` is called against a single-head migration chain
- **Then** it returns the first whitespace-separated token of `alembic heads`'s single output line — i.e., the current head revision id (e.g., `"0017"` against the chain as of this spec)
- **Example values (current chain):**
  - `subprocess.check_output(["uv", "run", "alembic", "heads"], cwd=REPO, text=True)` returns `"0017 (head)\n"`
  - `_current_head()` returns `"0017"`
- **Example values (future chain):**
  - After migration `0018_<slug>.py` ships, the same call returns `"0018 (head)\n"` and `_current_head()` returns `"0018"` — without any edit to the helper or its callers.

### AC-1b: Helper rejects multi-head state

- **Given** a hypothetical broken state where `alembic heads` returns two non-empty lines (multiple heads)
- **When** `_current_head()` is called
- **Then** it raises `AssertionError` with a message naming `alembic merge` as the canonical fix
- **Verification:** unit-level inspection of the helper, not a CI-exercised path (the project does not currently have multi-head migrations; this AC documents the safety net)

### AC-2: `test_upgrade_head_creates_alembic_version` passes against the dynamic head

- **Given** a fresh Postgres database, all migrations applied via `alembic upgrade head`
- **When** the test queries `SELECT version_num FROM alembic_version`
- **Then** the assertion `assert row[0] == _current_head()` passes — both sides resolve to the same head revision id

### AC-3: `test_round_trip` passes against the dynamic head after downgrade + upgrade

- **Given** a database at head, then `alembic downgrade -1` followed by `alembic upgrade head`
- **When** the test queries `SELECT version_num FROM alembic_version`
- **Then** the assertion `assert row[0] == _current_head()` passes

### AC-4: Future migration adds no sympathy edit to `test_migrations.py`

- **Given** a contributor adds a new migration `migrations/versions/0018_<slug>.py` with `down_revision = "0017"` and `revision = "0018"`
- **When** the contributor runs `make test-integration` against a Postgres that has applied the new migration
- **Then** both `test_upgrade_head_creates_alembic_version` and `test_round_trip` pass without any edit to `test_migrations.py`
- **Verification:** Manually exercised during implementation: create a stub migration that adds a no-op `op.execute("SELECT 1")`, run the tests, confirm green, delete the stub before commit. Documented in the implementation plan.

### AC-5: Helper failure fails the test loudly

- **Given** `uv run alembic heads` exits non-zero (e.g., broken `alembic.ini`, corrupt migration chain)
- **When** `_current_head()` is invoked
- **Then** a `subprocess.CalledProcessError` propagates out of the test (no defensive swallow). The test failure clearly identifies a toolchain problem rather than a stale-pin problem.

### AC-6: Module skips when Postgres unreachable (no regression)

- **Given** a host without Postgres reachable on the configured `DATABASE_URL`
- **When** pytest collects the module
- **Then** the entire module is skipped via the existing `pytestmark` — `_current_head()` is never called, no `uv` invocation occurs
- **Anti-regression note:** This is the reason FR-1 forbids module-import-time invocation of the helper.

## 13) Non-functional requirements

- **Performance:** negligible — adds one `subprocess.check_output` call per test method (≤2 calls per integration run). The subprocess invocation cost is dominated by the existing `_alembic("upgrade", "head")` calls; the helper adds no measurable overhead.
- **Reliability:** unchanged — the test continues to gate on the same migration chain.
- **Operability:** no new metrics, logs, or alerts. The integration test outcome (pass/fail) remains the only operational signal.
- **Accessibility/usability:** N/A.

## 14) Test strategy requirements (spec-level)

- **Unit tests:** None added. `_current_head()` is exercised by the two existing integration tests; a dedicated unit test would have to mock `subprocess.check_output` to verify the parsing logic, which adds little value over the integration-test coverage and creates a mock-divergence failure mode. Trade-off accepted.
- **Integration tests:** Existing — `test_upgrade_head_creates_alembic_version` and `test_round_trip` in `backend/tests/integration/test_migrations.py`. Both must continue to pass.
- **Contract tests:** N/A.
- **E2E tests:** N/A.
- **Verification gates the implementer must hit:**
  - `make lint` (ruff) — green
  - `make typecheck` (mypy --strict) — green; `_current_head()` is typed `() -> str`
  - `make test-unit` — green (no new unit tests, but the suite must not regress)
  - `make test-integration` — green against the local Compose Postgres (or CI Postgres service container). Both `test_upgrade_head_creates_alembic_version` and `test_round_trip` MUST pass with `_current_head()` resolving to `"0017"`.

## 15) Documentation update requirements

- `docs/01_architecture`: none.
- `docs/02_product`: none (the idea + spec + plan stay in the planned-features folder until finalization moves them to `implemented_features/`).
- `docs/03_runbooks`: none. The new helper is self-documenting via its docstring; no operator-facing behavior changes.
- `docs/04_security`: none.
- `docs/05_quality`: none — `testing.md`'s description of the integration test layer is unchanged.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A — test-only change.
- **Migration/backfill expectations:** N/A — no schema changes.
- **Operational readiness gates:** N/A.
- **Release gate:** PR-level — green CI (lint + typecheck + unit + integration + contract + Docker build + frontend) is the only gate. No staging deploy, no maintainer sign-off beyond Gemini review.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (helper) | AC-1, AC-5, AC-6 | Story 1.1 (define `_current_head()`) | `backend/tests/integration/test_migrations.py` | none |
| FR-2 (replace assertions) | AC-2, AC-3, AC-4 | Story 1.2 (replace both assertions + comment update) | `backend/tests/integration/test_migrations.py` | none |
| FR-3 (skip regression) | AC-6 | Story 1.1 (helper placement) | `backend/tests/integration/test_migrations.py` | none |

## 18) Definition of feature done

This feature is complete when:

- [ ] **CI-exercised acceptance criteria pass in CI**: AC-1 (helper resolves head — exercised by AC-2 + AC-3 invocations), AC-2 (upgrade-head test passes), AC-3 (round-trip test passes).
- [ ] **Inspection-level acceptance criteria documented and verified at code-review time**: AC-1b (multi-head assertion — verified by reading the helper), AC-4 (no-sympathy-edit — verified by the manual stub-migration check described in AC-4), AC-5 (loud failure on non-zero exit — verified by reading the helper), AC-6 (skip-on-unreachable — exercised every time CI runs but the skip path itself is the existing pytestmark, not a new code path introduced by this chore).
- [ ] `make lint`, `make typecheck`, `make test-unit`, `make test-integration`, `make test-contract` are all green locally on the feature branch before push.
- [ ] CI workflow (`.github/workflows/pr.yml`) is green on the PR.
- [ ] Manual AC-4 verification recorded in the implementation plan (stub migration added → tests pass → stub removed → tests still pass).
- [ ] Gemini Code Assist review comments adjudicated.
- [ ] Final GPT-5.5 review (per CLAUDE.md cross-model review policy) is clean or has documented Accept/Reject adjudications.
- [ ] No open questions remain in §19.
- [ ] Finalization PR moves `planned_features/chore_migration_test_head_brittleness/` to `implemented_features/<YYYY_MM_DD>_chore_migration_test_head_brittleness/` and updates `state.md`.

## 19) Open questions and decision log

### Open questions

None.

### Decision log

- **2026-05-23 — Option A (`alembic heads` subprocess) selected** — Locked in idea.md preflight 2026-05-23. Option B (parse migration filenames) rejected: carries lexicographic-sortability risk if a future branch lands and offers no upside since `alembic heads` is Alembic's source-of-truth output.
- **2026-05-23 — No new unit test for `_current_head()`** — Mocking `subprocess.check_output` to test the parsing logic adds a mock-divergence failure mode without meaningfully exceeding the coverage the two existing integration tests already provide. Trade-off accepted; documented in §14.
- **2026-05-23 — Helper invoked inside test bodies, not at module import** — Required so the `pytestmark = pytest.mark.skipif(...)` gate runs first. A host without `uv` installed (or with no Postgres) will see the module skip rather than fail at collection time.
- **2026-05-23 — Per-migration changelog comments collapsed to a single anchor comment** — The detailed changelog of which migration shipped what is preserved in `migrations/versions/*.py` (each migration carries its own docstring) and `docs/00_overview/implemented_features/`. Keeping the comment chain in `test_migrations.py` duplicates that source and grows with every migration; collapsing it removes the maintenance tax without losing information. (Locked by FR-2 + §3 In scope + §4 Anti-pattern — no remaining ambiguity.)
- **2026-05-23 — Helper asserts single-head invariant** — `_current_head()` raises `AssertionError` if `alembic heads` returns more than one head, with a message naming `alembic merge` as the fix. Reason: silently picking the first head if a future branch lands would mask a real schema-design issue. Surfaced by GPT-5.5 cross-model review (cycle 1, Pass B finding #2, accepted).
