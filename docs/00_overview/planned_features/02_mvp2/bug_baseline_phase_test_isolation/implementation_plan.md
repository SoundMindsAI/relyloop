# Implementation Plan — Baseline-phase unit tests depend on suite ordering

**Date:** 2026-06-02
**Status:** Ready for Execution
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [CLAUDE.md §"Bug Fix Protocol"](../../../../../CLAUDE.md), [docs/05_quality/testing.md](../../../../05_quality/testing.md)

---

## 0) Planning principles

- Spec traceability first: every task maps to FR-1/FR-2/FR-3.
- Fix at the right layer (production lazy-read + test-module fixture) per the Bug Fix Protocol.
- Regression test must fail on pre-fix code and pass post-fix.
- No runtime behavior change to returned values; only side-effect timing on the explicit-timeout path.
- This is a backend test-only + one-helper change: no migration, no API, no frontend, no `audit_log`.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.1 | Lazy `get_settings()` read in `_compute_baseline_wait_s`. |
| FR-2 | Epic 1 / Story 1.2 | Autouse env fixture in the test module; standalone-green requirement. |
| FR-3 | Epic 1 / Story 1.2 | Regression test (no `get_settings()` on explicit-timeout path) + full-suite green. |

No deferred phases. Single-phase, single-epic. No `phase<N>_idea.md` required.

## 2) Delivery structure

**Structure:** Epic → Story → Tasks → DoD. Two stories in one epic.

### Conventions (project-specific)

```
- Worker helpers live in backend/workers/orchestrator.py; domain-pure where possible.
- Settings are read via get_settings() (lru_cache'd) — never instantiate Settings() directly.
- Unit tests are hermetic: no DB, no network; use monkeypatch for env / module-level state
  (docs/05_quality/testing.md). Required-secret env vars seeded via monkeypatch.setenv at /dev/null.
- get_settings.cache_clear() must be called on the canonical symbol imported from
  backend.app.core.settings, never on a monkeypatched module attribute (e.g. orch.get_settings).
- Run targeted unit tests with .venv/bin/python -m pytest ... -p no:randomly.
- Commit with git commit -s (DCO). Conventional Commits.
```

### AI Agent Execution Protocol (applies to every story)

0. Load context: read `architecture.md` + `state.md`.
1. Read scope: story outcome + key interfaces + DoD.
2. Implement the production change (Story 1.1) first, then the test changes (Story 1.2).
3. Run targeted unit tests in isolation (`-p no:randomly`) AND the full `backend/tests/unit/` suite.
4. No frontend / no E2E (none in scope).
5. Run `make lint` + `make typecheck`.
6. Attach evidence in the PR: isolation run (pre-fix red → post-fix green), full-suite green.

---

## Epic 1 — Hermetic baseline-wait unit tests

**Gate:** `.venv/bin/python -m pytest backend/tests/unit/workers/test_orchestrator_baseline_phase.py -p no:randomly` is all-green with `DATABASE_URL_FILE`/`POSTGRES_PASSWORD_FILE` **unset** in the shell, AND `make test-unit` (full suite) stays green with coverage ≥ 80%, AND `make lint` + `make typecheck` pass.

### Story 1.1 — Lazy settings read in `_compute_baseline_wait_s` (FR-1)

**Outcome:** `_compute_baseline_wait_s` reads `get_settings()` only when `study.config` lacks a truthy `trial_timeout_s`. Explicit-timeout callers never construct `Settings`. Returned values are unchanged for every input.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/workers/orchestrator.py` | Restructure `_compute_baseline_wait_s` (lines 467-474) so `get_settings()` is invoked only inside the missing-`trial_timeout_s` branch. |

**Endpoints**

N/A — no API surface.

**Pydantic schemas**

N/A.

**Key interfaces**

Signature is unchanged:

```python
def _compute_baseline_wait_s(study: Study) -> float:
    """FR-2 step 5: ``min(600, max(60, trial_timeout_s + 30))``."""
```

Reference implementation shape (illustrative — implementer matches existing style/constants
`_BASELINE_WAIT_CEILING_S`=600, `_BASELINE_WAIT_FLOOR_S`=60, `_BASELINE_WAIT_MARGIN_S`=30):

```python
def _compute_baseline_wait_s(study: Study) -> float:
    """FR-2 step 5: ``min(600, max(60, trial_timeout_s + 30))``."""
    trial_timeout_s = study.config.get("trial_timeout_s")
    if not trial_timeout_s:
        # Fallback only when the study config omits an explicit timeout.
        trial_timeout_s = get_settings().studies_default_timeout_s
    return min(
        _BASELINE_WAIT_CEILING_S,
        max(_BASELINE_WAIT_FLOOR_S, float(trial_timeout_s) + _BASELINE_WAIT_MARGIN_S),
    )
```

Note: the `or`-vs-`if not` semantics are preserved — `study.config.get("trial_timeout_s") or settings.studies_default_timeout_s` falls back on any falsy value (None, 0, missing), and `if not trial_timeout_s` matches that exactly.

**Tasks**

1. Edit `_compute_baseline_wait_s` to defer the `get_settings()` call into the missing/falsy-`trial_timeout_s` branch, preserving the existing falsy-fallback semantics and the formula constants.
2. Confirm no other caller of `_compute_baseline_wait_s` relies on it always calling `get_settings()` (grep: only `backend/workers/orchestrator.py:419` calls it; it does not inspect settings side effects).

**Definition of Done**

- [ ] `_compute_baseline_wait_s` does not call `get_settings()` when `study.config["trial_timeout_s"]` is truthy (asserted by Story 1.2's regression test, AC-2).
- [ ] Return values unchanged: floor-at-60 (`{"trial_timeout_s": 5}` → 60.0), +30 (`{"trial_timeout_s": 60}` → 90.0), cap-at-600 (`{"trial_timeout_s": 1200}` → 600.0), settings-fallback (`{}` with `studies_default_timeout_s=45` → 75.0).
- [ ] `make typecheck` passes (mypy --strict).

### Story 1.2 — Hermetic test module + regression coverage (FR-2, FR-3)

**Outcome:** `test_orchestrator_baseline_phase.py` is hermetic regardless of collection order, and carries a regression test that fails on the pre-fix production code and passes post-fix.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/unit/workers/test_orchestrator_baseline_phase.py` | Add imports (`from collections.abc import Iterator`, `from backend.app.core.settings import get_settings`); add an autouse `_settings_env_and_restore` fixture mirroring `test_poll_cron_kwargs.py:34-55`; add a regression test asserting no `get_settings()` call on the explicit-timeout path. |

**Key interfaces**

Autouse fixture (mirror of `backend/tests/unit/workers/test_poll_cron_kwargs.py:34-55`):

```python
@pytest.fixture(autouse=True)
def _settings_env_and_restore(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Seed required-secret env vars + clear the settings lru_cache.

    Settings construction needs DATABASE_URL_FILE + POSTGRES_PASSWORD_FILE per
    CLAUDE.md Rule #2. Point both at /dev/null — the cached_property accessors
    aren't invoked here, so the empty file content is never read. Clears the
    cache on the canonical get_settings imported from backend.app.core.settings
    (NOT orch.get_settings, which test_missing_trial_timeout_uses_settings_default
    monkeypatches to a plain lambda with no .cache_clear()).
    """
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

Regression test (the test that would have caught the production-side defect, AC-2):

```python
def test_explicit_timeout_does_not_read_settings(
    self, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-1: an explicit trial_timeout_s must not construct Settings."""
    def _boom() -> Any:
        raise AssertionError("get_settings() must not be called for explicit timeout")

    monkeypatch.setattr(orch, "get_settings", _boom)
    study = _study(config={"trial_timeout_s": 60})
    assert _compute_baseline_wait_s(study) == 90.0
```

**Tasks**

1. Add `from collections.abc import Iterator` and `from backend.app.core.settings import get_settings` to the test module's imports (currently `get_settings` is only reachable via `orch.get_settings`). `Any` is already imported at `test_orchestrator_baseline_phase.py:22` (used by `_study`), so the regression test's `-> Any` annotation needs no new import.
2. Add the autouse `_settings_env_and_restore` fixture at module scope, above the test classes.
3. Add `test_explicit_timeout_does_not_read_settings` to the `TestComputeBaselineWaitS` class (spies on `orch.get_settings` so it fails if Story 1.1 hasn't deferred the read).
4. Confirm `test_missing_trial_timeout_uses_settings_default` still passes (it monkeypatches `orch.get_settings`; the autouse fixture clears the canonical cache without touching that monkeypatch).

**Definition of Done**

- [ ] **AC-1:** `.venv/bin/python -m pytest backend/tests/unit/workers/test_orchestrator_baseline_phase.py -p no:randomly` is all-green with `DATABASE_URL_FILE`/`POSTGRES_PASSWORD_FILE` **unset** in the shell. (Pre-fix baseline for the PR evidence: `3 failed, 1 passed`.)
- [ ] **AC-2:** `test_explicit_timeout_does_not_read_settings` passes post-fix; verified to **fail** against the pre-fix `_compute_baseline_wait_s` (temporarily revert Story 1.1 or run on the base commit to demonstrate the red).
- [ ] **AC-3:** `test_missing_trial_timeout_uses_settings_default` still returns `75.0`.
- [ ] **AC-4:** `make test-unit` (full `backend/tests/unit/`) green; coverage ≥ 80%.
- [ ] `make lint` passes (the new fixture follows the precedent; `Iterator` import used).

---

## 3) Testing workstream

| Layer | File | Story | What it covers |
|---|---|---|---|
| Unit | `backend/tests/unit/workers/test_orchestrator_baseline_phase.py` | 1.2 | Autouse env fixture (FR-2); `test_explicit_timeout_does_not_read_settings` regression (FR-3/AC-2); existing 4 `TestComputeBaselineWaitS` cases pass standalone (AC-1, AC-3). |

- Integration: N/A — no DB/workflow change. `backend/tests/integration/test_orchestrator_baseline_trial.py` is unaffected (not modified).
- Contract: N/A — no API surface.
- E2E: N/A — no UI.

## 4) Documentation update workstream

- No doc updates required. `docs/05_quality/testing.md` already states the hermeticity rule.
- `state.md` / `architecture.md`: no change (no architectural delta; one-helper refactor + test hygiene). The merge one-liner will be prepended to `state.md`'s "Last 5 merges" at finalization per the standard process — not part of this plan's code scope.

## 5) Migration

None. Alembic head is unchanged. No `alembic revision`, no schema change, no round-trip verification needed. (Confirmed: this change touches `backend/workers/orchestrator.py` and one test file only.)

## 6) Audit-event coverage

N/A — `_compute_baseline_wait_s` is a pure helper and the test change mutates no state. No `audit_log` emission applies.

## 7) Plan consistency review

- **Spec ↔ plan FR coverage:** FR-1 → Story 1.1; FR-2 → Story 1.2; FR-3 → Story 1.2. All three covered.
- **Endpoint count:** spec §8 = 0 endpoints; plan = 0. Match.
- **Error code coverage:** spec §7.5 = none; plan = none. Match.
- **File ownership:** `backend/workers/orchestrator.py` owned only by Story 1.1; the test file owned only by Story 1.2. No conflict.
- **Modified files exist:** `backend/workers/orchestrator.py` (verified, `_compute_baseline_wait_s` at 467-474); `backend/tests/unit/workers/test_orchestrator_baseline_phase.py` (verified, `TestComputeBaselineWaitS` at 66-89).
- **Test file assignment:** the single touched test file is assigned to Story 1.2. No orphans.
- **Open questions:** spec §19 has none.
- **No frontend scope** → no plan-level UI Guidance section required.
- **No enumerated values / dropdowns** → no source-of-truth contract table required.

## 8) Open questions

None.

---

## Cross-model review log (GPT-5.5)

Reviewer: GPT-5.5 (`gpt-5.5` via OpenAI Chat Completions, `max_completion_tokens`; spec passed as supporting context). API call succeeded; cross-model review performed (not skipped).

**Cycle 1** — 1 finding (0 High, 0 Medium, 1 Low).

| # | Pass | Severity | Finding | Adjudication |
|---|---|---|---|---|
| 1 | B | Low | The regression test's `_boom() -> Any` annotation would fail lint/typecheck if `Any` isn't imported, but the import task only adds `Iterator` + `get_settings`. | **Reject-as-already-satisfied** with a clarity patch. Counter-evidence: `Any` is already imported at `backend/tests/unit/workers/test_orchestrator_baseline_phase.py:22` (`from typing import Any`, used by the existing `_study(**overrides: Any) -> Any` helper at line 36) — copying the snippet as written would NOT raise an undefined name. The reviewer's concern was reasonable given the Tasks list didn't mention `Any` was pre-existing, so I added a clarifying note to Story 1.2 Task 1 confirming no new import is needed. No contract change. |

**Cycle 2** — re-review of the patched plan with the cycle-1 rejection log in the system prompt. Result: `{"findings": []}` (0 findings). **Convergence reached.**

**Convergence:** cycle 2 returned no findings. Total: 2 cycles, 1 finding (0 High, 0 Medium, 1 Low), 0 accepted / 1 rejected-with-counter-evidence (+ clarity note) / 0 deferred.
