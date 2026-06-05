# Implementation Plan — Replace deprecated `arq_pool.close()` with `aclose()`

**Date:** 2026-06-01
**Status:** Complete (shipped in PR #387, 2026-06-01)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** CLAUDE.md (Conventional Commits + DCO sign-off; no migration; no behavior change)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs.
- This is a mechanical deprecation fix: two call-site edits + their regression tests. No migration, no API, no UI, no schema.
- Fail-loud tests: assert the call shape directly (`aclose` awaited, `close` not called) — do not rely on a global warning filter.
- Keep scope bounded to exactly the two pool-close call sites and their tests. No "while I'm here" refactors.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.1 | API lifespan (`main.py:144`) → `aclose()` + regression test |
| FR-2 | Epic 1 / Story 1.2 | Worker `on_shutdown` (`all.py:225`) → `aclose()` + new regression test |
| FR-3 | Epic 1 / Stories 1.1, 1.2 | No deprecation warning — validated structurally via FR-4 assertions |
| FR-4 | Epic 1 / Stories 1.1, 1.2 | Regression guards on both paths |

No deferred phases — the spec is single-phase. No `phase<N>_idea.md` tracking required.

## 2) Delivery structure

**Structure:** Epic → Story → Tasks → DoD. Single epic, two stories, both backend-only and test-only-plus-one-line.

### Conventions (project-specific)

```
- arq pool is ArqRedis (subclass of redis.asyncio.Redis); aclose() is the
  non-deprecated coroutine present on arq==0.28.0 (verified 2026-06-01).
- Existing best-effort try/except around the API close stays untouched (main.py:143-146).
- Existing `if arq_pool is not None:` guards stay untouched (main.py:142, all.py:224).
- Tests live in backend/tests/unit/. asyncio_mode = "auto" (pyproject.toml:213) — async
  test functions need no decorator.
- Commit with `git commit -s` (DCO) + Conventional Commits `chore:` prefix.
```

### AI Agent Execution Protocol

0. Load context: read `architecture.md` + `state.md`.
1. Read story scope (outcome + modified files + DoD).
2. Implement the one-line call-site swap.
3. Update/add the regression test.
4. Run `make test-unit` (targeted: the two touched test files), `make lint`, `make typecheck`.
5. No frontend, no migration, no docs-beyond-state.md.
6. Attach evidence (commands run + pass/fail) at finalization.

---

## Epic 1 — Swap `arq_pool.close()` → `aclose()` on both shutdown paths

**Epic gate (hard stop):** Both call sites use `await arq_pool.aclose()`; no `arq_pool.close()` call remains in `backend/app/` or `backend/workers/`; both regression tests pass; `make test-unit` + `make lint` + `make typecheck` clean.

### Story 1.1 — API lifespan closes the Arq pool with `aclose()`
**Outcome:** The FastAPI lifespan shutdown awaits `arq_pool.aclose()` instead of the deprecated `arq_pool.close()`; a regression test asserts the async-correct form.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Line 144: `await arq_pool.close()` → `await arq_pool.aclose()`. Surrounding `if arq_pool is not None:` guard (142) and best-effort try/except (143-146) unchanged. |
| `backend/tests/unit/test_main_lifespan.py` | Line 86: stub `fake_pool.aclose = AsyncMock(return_value=None)` instead of `fake_pool.close = ...`. Add a test asserting the lifespan awaits `fake_pool.aclose` once and never calls `fake_pool.close`. |

**Endpoints**

N/A — no API surface.

**Key interfaces**

No new functions. The edit is a single method-name change on an existing await:

```python
# backend/app/main.py — lifespan finally block (existing structure, line 142-146)
if arq_pool is not None:
    try:
        await arq_pool.aclose()   # was: arq_pool.close()
    except Exception as exc:  # noqa: BLE001 — shutdown swallow
        logger.warning("arq pool close raised during shutdown", error=str(exc))
```

**Tasks**
1. Edit `backend/app/main.py:144`: `await arq_pool.close()` → `await arq_pool.aclose()`. Leave the guard, try/except, and WARN log text unchanged.
2. Edit `backend/tests/unit/test_main_lifespan.py:86`: change `fake_pool.close = AsyncMock(return_value=None)` to `fake_pool.aclose = AsyncMock(return_value=None)`. (The fixture exposes the pool under the `"pool"` key for assertions.)
3. Add a test method in `test_main_lifespan.py` (e.g., `test_lifespan_closes_arq_pool_with_aclose`) that enters/exits `app_main.lifespan(app)` and asserts:
   - `_patched_externals["pool"].aclose.assert_awaited_once()`
   - `_patched_externals["pool"].close.assert_not_called()` (a bare `MagicMock().close` is never awaited; this guards against reintroducing the deprecated call).

**Definition of Done (DoD)**
- `backend/app/main.py:144` reads `await arq_pool.aclose()`.
- `backend/tests/unit/test_main_lifespan.py` stubs `aclose` (not `close`) and the new test asserts `aclose` awaited once + `close` not called (AC-1, AC-4).
- `make test-unit` passes for `test_main_lifespan.py`; `make lint` + `make typecheck` clean.

### Story 1.2 — Worker `on_shutdown` closes the Arq pool with `aclose()`
**Outcome:** The Arq worker `on_shutdown` hook awaits `arq_pool.aclose()` instead of the deprecated `arq_pool.close()`; a new regression test (first coverage on this path) asserts the async-correct form.

**New files**

None. (Test added to the existing `test_workers.py`.)

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Line 225: `await arq_pool.close()` → `await arq_pool.aclose()`. Surrounding `if arq_pool is not None:` guard (224) and the preceding Optuna-engine disposal (215-221) unchanged. |
| `backend/tests/unit/test_workers.py` | Add a test invoking `on_shutdown(ctx)` with a fake pool + fake/absent Optuna storage, asserting `arq_pool.aclose` awaited and `close` not called. Add a pool-absent no-op case. `on_shutdown` has no prior coverage (the file only checks `on_startup` exists, lines 109-111). |

**Endpoints**

N/A.

**Key interfaces**

No new functions. Single method-name change on an existing await:

```python
# backend/workers/all.py — on_shutdown(ctx) (existing structure, line 223-225)
arq_pool: ArqRedis | None = ctx.get("arq_pool")
if arq_pool is not None:
    await arq_pool.aclose()   # was: arq_pool.close()
```

**Tasks**
1. Edit `backend/workers/all.py:225`: `await arq_pool.close()` → `await arq_pool.aclose()`. Leave the guard and Optuna disposal unchanged.
2. Import `on_shutdown` from `backend.workers.all` in `test_workers.py`.
3. Add a test (e.g., `test_on_shutdown_closes_arq_pool_with_aclose`):
   - Build `fake_pool = MagicMock()` with `fake_pool.aclose = AsyncMock(return_value=None)`.
   - Call `await on_shutdown({"arq_pool": fake_pool})` (omit `optuna_storage` so the storage branch is a no-op via `ctx.get(...)`, or pass a stub whose engine is `None`).
   - Assert `fake_pool.aclose.assert_awaited_once()` and `fake_pool.close.assert_not_called()`.
4. Add a pool-absent no-op test (e.g., `test_on_shutdown_no_pool_is_noop`): `await on_shutdown({})` raises nothing and calls neither method.

**Definition of Done (DoD)**
- `backend/workers/all.py:225` reads `await arq_pool.aclose()`.
- `test_workers.py` has a new test asserting `on_shutdown` awaits `aclose` + never calls `close` (AC-2), plus a pool-absent no-op case (AC-4).
- `make test-unit` passes for `test_workers.py`; `make lint` + `make typecheck` clean.
- Combined epic check: `grep -rn "arq_pool.close()" backend/app/ backend/workers/` returns no matches.

---

## UI Guidance (required for frontend-facing work)

N/A — no frontend scope. No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Scope: both shutdown-path call shapes.
- Tasks:
  - [ ] Update `test_main_lifespan.py` to stub + assert `aclose` (Story 1.1).
  - [ ] Add `on_shutdown` `aclose` assertion + pool-absent no-op in `test_workers.py` (Story 1.2).
- DoD:
  - [ ] Both paths assert `aclose` awaited once + `close` not called; pool-absent paths are no-ops.

### 3.2 Integration tests
- N/A — no DB/workflow surface. The unit tests cover both shutdown paths. `backend/app/main.py` is excluded from coverage measurement (`pyproject.toml:237`), so the lifespan unit test is the regression guard, not a coverage delta.

### 3.3 Contract tests
- N/A — no endpoint added or changed.

### 3.4 E2E tests
- N/A — no UI.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/test_main_lifespan.py` | `fake_pool.close = AsyncMock(...)` (line 86) | 1 | Update to `fake_pool.aclose` + add assertion (Story 1.1). Required: after the fix the lifespan awaits `aclose`; a bare-MagicMock `aclose` is non-awaitable and would raise without this stub change. |
| `backend/tests/unit/test_workers.py` | `on_startup` existence check (109-111); no `on_shutdown` coverage | 0 | Add new `on_shutdown` test (Story 1.2). No existing assertion changes. |

### 3.5 Migration verification
- N/A — no schema change. Alembic head stays `0022_solr_engine_auth_check`.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make lint`
- [ ] `make typecheck`
- (integration / contract / e2e: N/A — out of scope)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files
- **`state.md`** — at finalization, prepend the merge one-liner to "Last 5 merges" (drop the 6th) and add the full entry to `state_history.md`. Alembic head unchanged. No active-branch/priority change beyond the merge.
- **`architecture.md`** — no change (no new service/layer/flow; lifecycle structure unchanged).
- **`CLAUDE.md`** — no change (no new convention/env-var/build command; no maturity-boundary crossing).

### 4.1–4.5 Topical docs (`docs/01`–`05`)
- None required. Pure lifecycle deprecation fix with no architectural, product, runbook, security, or quality-doc impact.

**Documentation DoD**
- [ ] `state.md` merge one-liner added at finalization; `state_history.md` entry added.

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals
- Remove the deprecated `arq_pool.close()` usage on both shutdown paths; align with the already-correct `redis_client.aclose()` precedent in the same file (`main.py:177`).

### 5.2 Planned refactor tasks
- [ ] Backend: swap both `close()` → `aclose()` (Stories 1.1, 1.2).
- [ ] No dead branches to remove.

### 5.3 Refactor guardrails
- [ ] Behavioral parity proven by the two regression tests (close semantics identical; only deprecation status differs).
- [ ] Lint/typecheck green.
- [ ] No product-scope expansion.
- [ ] No new dependency, no arq version bump.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `arq==0.28.0` (`ArqRedis.aclose`) | Stories 1.1, 1.2 | implemented (verified) | None on current pin. If arq downgraded below `aclose` introduction, the call would `AttributeError` — `aclose` is present at 0.28.0. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Forgetting the `test_main_lifespan.py` stub change → test raises `TypeError` awaiting a bare MagicMock | L | L | Story 1.1 task 2 makes the stub swap explicit; DoD asserts it. |
| Reintroducing `close()` in a future edit | L | L | Both regression tests assert `close.assert_not_called()`; epic gate greps for residual `arq_pool.close()`. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| `aclose()` raises during API shutdown | Redis already gone at shutdown | Existing best-effort try/except swallows + WARN-logs (`main.py:145-146`) — unchanged | Auto (logged) |
| Pool absent at shutdown | Startup pool-build failed (API) / pool not in worker ctx | `if arq_pool is not None:` guard skips the close — no raise | Auto (no-op) |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 1.1 (API lifespan).
2. Story 1.2 (worker `on_shutdown`).

### Parallelization opportunities
- Stories 1.1 and 1.2 touch disjoint files (`main.py` + `test_main_lifespan.py` vs. `all.py` + `test_workers.py`) and could be done in either order or together in one commit. Bundle both into a single PR (one branch per session per CLAUDE.md).

## 8) Rollout and cutover plan

- Rollout stages: single PR, full. No feature flag, no migration, no cutover steps.
- Release gate: `make test-unit` + `make lint` + `make typecheck` green; `pr.yml` CI green.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — API lifespan `aclose()` + regression test
- [ ] Story 1.2 — worker `on_shutdown` `aclose()` + regression test

### Blocked items
- None.

### Done this sprint
- (none yet)

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Modified files match story scope (call site + its test).
- [ ] No endpoint/schema/migration (N/A for this plan).
- [ ] Both regression tests added/updated and passing.
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make lint`
    - [ ] `make typecheck`
- [ ] `grep -rn "arq_pool.close()" backend/app/ backend/workers/` returns no matches (epic gate).
- [ ] `state.md` / `state_history.md` updated at finalization.

## 11) Plan consistency review (performed)

1. **Spec ↔ plan endpoint count:** Spec §8.1 = N/A (0 endpoints). Plan = 0 endpoints. Match. ✓
2. **Spec ↔ plan FR coverage:** FR-1→Story 1.1, FR-2→Story 1.2, FR-3→Stories 1.1+1.2, FR-4→Stories 1.1+1.2. All 4 FRs assigned. ✓
3. **Story internal consistency:** No endpoint tables / schemas (N/A). DoD references the correct call sites (`main.py:144`, `all.py:225`) and the correct test files. No file owned by two stories (1.1 owns `main.py` + `test_main_lifespan.py`; 1.2 owns `all.py` + `test_workers.py`). ✓
4. **Test file count:** 2 touched test files (`test_main_lifespan.py` updated, `test_workers.py` extended), each assigned to exactly one story. Match §3.1. ✓
5. **Gate arithmetic:** Epic gate = "both call sites + grep clean + 2 tests green" — matches the 2 stories below it. ✓
6. **Open questions resolved:** Spec §19 has no open questions. ✓
7. **Plan ↔ codebase verification:**
   - `backend/app/main.py:144` — `await arq_pool.close()` confirmed present (read 2026-06-01). ✓
   - `backend/workers/all.py:225` — `await arq_pool.close()` confirmed present; `on_shutdown(ctx)` at line 212, bound at 270. ✓
   - `backend/tests/unit/test_main_lifespan.py:85-86` — `fake_pool = MagicMock()` + `fake_pool.close = AsyncMock(...)`; pool exposed under `"pool"` key (line 98). ✓
   - `backend/tests/unit/test_workers.py:109-111` — asserts `on_startup` exists/callable only; no `on_shutdown` coverage. ✓
   - `arq==0.28.0` `ArqRedis.aclose` exists (runtime-verified). ✓
8. **Infrastructure path verification:** No migration (Alembic head `0022` unchanged, untouched). Test dir `backend/tests/unit/` confirmed. No router registration. ✓
9. **Frontend data plumbing:** N/A — no frontend.
10. **Persistence scope:** N/A — no storage.
11. **Enumerated value contract audit:** N/A — no filters/badges/dropdowns.
12. **Admin control / ceiling:** N/A — pre-MVP4, no admin model.
13. **Audit-event coverage:** N/A — no state mutation; `audit_log` not yet shipped (MVP3) and a pool-close emits nothing regardless.

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR (FR-1..FR-4) mapped to stories/tasks/tests.
- [x] Each story includes Modified files, Tasks, DoD (Endpoints/Schemas N/A and marked so).
- [x] Test layers scoped (unit only; integration/contract/e2e marked N/A with reasons).
- [x] Documentation updates planned (state.md/state_history.md at finalization; no topical-doc changes).
- [x] Lean refactor scope + guardrails explicit.
- [x] Epic gate measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed, no unresolved findings.
