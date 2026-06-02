# Feature Specification — Baseline-phase unit tests depend on suite ordering

**Date:** 2026-06-02
**Status:** Approved
**Owners:** Eric Starr (Product + Engineering)
**Related docs:**
- [idea.md](idea.md)
- [implementation_plan.md](implementation_plan.md)
- [docs/05_quality/testing.md](../../../../05_quality/testing.md) — test-layer convention + hermeticity rule
- [CLAUDE.md §"Bug Fix Protocol"](../../../../../CLAUDE.md)

---

## 1) Purpose

- **Problem:** `backend/tests/unit/workers/test_orchestrator_baseline_phase.py::TestComputeBaselineWaitS` (3 of its 4 cases) passes in the full `backend/tests/unit/` run but **fails in isolation** with a pydantic `ValidationError` (`database_url_file`/`postgres_password_file` Field required). The tests free-ride on a process-wide `os.environ` side effect leaked by an unrelated test module (`test_main_lifespan.py`) that happens to be collected earlier. A unit test that only passes via suite-ordering is a latent flake.
- **Outcome:** The three `TestComputeBaselineWaitS` cases pass standalone — `.venv/bin/python -m pytest backend/tests/unit/workers/test_orchestrator_baseline_phase.py -p no:randomly` is all-green with no reliance on any other test module having run first — while the full unit suite stays green. The fix removes the eager `get_settings()` read in `_compute_baseline_wait_s` (the latent fragility) **and** adds a hermetic autouse env fixture to the test module (belt-and-suspenders).
- **Non-goal:** Fixing the upstream `os.environ.setdefault` leak in `test_main_lifespan.py` (a separate, deliberate test-hygiene change — see §3 Out of scope). Changing the FR-2 wait-time formula or any runtime behavior of the baseline phase.

## 2) Current state audit

### Existing implementations

- **`backend/workers/orchestrator.py:467-474`** — `_compute_baseline_wait_s(study: Study) -> float`. Implements the FR-2 step-5 formula `min(600, max(60, trial_timeout_s + 30))`. **Line 469** reads `settings = get_settings()` **unconditionally**; line 470 then computes `trial_timeout_s = study.config.get("trial_timeout_s") or settings.studies_default_timeout_s`. The settings read is only needed when `study.config` lacks `trial_timeout_s`, but it runs every call. Module constants `_BASELINE_WAIT_CEILING_S` (600), `_BASELINE_WAIT_FLOOR_S` (60), `_BASELINE_WAIT_MARGIN_S` (30) are used in the formula. — No surprises beyond the eager read.
- **`backend/tests/unit/workers/test_orchestrator_baseline_phase.py`** — Unit tests for the FR-2 helpers. `TestComputeBaselineWaitS` (lines 66-89) has 4 cases: three pass an explicit `config={"trial_timeout_s": N}` (floor-at-60, +30, cap-at-600); the fourth, `test_missing_trial_timeout_uses_settings_default` (lines 82-89), passes `config={}` and `monkeypatch.setattr(orch, "get_settings", lambda: fake_settings)`. The module has **no autouse fixture** seeding the required-secret env vars.
- **`backend/app/core/settings.py:418-425`** — `get_settings()` is `lru_cache`'d and returns `Settings()`. `Settings` (`model_config` at line 83-84, `env_file=None`) requires `database_url_file` + `postgres_password_file` (`@cached_property` accessors at ~line 364). Construction raises pydantic `ValidationError` when those env vars are absent.
- **`backend/tests/conftest.py:39-51`** — autouse `_clear_settings_caches` fixture clears the `get_settings`/`get_engine`/`get_session_factory` lru_caches before every test. It does **NOT** set or unset any `os.environ` entries.
- **`backend/tests/unit/test_main_lifespan.py:38-46`** — at **module level** (collection time) creates `tempfile.mkdtemp()` stub files and calls `os.environ.setdefault("DATABASE_URL_FILE", ...)` + `os.environ.setdefault("POSTGRES_PASSWORD_FILE", ...)`. Uses raw `os.environ.setdefault` (never reverted) — leaks the two vars process-wide. The module comment (lines 32-37) incorrectly claims the stubs "only apply during this module's collection / first call."
- **`backend/tests/unit/workers/test_poll_cron_kwargs.py:34-55`** — `_settings_env_and_restore`, the **canonical precedent** autouse fixture: `monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")` + `monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")` + `get_settings.cache_clear()`, with a teardown that clears the cache again. This is the pattern the fix mirrors.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| N/A — no UI, no routes, no URLs | — | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/workers/test_orchestrator_baseline_phase.py` | `TestComputeBaselineWaitS` cases + module import graph | 4 cases | Add autouse env fixture; add 1 regression assertion that `_compute_baseline_wait_s` with an explicit `trial_timeout_s` does NOT call `get_settings()`. |

### Existing behaviors affected by scope change

- **`_compute_baseline_wait_s` settings read:** Current: reads `get_settings()` on every call. New: reads `get_settings()` only when `study.config["trial_timeout_s"]` is absent/falsy. Decision needed: **no** — the returned value is identical for every input (the `or` short-circuit already meant the settings value was discarded whenever `trial_timeout_s` was truthy). The deliberate behavior delta is that the explicit-timeout path no longer constructs `Settings` and therefore can no longer raise a `Settings` `ValidationError` — which is exactly the defect being removed.

---

## 3) Scope

### In scope

- Make `_compute_baseline_wait_s` (`backend/workers/orchestrator.py`) read `get_settings()` lazily — only inside the missing-`trial_timeout_s` branch.
- Add an autouse env fixture to `test_orchestrator_baseline_phase.py` mirroring `test_poll_cron_kwargs.py::_settings_env_and_restore` (seed `*_FILE` env + `get_settings.cache_clear()`), so the module is hermetic regardless of collection order.
- Add a regression test asserting `_compute_baseline_wait_s` does not construct `Settings()` when an explicit `trial_timeout_s` is supplied (the test that would have caught the production-side defect), plus confirmation the module's existing `TestComputeBaselineWaitS` cases pass standalone.

### Out of scope

- Fixing `test_main_lifespan.py:45-46`'s `os.environ.setdefault` leak. Switching it to `monkeypatch.setenv` (or a session fixture) is a deliberate change in an unrelated app-startup-lifespan test module that could retroactively break any *other* module silently free-riding on the same leak — it must be handled as its own change, not as a drive-by. If warranted, file a separate `chore_` idea.
- Any change to the FR-2 wait formula, the baseline phase orchestration, the resolver, or the resume path.
- Any new endpoint, migration, schema change, or frontend work.

### API convention check

N/A — this is a worker-helper + test change. No HTTP endpoints, no routers, no error envelopes are added or modified.

### Phase boundaries (if multi-phase)

Single-phase. No deferred phases; no `phase<N>_idea.md` required.

## 4) Product principles and constraints

- **Unit tests MUST be hermetic** (per [docs/05_quality/testing.md](../../../../05_quality/testing.md): "No DB fixtures; `monkeypatch` for env / module-level state"). A unit test must not depend on another module's import-time side effect.
- **CLAUDE.md Bug Fix Protocol:** reproduce first (done — see §2/§7), trace to root cause (done — two cooperating defects), fix at the right layer (production lazy-read + test-module fixture), add a regression test that fails without the fix.
- **CLAUDE.md Rule #2 / settings-via-files:** the fixture seeds `*_FILE` env vars pointing at `/dev/null` (matching the precedent); the `@cached_property` secret accessors are never invoked by these tests, so no real secret content is read.
- **No change to returned values:** the production edit preserves the wait-time formula and the exact return value for every input the function returns today. It does, however, deliberately change *side-effect timing* on the explicit-`trial_timeout_s` path: `get_settings()` (and thus `Settings` construction + its possible `ValidationError`) is no longer invoked there. That side-effect removal is the intended fix, not an incidental refactor — the explicit-timeout path no longer depends on a constructible `Settings`.

### Anti-patterns

- **Do not** "fix" this by adding `os.environ` writes or relying on `test_main_lifespan.py` running first — that perpetuates the suite-ordering coupling.
- **Do not** delete the eager `get_settings()` read and leave `studies_default_timeout_s` unreferenced — the fallback path (no `trial_timeout_s` in config) still legitimately needs it; only make the read conditional.
- **Do not** mark these tests `@pytest.mark.integration` or skip them — they are pure unit tests (no DB, no network) and must stay in the unit layer.
- **Do not** add a session-scoped or conftest-level env seed that hides the coupling for the whole unit suite — the fix belongs in the test module that has the defect, mirroring the per-module precedent.
- **Do not** touch `test_main_lifespan.py` in this change (see §3 Out of scope).

## 5) Assumptions and dependencies

- Dependency: none external. The fix is self-contained in two files.
  - Why required: —
  - Status: implemented (precedent fixture exists)
  - Risk if missing: —
- Assumption: `pytest-randomly` (or any future re-sharding) could reorder collection at any time; the fix must not assume `test_main_lifespan.py` precedes `workers/`. Verified the failure reproduces deterministically under `-p no:randomly` in isolation.

## 6) Actors and roles

- Primary actor(s): developers / CI running the unit-test suite (no end-user actor).
- Role model: N/A — single-tenant install, no auth surface.
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — no state mutation. `_compute_baseline_wait_s` is a pure function; the change is test hygiene + a lazy read. No `audit_log` row is created or affected.

## 7) Functional requirements

### FR-1: Lazy settings read in `_compute_baseline_wait_s`
- Requirement:
  - The system **MUST** read `get_settings()` inside `_compute_baseline_wait_s` only when `study.config` does not provide a truthy `trial_timeout_s`.
  - When `study.config["trial_timeout_s"]` is present and truthy, `_compute_baseline_wait_s` **MUST NOT** construct a `Settings` instance (i.e. **MUST NOT** call `get_settings()`).
  - The function **MUST** return the identical value for every input it returns today: `min(600, max(60, float(timeout) + 30))`.
- Notes: This is the production-side root cause. The existing `or` short-circuit already discarded `settings.studies_default_timeout_s` whenever `trial_timeout_s` was truthy; making the read lazy preserves the contract and removes the import-graph coupling for the explicit-timeout callers.

### FR-2: Hermetic test module
- Requirement:
  - `test_orchestrator_baseline_phase.py` **MUST** declare an autouse fixture that seeds `DATABASE_URL_FILE` + `POSTGRES_PASSWORD_FILE` (via `monkeypatch.setenv`, values `/dev/null`) and calls `get_settings.cache_clear()` before each test, clearing the cache again on teardown — mirroring `backend/tests/unit/workers/test_poll_cron_kwargs.py:34-55`.
  - The fixture **MUST** call `cache_clear()` on the canonical `get_settings` imported directly from `backend.app.core.settings` (e.g. `from backend.app.core.settings import get_settings` aliased at the top of the test module), **NOT** on `orch.get_settings`. Rationale: `test_missing_trial_timeout_uses_settings_default` does `monkeypatch.setattr(orch, "get_settings", lambda: fake_settings)` — a plain `lambda` has no `.cache_clear()` attribute. If the fixture resolved `orch.get_settings` at teardown it would raise `AttributeError` after that test monkeypatched the reference. The precedent fixture already imports `get_settings` from the settings module for exactly this reason.
  - The module's `TestComputeBaselineWaitS` cases **MUST** pass when run in isolation: `.venv/bin/python -m pytest backend/tests/unit/workers/test_orchestrator_baseline_phase.py -p no:randomly` is all-green with no other test module collected first.
- Notes: Belt-and-suspenders alongside FR-1. Even after FR-1 makes the three explicit-timeout cases settings-free, `test_missing_trial_timeout_uses_settings_default` and any future settings-dependent test in the module need the env present; the fixture guarantees module-level hermeticity.

### FR-3: Regression coverage
- Requirement:
  - The system **MUST** include a test that fails on the pre-fix code and passes post-fix, asserting `_compute_baseline_wait_s` does not call `get_settings()` (or construct `Settings`) when an explicit `trial_timeout_s` is supplied.
  - The full `backend/tests/unit/` suite **MUST** remain green.
- Notes: Per Bug Fix Protocol step 4. The regression test isolates the production-side defect (eager settings read) independent of the env-leak trigger, so it stays meaningful even if `test_main_lifespan.py`'s leak is later removed.

## 8) API and data contract baseline

### 7.1 Endpoint surface (if applicable)

N/A — no endpoints.

### 7.2 Contract rules

N/A — no API surface.

### 7.3 Response examples

N/A — no API surface.

### 7.4 Enumerated value contracts

N/A — no filters, status badges, sort keys, dropdowns, or backend allowlists touched.

### 7.5 Error code catalog

N/A — no error codes introduced.

## 9) Data model and state transitions

### New/changed entities

None. No tables, columns, or migrations.

### Required invariants

- `_compute_baseline_wait_s(study)` returns `min(600, max(60, float(trial_timeout_s) + 30))` for every input, where `trial_timeout_s` is `study.config["trial_timeout_s"]` when truthy, else `settings.studies_default_timeout_s`. This invariant is unchanged by the fix.

### State transitions

N/A — pure function, no state.

### Idempotency/replay behavior

N/A.

## 10) Security, privacy, and compliance

- Threats: none introduced. The fixture seeds `*_FILE` env vars at `/dev/null` (no real secret content read), matching the established precedent.
- Controls: N/A.
- Secrets/key handling: the fixture never reads secret file *content* — the `@cached_property` accessors are not invoked by these tests; only the env-var presence matters for `Settings` construction.
- Auditability: N/A — no state mutation.
- Data retention/deletion/export impact: none.

## 11) UX flows and edge cases

N/A — no UI. No information architecture, tooltips, or user-facing flows.

### Edge/error flows

- **Collection reordering** (`pytest-randomly`, re-sharding, `pytest <single-file>`): post-fix, the module is hermetic, so the three cases pass regardless of which module collects first or whether any other module runs at all.
- **Missing `trial_timeout_s` path:** `test_missing_trial_timeout_uses_settings_default` still monkeypatches `orch.get_settings` to a fake; the autouse fixture additionally guarantees a constructible `Settings` if any future case relies on the real one.

## 12) Given/When/Then acceptance criteria

### AC-1: Explicit-timeout cases pass in isolation
- Given a clean shell with `DATABASE_URL_FILE`/`POSTGRES_PASSWORD_FILE` **unset**
- When running `.venv/bin/python -m pytest backend/tests/unit/workers/test_orchestrator_baseline_phase.py -p no:randomly`
- Then all tests pass (no `ValidationError`).
- Example values:
  - Pre-fix: `3 failed, 1 passed` (the floor-at-60, +30, cap-at-600 cases fail).
  - Post-fix: all pass.

### AC-2: `_compute_baseline_wait_s` does not read settings for explicit timeouts
- Given a `study` with `config={"trial_timeout_s": 60}`
- When `_compute_baseline_wait_s(study)` is called with `get_settings` patched to a spy that raises if invoked
- Then the spy is never called AND the return value is `90.0`.
- Example values:
  - Input: `config={"trial_timeout_s": 60}`
  - Expected: `90.0`, `get_settings` call count `0`.

### AC-3: Settings fallback still works for missing timeout
- Given a `study` with `config={}` and `studies_default_timeout_s=45`
- When `_compute_baseline_wait_s(study)` is called
- Then the return value is `75.0` (`max(60, 45+30)`).
- Example values:
  - Input: `config={}`, `studies_default_timeout_s=45`
  - Expected: `75.0`.

### AC-4: Full unit suite stays green
- Given the complete `backend/tests/unit/` tree
- When running `make test-unit`
- Then the suite passes with no new failures and coverage stays ≥ 80%.

## 13) Non-functional requirements

- Performance: negligible — one fewer `Settings()` construction per `_compute_baseline_wait_s` call on the explicit-timeout path.
- Reliability: removes a latent flake (suite-ordering dependency); improves test determinism.
- Operability: no logging/metrics/alert changes.
- Accessibility/usability: N/A.

## 14) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/`):
  - Autouse env fixture in `test_orchestrator_baseline_phase.py` (FR-2).
  - Regression test asserting no `get_settings()` call on the explicit-timeout path (FR-3 / AC-2).
  - Existing `TestComputeBaselineWaitS` cases must pass standalone (AC-1) and the settings-fallback case must still pass (AC-3).
- Integration tests: N/A — no DB/workflow change. (Real-backend baseline coverage lives in `backend/tests/integration/test_orchestrator_baseline_trial.py` and is unaffected.)
- Contract tests: N/A — no API surface.
- E2E tests: N/A — no UI.

## 15) Documentation update requirements

- `docs/01_architecture`: none.
- `docs/02_product`: none.
- `docs/03_runbooks`: none.
- `docs/04_security`: none.
- `docs/05_quality`: optional — the hermeticity rule already exists in `testing.md`; no edit required. (A one-line note that `os.environ.setdefault` at module level leaks process-wide could be added but is out of scope here.)

## 16) Rollout and migration readiness

- Feature flags / staged rollout: N/A.
- Migration/backfill expectations: none — no schema change.
- Operational readiness gates: none.
- Release gate: `make test-unit` green standalone for the target module AND for the full suite; `make lint` + `make typecheck` green.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-2, AC-3 | Story 1.1 | `backend/tests/unit/workers/test_orchestrator_baseline_phase.py` | none |
| FR-2 | AC-1 | Story 1.2 | `backend/tests/unit/workers/test_orchestrator_baseline_phase.py` | none |
| FR-3 | AC-2, AC-4 | Story 1.2 | `backend/tests/unit/workers/test_orchestrator_baseline_phase.py` | none |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-4) pass in CI.
- [ ] `TestComputeBaselineWaitS` passes when run in isolation (`-p no:randomly`, target module only, `*_FILE` env unset in the shell).
- [ ] The full `backend/tests/unit/` suite is green; coverage ≥ 80%.
- [ ] `make lint` + `make typecheck` pass.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all decisions locked.

### Decision log
- 2026-06-02 — **Fix both layers, not just the test fixture.** The eager `get_settings()` read in `_compute_baseline_wait_s` (orchestrator.py:469) is the durable defect; the autouse fixture is belt-and-suspenders. Rationale: a test-only fixture would mask the production fragility (the helper reads settings it doesn't need); the lazy read removes the coupling at the source per Bug Fix Protocol "fix at the right layer."
- 2026-06-02 — **Do not touch `test_main_lifespan.py`'s `os.environ.setdefault` leak in this change.** Rationale: it's the upstream trigger but lives in an unrelated lifespan-test module; swapping `setdefault`→`monkeypatch.setenv` could retroactively break other modules silently free-riding on the same leak, so it must be a deliberate separate change, not a drive-by. The correct minimal fix for *this* bug is to make the baseline-wait tests hermetic.
- 2026-06-02 — **Mirror `test_poll_cron_kwargs.py:34-55` for the fixture, not the (nonexistent) `test_register_webhook_worker.py::_relyloop_base_url`.** Rationale: the latter was a stale reference corrected during idea-preflight; `_settings_env_and_restore` is the live canonical precedent.

---

## Cross-model review log (GPT-5.5)

Reviewer: GPT-5.5 (`gpt-5.5` via OpenAI Chat Completions, `max_completion_tokens`). API call succeeded; cross-model review performed (not skipped).

**Cycle 1** — 2 findings (0 High, 0 Medium, 2 Low). Both accepted.

| # | Pass | Severity | Finding | Adjudication |
|---|---|---|---|---|
| 1 | A | Low | "No behavior change at runtime / pure refactor" overstates the change — the lazy read intentionally changes side-effect/exception timing (no `Settings` `ValidationError` on the explicit-timeout path). | **Accept.** Correct — that side-effect removal is the point of the fix. Reworded §2 "Existing behaviors affected" and §4 "No change to returned values" to qualify the claim and call the side-effect delta out as intended. |
| 2 | B | Low | The autouse fixture must call `cache_clear()` on the canonical `get_settings` imported from `backend.app.core.settings`, not on `orch.get_settings` — because `test_missing_trial_timeout_uses_settings_default` monkeypatches `orch.get_settings` to a `lambda` (no `.cache_clear()`), so a teardown resolving `orch.get_settings` would raise `AttributeError`. | **Accept.** Verified: `test_orchestrator_baseline_phase.py:86` does `monkeypatch.setattr(orch, "get_settings", lambda: fake_settings)`; the precedent `test_poll_cron_kwargs.py` imports `get_settings` from the settings module directly. Added an explicit MUST clause to FR-2. |

**Cycle 2** — re-review of the patched spec with the cycle-1 rejection/accept log in the system prompt. Result: `{"findings": []}` (0 findings). **Convergence reached.**

**Convergence:** cycle 2 returned no new High/Medium (or any) findings. Both cycle-1 findings were Low (no contract/data/AC change), so no Major findings gate applied; corrections applied directly. Total: 2 cycles, 2 findings (0 High, 0 Medium, 2 Low), 2 accepted / 0 rejected / 0 deferred.
