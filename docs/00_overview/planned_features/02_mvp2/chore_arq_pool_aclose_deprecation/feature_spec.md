# Feature Specification — Replace deprecated `arq_pool.close()` with `aclose()`

**Date:** 2026-06-01
**Status:** Draft
**Owners:** RelyLoop maintainers (soundminds.ai)
**Related docs:**
- [`idea.md`](idea.md)
- [`implementation_plan.md`](implementation_plan.md) (to be generated)
- [`docs/01_architecture/system-overview.md`](../../../../01_architecture/system-overview.md) (API + worker lifecycle)

---

## 1) Purpose

The Arq Redis pool is closed via the deprecated sync-named `ArqRedis.close()` on two shutdown paths. arq deprecated `close()` in favor of the `aclose()` coroutine; the `DeprecationWarning` fires on every API and worker shutdown and floods integration-test teardown logs.

- **Problem:** `backend/app/main.py:144` (FastAPI lifespan `finally`) and `backend/workers/all.py:225` (Arq worker `on_shutdown` hook) both call `await arq_pool.close()`, emitting a `DeprecationWarning` on every shutdown. When arq removes `close()` in a future release, both shutdown paths will raise.
- **Outcome:** Both call sites use `await arq_pool.aclose()`; no `DeprecationWarning` on shutdown; a regression guard asserts the async-correct form on both paths so a future edit cannot silently reintroduce `close()`.
- **Non-goal:** No behavior change, no new dependency, no upgrade of the pinned arq version, no refactor of pool construction or the worker/API lifecycle structure. This is a mechanical deprecation fix only.

## 2) Current state audit

### Existing implementations

- `backend/app/main.py:127-146` — FastAPI lifespan. Builds the Arq pool via `await create_pool(RedisSettings.from_dsn(settings.redis_url))` (line 131), stashes it on `_app.state.arq_pool` (line 132), and in the `finally` block calls `await arq_pool.close()` (line 144) wrapped in a best-effort try/except that swallows + WARN-logs any raise. The sibling raw Redis client on line 177 already uses the correct `await redis_client.aclose()`.
- `backend/workers/all.py:116-126, 212-225` — Arq `WorkerSettings.on_startup` builds a shared pool (`await create_pool(...)`, line 125) cached in `ctx["arq_pool"]`. `on_shutdown(ctx)` (defined at line 212) disposes the Optuna engine and then calls `await arq_pool.close()` (line 225) on the pool fetched from `ctx`. `on_shutdown` is bound onto `WorkerSettings` at line 270.
- **arq version:** `0.28.0` (verified in `uv.lock:55`; constraint `arq>=0.26` in `pyproject.toml`, surfaced at `uv.lock:1689`). arq is pre-1.0. Verified 2026-06-01 via `python -c "import arq.connections; ..."`: `arq.connections.ArqRedis` exposes **both** `close` and `aclose`; `aclose()` is the non-deprecated coroutine. `ArqRedis` subclasses `redis.asyncio.Redis`, whose `aclose()` is the canonical async close. The `await arq_pool.aclose()` form is valid on the installed version.

No other arq/Redis **pool** `.close()` call sites exist. Preflight (2026-06-01) swept `backend/app/` and `backend/workers/`: every other shutdown call is already async-correct or out of scope — `redis_client.aclose()` (`main.py:177`, `seed_clusters.py:98`, `demo_reseed.py:254`), `adapter.aclose()` (elastic/solr adapters, cluster service, trial/baseline workers), and `openai_client.close()` (chat/digest/judgment workers — a different SDK's client, out of scope for this chore).

### Navigation and link impact

N/A — no UI, no URLs.

| Source file | Current link target | New link target |
|---|---|---|
| N/A | N/A | N/A |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/test_main_lifespan.py` | `fake_pool.close = AsyncMock(return_value=None)` (line 86) | 1 | Flip the stub to `fake_pool.aclose = AsyncMock(...)`. `fake_pool` is a bare `MagicMock` (line 85); after the fix the lifespan awaits `fake_pool.aclose()`, and a bare MagicMock attribute returns a non-awaitable MagicMock — awaiting it raises `TypeError`. Add an assertion that `fake_pool.aclose` was awaited once and `fake_pool.close` was never called. |
| `backend/tests/unit/test_workers.py` | Asserts `on_startup` exists/callable (lines 109-111); does **not** exercise `on_shutdown` | 0 existing | Add a new test that invokes `on_shutdown(ctx)` with a fake pool + asserts `aclose` was awaited and `close` was not. No prior coverage on the worker shutdown path. |

### Existing behaviors affected by scope change

- **API shutdown pool close:** Current: `await arq_pool.close()` (deprecated; emits `DeprecationWarning`). New: `await arq_pool.aclose()` (no warning; identical close semantics). Decision needed: no.
- **Worker shutdown pool close:** Current: `await arq_pool.close()` (deprecated). New: `await arq_pool.aclose()`. Decision needed: no.

---

## 3) Scope

### In scope

- Replace `await arq_pool.close()` with `await arq_pool.aclose()` at `backend/app/main.py:144`.
- Replace `await arq_pool.close()` with `await arq_pool.aclose()` at `backend/workers/all.py:225`.
- Update `backend/tests/unit/test_main_lifespan.py` to stub + assert `aclose` (not `close`).
- Add a `backend/tests/unit/test_workers.py` regression test asserting the worker `on_shutdown` awaits `aclose`, not `close`.

### Out of scope

- Upgrading the pinned arq version.
- Adding a project-wide `filterwarnings = error` pytest config (would convert all `DeprecationWarning`s into failures — a broader, separate decision; see §19 Decision log).
- Refactoring pool construction, lifespan structure, or the worker `WorkerSettings` shape.
- Any change to `openai_client.close()`, `adapter.aclose()`, or raw `redis_client.aclose()` call sites (all out of scope; first is a different SDK, the latter two are already correct).

### API convention check

N/A — this chore adds no endpoints and changes no API surface. (Conventions per [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) are unaffected.)

### Phase boundaries (if multi-phase)

Single-phase. No deferred phases, no `phase<N>_idea.md` tracking required.

## 4) Product principles and constraints

- **Pure maintenance, zero behavior change.** The shutdown semantics of `close()` and `aclose()` are identical on the installed arq version (both flush + close the underlying Redis connection pool); only the deprecation status differs.
- **Honor CLAUDE.md Absolute Rules.** No migration (Rule #5 N/A), no secrets (Rule #2 N/A), no LLM call (Rules #3/#8 N/A), no engine-adapter bypass (Rule #4 N/A), no `/healthz` change (Rules #6/#11 N/A). Conventional Commits + DCO sign-off (Rule #7) apply to the commit.
- **Match the same-file precedent.** `main.py:177` already uses `await redis_client.aclose()`; the fix makes the arq pool close consistent with it.

### Anti-patterns

- **Do not** add `filterwarnings = error` (or an arq-specific warning filter) to `pyproject.toml` to "prove" the fix — that converts every `DeprecationWarning` repo-wide into a test failure, a much larger blast radius than this chore. The regression guard must assert the call shape directly (`aclose` awaited, `close` not called), not assert warning-absence.
- **Do not** wrap the new `aclose()` in additional defensive try/except beyond what already exists. `main.py:144` is already inside a best-effort try/except; `all.py:225` runs inside `on_shutdown` which arq tolerates raising. Keep the existing structure.
- **Do not** "while I'm here" refactor pool construction, swap `create_pool` ergonomics, or touch unrelated shutdown calls. Scope is exactly two call-site edits + their tests.
- **Do not** bump the arq pin or add `aclose` shims — `aclose()` already exists on the installed `arq==0.28.0`.

## 5) Assumptions and dependencies

- **Dependency:** `arq==0.28.0` (pinned in `uv.lock`).
  - Why required: provides `ArqRedis.aclose()`.
  - Status: implemented (installed; verified to expose `aclose`).
  - Risk if missing: none on the current pin. If arq were downgraded below the version that introduced `aclose()`, the call would `AttributeError`. The pin constraint `>=0.26` is the floor; `aclose()` is present at 0.28.0. Implementation should confirm `aclose` exists on the resolved version before merge (it does today).

## 6) Actors and roles

- Primary actor(s): system (FastAPI app shutdown; Arq worker shutdown). No human actor.
- Role model: N/A — single-tenant install, no auth surface.
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — pure process-lifecycle cleanup. No tenant-visible state mutation, no DB write, no `audit_log` row. (`audit_log` itself is not yet shipped; arrives at MVP3 per [`docs/01_architecture/data-model.md`](../../../../01_architecture/data-model.md). Even once it lands, a pool-close is not a state mutation and emits nothing.)

## 7) Functional requirements

### FR-1: API lifespan closes the Arq pool with `aclose()`
- Requirement:
  - The system **MUST** call `await arq_pool.aclose()` (not `arq_pool.close()`) in the FastAPI lifespan `finally` block at `backend/app/main.py` when an Arq pool was constructed.
  - The system **MUST** retain the existing best-effort try/except that swallows + WARN-logs any raise from the close call (no behavior change to error handling).
- Notes: `arq_pool` is `None` when pool construction failed at startup; the existing `if arq_pool is not None:` guard (line 142) is unchanged.

### FR-2: Worker `on_shutdown` closes the Arq pool with `aclose()`
- Requirement:
  - The system **MUST** call `await arq_pool.aclose()` (not `arq_pool.close()`) in the Arq worker `on_shutdown` hook at `backend/workers/all.py` when `ctx["arq_pool"]` is present.
  - The system **MUST** retain the existing `if arq_pool is not None:` guard (line 224) and the preceding Optuna-engine disposal (unchanged).
- Notes: the pool is fetched via `ctx.get("arq_pool")`; the guard handles the missing-pool case.

### FR-3: No deprecation warning on shutdown
- Requirement:
  - The system **MUST NOT** emit the arq `close()`-deprecation `DeprecationWarning` from either shutdown path after the fix.
- Notes: verified indirectly via the regression tests in FR-4 (asserting `aclose` is the awaited method), not via a global warning filter (see §3 Out of scope and §4 Anti-patterns).

### FR-4: Regression guards on both shutdown paths
- Requirement:
  - The system **MUST** assert, in `backend/tests/unit/test_main_lifespan.py`, that the lifespan awaits `arq_pool.aclose()` exactly once and never calls `arq_pool.close()`.
  - The system **MUST** add a test in `backend/tests/unit/test_workers.py` asserting the worker `on_shutdown(ctx)` awaits `arq_pool.aclose()` and never calls `close()`.
- Notes: `on_shutdown` has no existing unit coverage (`test_workers.py` only checks `on_startup` exists/callable); this FR establishes the first coverage on the worker shutdown path.

## 8) API and data contract baseline

### 7.1 Endpoint surface

N/A — no endpoints added or changed.

### 7.2 Contract rules

N/A — no API contract.

### 7.3 Response examples

N/A — no API response.

### 7.4 Enumerated value contracts

N/A — no filters, status badges, sort keys, or dropdowns.

### 7.5 Error code catalog

N/A — no new error codes.

## 9) Data model and state transitions

### New/changed entities

N/A — no schema change, no migration. Alembic head stays `0022_solr_engine_auth_check`.

### Required invariants

- After the fix, the only `ArqRedis`/pool close call across `backend/app/` and `backend/workers/` must be `aclose()` — no `arq_pool.close()` remains. (Enforced by the two regression tests; the implementation plan may optionally add a grep-style guard, but the two behavior assertions are the required mechanism.)

### State transitions

N/A.

### Idempotency/replay behavior

N/A.

## 10) Security, privacy, and compliance

- Threats: none introduced. A pool close touches no secret, no PII, no external surface.
- Controls: N/A.
- Secrets/key handling: unchanged — `settings.redis_url` is read as before (the existing non-secret config path).
- Auditability: N/A.
- Data retention/deletion/export impact: none.

## 11) UX flows and edge cases

### Information architecture

N/A — no UI.

### Tooltips and contextual help

N/A — no UI element.

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| N/A | N/A | N/A | N/A |

### Primary flows

1. **API shutdown:** FastAPI receives shutdown signal → lifespan `finally` runs → if a pool exists, `await arq_pool.aclose()` → no warning → process exits.
2. **Worker shutdown:** Arq worker receives shutdown → `on_shutdown(ctx)` runs → Optuna engine disposed → if `ctx["arq_pool"]` exists, `await arq_pool.aclose()` → no warning → process exits.

### Edge/error flows

- **Pool never constructed (API):** `arq_pool is None` (startup pool-build failed and WARN-logged); the `if arq_pool is not None:` guard skips the close. Unchanged.
- **Pool missing in worker ctx:** `ctx.get("arq_pool")` returns `None`; the guard skips the close. Unchanged.
- **`aclose()` raises (API):** existing best-effort try/except swallows + WARN-logs ("arq pool close raised during shutdown"). Unchanged.

## 12) Given/When/Then acceptance criteria

### AC-1: API lifespan awaits `aclose`, not `close`
- Given the FastAPI app started and built an Arq pool stashed on `app.state.arq_pool`
- When the lifespan shutdown (`finally`) runs
- Then `arq_pool.aclose()` is awaited exactly once and `arq_pool.close()` is never called
- Example values:
  - Input: a `fake_pool = MagicMock()` with `fake_pool.aclose = AsyncMock(return_value=None)` injected as the created pool
  - Expected: `fake_pool.aclose.assert_awaited_once()`; `fake_pool.close.assert_not_called()`

### AC-2: Worker `on_shutdown` awaits `aclose`, not `close`
- Given a worker `ctx` containing `arq_pool` (a fake pool) and an `optuna_storage`
- When `on_shutdown(ctx)` is awaited
- Then `arq_pool.aclose()` is awaited and `arq_pool.close()` is never called
- Example values:
  - Input: `ctx = {"arq_pool": fake_pool, "optuna_storage": fake_storage}` where `fake_pool.aclose = AsyncMock(...)`
  - Expected: `fake_pool.aclose.assert_awaited_once()`; `fake_pool.close.assert_not_called()`

### AC-3: No arq close-deprecation warning on shutdown
- Given the existing test suite runs the lifespan + worker shutdown paths
- When those paths execute against the real (or faithfully stubbed) `ArqRedis`
- Then no `DeprecationWarning` mentioning `close()`/`aclose` is emitted from the arq pool close
- Note: validated structurally via AC-1/AC-2 (the deprecated method is never called); the suite does not flip on a global `filterwarnings = error` to assert this.

### AC-4: Pool-absent paths remain no-ops
- Given no Arq pool was constructed (`arq_pool is None` / absent from worker ctx)
- When shutdown runs
- Then neither `close()` nor `aclose()` is called and no exception is raised

## 13) Non-functional requirements

- Performance: no measurable change (one method-name swap on a shutdown path).
- Reliability: slightly improved — removes a future break risk when arq removes `close()`. No SLO impact.
- Operability: cleaner shutdown logs (no `DeprecationWarning` line on every API/worker stop; cleaner integration-test teardown output).
- Accessibility/usability: N/A (no UI).

## 14) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/`):
  - `test_main_lifespan.py` — update the existing test to stub `aclose` and assert `aclose` awaited once + `close` not called (AC-1, AC-4).
  - `test_workers.py` — new test invoking `on_shutdown(ctx)` asserting `aclose` awaited + `close` not called, plus a pool-absent no-op case (AC-2, AC-4).
- Integration tests (`backend/tests/integration/`): none required — the change has no DB/workflow surface; the unit tests cover both shutdown paths. (`main.py` is excluded from coverage measurement per `pyproject.toml:237`, so the lifespan unit test is the guard, not a coverage number.)
- Contract tests (`backend/tests/contract/`): N/A — no API contract.
- E2E tests (`ui/tests/e2e/`): N/A — no UI.

## 15) Documentation update requirements

- `docs/01_architecture`: none required (no architectural change; the lifecycle structure is unchanged).
- `docs/02_product`: none.
- `docs/03_runbooks`: none.
- `docs/04_security`: none.
- `docs/05_quality`: none.
- `state.md`: add the merge one-liner to "Last 5 merges" + full entry to `state_history.md` at finalization (per CLAUDE.md). No Alembic-head change.

## 16) Rollout and migration readiness

- Feature flags / staged rollout: none — single mechanical change, ships in one PR.
- Migration/backfill expectations: none — no schema change.
- Operational readiness gates: standard `pr.yml` CI green (lint, mypy, unit tests, coverage gate).
- Release gate: unit suite green (`make test-unit`), `make lint`, `make typecheck` clean.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-4 | Story 1.1 | `backend/tests/unit/test_main_lifespan.py` | none |
| FR-2 | AC-2, AC-4 | Story 1.2 | `backend/tests/unit/test_workers.py` | none |
| FR-3 | AC-3 | Stories 1.1, 1.2 | (validated via FR-4 tests) | none |
| FR-4 | AC-1, AC-2, AC-4 | Stories 1.1, 1.2 | `backend/tests/unit/test_main_lifespan.py`, `backend/tests/unit/test_workers.py` | none |

## 18) Definition of feature done

This feature is complete when:

- [ ] `backend/app/main.py:144` and `backend/workers/all.py:225` call `await arq_pool.aclose()`.
- [ ] No `arq_pool.close()` call remains in `backend/app/` or `backend/workers/`.
- [ ] AC-1 through AC-4 pass in CI.
- [ ] `test_main_lifespan.py` updated; new `test_workers.py` shutdown test added; both green.
- [ ] `make lint` + `make typecheck` + `make test-unit` clean.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- None. The change is fully specified.

### Decision log

- 2026-06-01 — **Two call sites, not one.** Preflight found a second deprecated `arq_pool.close()` at `backend/workers/all.py:225` (worker `on_shutdown`) in addition to the `main.py:144` site named in the idea. Both are in scope. Rationale: the idea explicitly directed sweeping for other pool `.close()` sites; fixing only one leaves the deprecation live on the worker path.
- 2026-06-01 — **Use `aclose()`, confirmed available.** `arq==0.28.0` `ArqRedis` exposes `aclose()` (verified at runtime). No version bump needed. Rationale: arq is pre-1.0 (the idea's original "≥5.0.1" was wrong; corrected during preflight).
- 2026-06-01 — **No global `filterwarnings = error`.** Rejected adding a pytest warning-error filter to enforce the fix. Rationale: it would turn every repo-wide `DeprecationWarning` into a failure (much larger blast radius); the regression is instead guarded by asserting the call shape (`aclose` awaited, `close` not called) on both paths.
- 2026-06-01 — **Add first worker-shutdown unit coverage.** `on_shutdown` had no test; FR-4 adds the first. Rationale: without it, a future edit reintroducing `close()` on the worker path is caught by nothing.
