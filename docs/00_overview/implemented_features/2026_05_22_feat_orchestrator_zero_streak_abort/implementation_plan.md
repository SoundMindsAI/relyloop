# Implementation Plan — Orchestrator zero-metric streak abort

**Date:** 2026-05-22
**Status:** Complete (PR #191, merged 2026-05-22 as squash `51ae4b3c`)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md) Absolute Rules; [`docs/05_quality/testing.md`](../../../../docs/05_quality/testing.md) test layer convention.

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Mirror precedent exactly: the existing `_last_n_all_failed` / `_CONSECUTIVE_FAILURE_THRESHOLD` pattern at [`backend/workers/orchestrator.py:69-210`](../../../../backend/workers/orchestrator.py) is the structural template — every architectural choice (module-level constant, helper near the loop, log levels, cancel-race handling) is locked to that precedent.
- Keep increments narrow: Story 1.1 is the ~30-LOC orchestrator change; Story 1.2 is the test suite + fixture helper. Both stories live on the same branch and the same PR (per the one-branch-per-session memory). 
- Fail-loud tests: every AC asserts an explicit terminal state, exact `failed_reason` string, and structlog event payload — no fuzzy "succeeded somehow" asserts.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Story | Notes |
|---|---|---|
| FR-1 (`_last_n_all_zero` helper) | Epic 1 / Story 1.1 | New async helper alongside `_last_n_all_failed`; SQL filters on `study_id` only; Python evaluates the predicate after the recent-`n` window. |
| FR-2 (`_ZERO_STREAK_THRESHOLD = 20`) | Epic 1 / Story 1.1 | Module-level constant adjacent to `_CONSECUTIVE_FAILURE_THRESHOLD = 5`. |
| FR-3 (abort block + structlog) | Epic 1 / Story 1.1 | New block in `start_study`'s polling loop, between the failure-streak block and the stop-condition checks. WARNING-level `stop_condition_fired`; INFO-level `orchestrator_race_lost` on cancel-race. |
| FR-4 (failure-streak precedence) | Epic 1 / Story 1.1 + 1.2 | Wired by the block ordering in 1.1; asserted by Story 1.2's `test_zero_streak_precedence_failure_streak_runs_first`. |
| FR-5 (no-op below threshold) | Epic 1 / Story 1.1 + 1.2 | Helper's "insufficient data" semantics in 1.1; covered by 1.2's boundary parameterized test. |

**Phase boundaries:** the spec defines a single phase (no Phase 2). No deferred-phase tracking files needed.

## 2) Delivery structure

**Epic 1 — Mid-flight zero-streak abort** (single epic, two stories on the same branch / same PR per `feedback_one_branch_per_session`).

### Conventions (project-specific)

- All repo functions take `db: AsyncSession` first arg; caller commits (existing pattern at [`backend/app/db/repo/trial.py`](../../../../backend/app/db/repo/trial.py)).
- Orchestrator helpers are async; the polling loop opens a fresh `AsyncSession` per tick — do NOT hold a session across `asyncio.sleep`. The new helper is invoked inside an already-open tick session, matching `_last_n_all_failed`'s call site.
- Module-level orchestrator constants are sentinel UPPER_SNAKE with a leading underscore (`_REPLENISH_TICK_S`, `_DRAIN_TIMEOUT_S`, `_CONSECUTIVE_FAILURE_THRESHOLD`). The new constant follows the same convention.
- `logger = structlog.get_logger(__name__)` is module-scoped at the top of `orchestrator.py` — the new code reuses it directly (no new logger instance).
- structlog calls use `event` (free-form) as the positional argument and `event_type=` (machine-routable) plus payload kwargs for filtering. The new emissions follow the existing precedent at [`orchestrator.py:196-201`](../../../../backend/workers/orchestrator.py) and [`orchestrator.py:202-209`](../../../../backend/workers/orchestrator.py).
- `study_state.fail_study` is the ONLY entry point for `running → failed` transitions. The orchestrator MUST NOT write `Study.status` directly — the SQLAlchemy event listener at [`backend/app/services/study_state.py:264-293`](../../../../backend/app/services/study_state.py) raises `StudyStateProtectionError` on unauthorized writes.

### AI Agent Execution Protocol

0. Load context: read [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md), and the feature spec ([`feature_spec.md`](feature_spec.md)) before starting Story 1.1.
1. Read scope: verify Story 1.1's outcome + key interfaces + DoD before writing code.
2. Implement backend (Story 1.1) first: constant → helper → block wiring → log emissions.
3. Run backend integration tests (`make test-integration` on the touched module): `pytest backend/tests/integration/test_study_lifecycle.py -v` should pass with the existing `test_ac5_five_consecutive_failures_fail_the_study` continuing to succeed (FR-4 precedent regression check).
4. Implement Story 1.2 (test fixtures + 6 new tests).
5. Run the full test suite: `make test-unit && make test-integration && make test-contract`.
6. Update `state.md` + `architecture.md` per §4 below.
7. No migration; skip migration round-trip verification.
8. Attach evidence in PR description: commands run, pass/fail counts, files changed.

---

## Epic 1 — Mid-flight zero-streak abort

### Story 1.1 — `_last_n_all_zero` helper + orchestrator abort block

**Outcome:** the orchestrator's polling loop aborts a study as `failed` with `failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"` whenever the 20 most-recent `optuna_trial_number`-ordered trials are all `status='complete' AND primary_metric=0.0` (FR-1, FR-2, FR-3). Failure-streak precedence (FR-4) and below-threshold no-op (FR-5) preserved by block ordering and helper semantics.

**New files**

None. The feature is contained entirely within an existing module.

**Modified files**

| File | Change |
|---|---|
| [`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py) | (1) Add module constant `_ZERO_STREAK_THRESHOLD: int = 20` adjacent to `_CONSECUTIVE_FAILURE_THRESHOLD` at line 69. (2) Add async helper `_last_n_all_zero(db, study_id, *, n)` alongside `_last_n_all_failed` at line 268. (3) Add new abort block inside `start_study`'s polling loop between the existing `_last_n_all_failed` block (currently lines 188-210) and the `max_trials`/`time_budget_min` checks (currently lines 213-220). (4) Update the module docstring's "Failure surface" section to document the new abort reason. |

**Endpoints**

None added or modified. This story has no API surface.

**Key interfaces**

```python
# backend/workers/orchestrator.py (module-scoped constant)
_ZERO_STREAK_THRESHOLD: int = 20
"""Spec FR-2 + AC-1: study transitions to ``failed`` with
``failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment
overlap likely lost mid-study"`` after 20 consecutive terminal trials all
satisfying ``status='complete' AND primary_metric IS NOT NULL AND
primary_metric == 0.0``. Threshold rationale (per feature_spec.md §19
decision log): Optuna's TPE warm-up default is 10 random samples; 20
covers both the random and informed phases — if both score 0.0, the
search space genuinely can't produce signal. Module-level constant, NOT
Settings, mirroring _CONSECUTIVE_FAILURE_THRESHOLD precedent."""


# backend/workers/orchestrator.py (helper, adjacent to _last_n_all_failed)
async def _last_n_all_zero(db: AsyncSession, study_id: str, *, n: int) -> bool:
    """Return True iff the N most recent terminal trials are ALL status='complete'
    with primary_metric == 0.0.

    Ordered by ``optuna_trial_number DESC``. If fewer than ``n`` rows exist
    for this study, returns False (insufficient signal). A single non-zero,
    failed, pruned, or NULL-metric row in the window resets the streak.

    Mirrors _last_n_all_failed semantics: SQL WHERE clause filters on
    study_id ONLY; the status / NULL / zero predicate is evaluated in
    Python on the recent-n window. Pre-filtering in SQL would change the
    semantics from "last n trials are zero" to "last n complete-zero
    trials exist anywhere", producing false-positive aborts.
    """
    stmt = (
        select(Trial.status, Trial.primary_metric)
        .where(Trial.study_id == study_id)
        .order_by(Trial.optuna_trial_number.desc())
        .limit(n)
    )
    rows = list((await db.execute(stmt)).all())
    if len(rows) < n:
        return False
    return all(
        status == "complete" and primary_metric is not None and primary_metric == 0.0
        for status, primary_metric in rows
    )
```

**New abort block** (inserted in `start_study`'s polling loop between the existing failure-streak return and the `max_trials` check):

```python
# 3a. Zero-metric-streak detection (spec FR-3 / AC-1). Runs AFTER the
# failure-streak check (FR-4 precedence preserved) and BEFORE the
# max_trials / time_budget checks. Same cancel-race handling as the
# failure-streak path.
if await _last_n_all_zero(db, study_id, n=_ZERO_STREAK_THRESHOLD):
    try:
        await study_state.fail_study(
            db,
            study_id,
            failed_reason=(
                "no signal: 20 consecutive trials scored 0.0 — "
                "judgment overlap likely lost mid-study"
            ),
        )
        await db.commit()
        logger.warning(
            "study failed",
            event_type="stop_condition_fired",
            study_id=study_id,
            reason="no_signal",
        )
    except study_state.InvalidStateTransition:
        await db.rollback()
        logger.info(
            "no-signal transition lost race; exiting",
            event_type="orchestrator_race_lost",
            study_id=study_id,
            attempted_reason="no_signal",
        )
    return
```

**Pydantic schemas**

None. The change does not touch any API request/response surface.

**Tasks**

1. Add `_ZERO_STREAK_THRESHOLD = 20` constant + docstring immediately after `_CONSECUTIVE_FAILURE_THRESHOLD` at [`orchestrator.py:69-73`](../../../../backend/workers/orchestrator.py).
2. Add the `_last_n_all_zero` helper immediately after `_last_n_all_failed` at the end of the file's "Internals" section (~line 285). Verify the SQL uses `select(Trial.status, Trial.primary_metric)` (not the full `Trial` row), `.where(Trial.study_id == study_id)`, `.order_by(Trial.optuna_trial_number.desc())`, `.limit(n)` — and the predicate is evaluated in Python on the returned rows, not in SQL.
3. Insert the new abort block in `start_study`'s polling loop, immediately AFTER the existing `_last_n_all_failed` block's `return` (line 210) and BEFORE the `max_trials` check (line 213). Block uses the new `_ZERO_STREAK_THRESHOLD` constant and the exact `failed_reason` string from FR-3 (byte-equal — tests in Story 1.2 assert this).
4. Inside the new block, call `study_state.fail_study(db, study_id, failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study")`, then `await db.commit()`, then `logger.warning(...)` with `event_type="stop_condition_fired"` and `reason="no_signal"`. On `InvalidStateTransition`, `await db.rollback()` then `logger.info(...)` with `event_type="orchestrator_race_lost"` and `attempted_reason="no_signal"`. End with `return`.
5. Update the `start_study` docstring's "Failure surface" bullet list to document the new abort: "After 20 consecutive `status='complete' AND primary_metric=0.0` trials, the orchestrator calls `fail_study` with `failed_reason='no signal: …'`."
6. Run `make backend-lint && make backend-typecheck` (the backend-only fast path — equivalent to running the backend portion of `make lint && make typecheck`; both are valid per the Makefile, the backend-only variant just skips the UI subtargets, which is appropriate here since no UI files change). Confirm no new ruff or mypy errors. Then run the existing `test_ac5_five_consecutive_failures_fail_the_study` test to confirm FR-4 precedent still works (`pytest backend/tests/integration/test_study_lifecycle.py::test_ac5_five_consecutive_failures_fail_the_study -v`).

**Definition of Done (DoD)**

- [ ] `_ZERO_STREAK_THRESHOLD = 20` is exported as a module-level constant adjacent to `_CONSECUTIVE_FAILURE_THRESHOLD` with a docstring citing spec FR-2.
- [ ] `_last_n_all_zero(db, study_id, *, n)` exists, signature matches the key-interface block above, and its SQL filters on `study_id` ONLY (no status/metric predicate in the SQL).
- [ ] The new abort block sits between `_last_n_all_failed` (line 210 area) and the `max_trials` check (line 213 area) — verified by reading the diff.
- [ ] `make backend-lint && make backend-typecheck` clean (equivalent to the backend portion of `make lint && make typecheck`; backend-only targets are valid Makefile aliases per the Makefile, used here because no UI changes).
- [ ] The existing `test_ac5_five_consecutive_failures_fail_the_study` integration test still passes (FR-4 precedent regression check).
- [ ] No other file is modified by this story (verified by `git diff --stat`).

---

### Story 1.2 — Test coverage for zero-streak abort (6 integration tests + fixture helper)

**Outcome:** every FR and AC in `feature_spec.md` has at least one integration test assertion; the `build_zero_scoring_hits_response` fixture helper is available alongside the existing `build_hits_response` for any future feature needing a zero-scoring stub adapter.

**New files**

None. All test additions and the fixture helper land in existing files.

**Modified files**

| File | Change |
|---|---|
| [`backend/tests/integration/fixtures/handbuilt_qrels.py`](../../../../backend/tests/integration/fixtures/handbuilt_qrels.py) | Add `build_zero_scoring_hits_response(query_ids, top_k=10)` returning a `{query_id: [ScoredHit]}` shape where every doc ID is **not** in the qrels (e.g., `miss-1`, `miss-2`, `miss-3`), so pytrec_eval's intersection is empty and `primary_metric == 0.0` for every metric on every query. Module docstring updated to mention the new builder. |
| [`backend/tests/integration/test_study_lifecycle.py`](../../../../backend/tests/integration/test_study_lifecycle.py) | Add 6 new tests covering AC-1 through AC-5 + FR-1/FR-5 boundary matrix (see "Tasks" below). Reuses existing helpers `seed_study`, `install_stub_adapter`, `monkeypatch_qrels`, `_running_orchestrator`, `_wait_for_status`. |

**Endpoints**

None.

**Key interfaces**

```python
# backend/tests/integration/fixtures/handbuilt_qrels.py

def build_zero_scoring_hits_response(
    query_ids: Sequence[str], top_k: int = 10
) -> dict[str, list[Any]]:
    """Return a ``search_batch``-shaped response whose doc IDs do NOT appear
    in :func:`build_qrels`'s qrels for these query_ids.

    Used by feat_orchestrator_zero_streak_abort integration tests to drive
    the orchestrator into trials with ``status='complete' AND
    primary_metric == 0.0``: pytrec_eval's qrels-vs-run intersection is
    empty when no doc ID overlaps, so every metric (NDCG, MAP, MRR,
    precision, recall) collapses to exactly 0.0.
    """
    from backend.app.adapters.protocol import ScoredHit

    # Doc IDs ``miss-*`` are guaranteed disjoint from build_qrels()'s
    # ``d1``/``d2``/``d3`` fixture set.
    return {
        str(qid): [
            ScoredHit(doc_id=f"miss-{i}", score=1.0 - i * 0.1)
            for i in range(min(top_k, 3))
        ]
        for qid in query_ids
    }
```

**Pydantic schemas**

None.

**Tasks**

Each integration test below is a separate async function with `pytestmark = pytest.mark.integration` (inherited from the module). All use the existing `seed_study(...)` factory (status='queued' by default) + `_running_orchestrator` context manager + `_wait_for_status`. Per the file's existing import block (`from backend.workers import orchestrator` — see [`backend/tests/integration/test_study_lifecycle.py:87`](../../../../backend/tests/integration/test_study_lifecycle.py)), the orchestrator module is already accessible as `orchestrator` inside `_running_orchestrator`; tests that need it at top scope should use `from backend.workers import orchestrator` (NOT `backend.app.workers` — the worker module is at `backend.workers`, not under `backend.app`). Monkeypatch targets use the same path: `monkeypatch.setattr("backend.workers.orchestrator.logger", recording_logger)`, `monkeypatch.setattr("backend.workers.orchestrator._last_n_all_failed", ...)`, etc.

1. **`test_zero_streak_20_consecutive_zeros_fails_the_study`** (AC-1 + FR-3 structlog contract). Seed `max_trials=25, parallelism=1`. Install a stub adapter via a thin wrapper of `install_stub_adapter` that replaces `search_batch_response` with the new `build_zero_scoring_hits_response(query_ids)`. Monkeypatch the orchestrator's `logger` with a `RecordingLogger` (per [`backend/tests/_log_helpers.py`](../../../../backend/tests/_log_helpers.py) `RecordingLogger`) so the structlog assertions survive the cache-warmth issue documented in `_log_helpers.py`. Drive the orchestrator; wait for `status='failed'` (timeout 60s). Assert:
   - `study.status == 'failed'`
   - `study.failed_reason == "no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"` (byte equality)
   - `summary.complete >= 20 AND summary.failed == 0 AND summary.pruned == 0` (the third clause per spec AC-1 — guards against a regression that produces pruned trials in the zero-streak path)
   - `recording_logger.find(level='warning', event_type='stop_condition_fired')` returns at least one record whose payload includes `reason='no_signal' AND study_id=<fixture.study_id>`.

2. **`test_zero_streak_nonzero_outlier_in_recent_window_does_not_fire`** (AC-2 boundary). Seed `max_trials=30, parallelism=1`. Install a stub adapter that returns `build_hits_response(query_ids)` (non-zero scoring) on its 11th `search_batch` call and `build_zero_scoring_hits_response(query_ids)` on every other call — implement this as a thin counter-stub wrapper around `StubAdapter`. The stub also exposes an `asyncio.Event` (`barrier`) that, when un-set, makes the stub's 21st `search_batch` call (and all subsequent calls) `await barrier.wait()` before returning — pausing the orchestrator's advancement past terminal-20 until the test explicitly releases. Drive the orchestrator under this **barrier-stub pattern** so the snapshot at terminal-20 is deterministic (per cycle-1 F3 + cycle-2 F1 findings — both (a) and (b) are mandatory per spec AC-2; neither half may be dropped). Concretely: (a) Snapshot at terminal-20: poll for `terminal == 20` AND fail-fast with `pytest.fail("snapshot missed — terminal advanced past 20")` if `terminal > 20` is observed first (the barrier keeps this from happening, but the fail-fast is a defensive backstop); open a session, call `_last_n_all_zero(db, fixture.study_id, n=20)` directly, assert returns `False`; assert `study.status == 'running'`. (b) Release the barrier (`barrier.set()`) and let the orchestrator run to completion: wait for `status='completed'` (timeout 60s); assert `study.failed_reason is None AND study.best_metric > 0.0`. Both (a) and (b) MUST execute and assert — dropping either is non-compliant with spec AC-2.

3. **`test_zero_streak_interleaved_failures_does_not_fire`** (AC-3). Seed `max_trials=24, parallelism=1`. Install a custom stub that alternates: on odd `search_batch` calls returns `build_zero_scoring_hits_response(query_ids)`, on even calls raises `ClusterUnreachableError`. (Use the existing `StubAdapter`'s `raise_on_search` field, toggled per-call via a closure or a `call_count`-tracking subclass.) **Set up `RecordingLogger` exactly like Tasks 1, 4, 5**: `recording_logger = RecordingLogger(); monkeypatch.setattr("backend.workers.orchestrator.logger", recording_logger)` (per cycle-1 F4 finding — the log assertion below needs an explicit setup). Drive the orchestrator; wait for `status='completed'` (timeout 60s). Assert:
   - `study.status == 'completed'`
   - `study.failed_reason is None`
   - `study.best_metric == 0.0`
   - **Streak-abort paths must NOT have fired:** `recording_logger.find(level='warning', event_type='stop_condition_fired')` returns `[]` (the streak-abort paths — `consecutive_failures` and `no_signal` — emit at WARNING; if either had fired, the study would be `failed` not `completed`, but assert the WARNING absence explicitly as the canary).
   - **`max_trials_reached` IS emitted at INFO:** `recording_logger.find(level='info', event_type='stop_condition_fired')` contains at least one record with `reason='max_trials_reached'`. (Note: `_stop()` at [`orchestrator.py:373`](../../../../backend/workers/orchestrator.py) emits `event_type='stop_condition_fired'` at INFO via `logger.info(...)` — only the streak-abort paths use WARNING. This is the existing precedent the zero-streak guard mirrors.)

4. **`test_zero_streak_precedence_failure_streak_runs_first`** (AC-5 / FR-4). Seed `max_trials=30, parallelism=1` with a vanilla stub adapter. Monkeypatch `orchestrator._last_n_all_failed` → `AsyncMock(return_value=True)` AND `orchestrator._last_n_all_zero` → `AsyncMock(return_value=True)`. Monkeypatch the recording logger. Drive the orchestrator; wait for `status='failed'` (timeout 30s). Assert:
   - `study.failed_reason == "5 consecutive trial failures"` (the failure-streak path's exact string)
   - `orchestrator._last_n_all_zero.call_count == 0` (the zero-streak helper was never invoked — the failure-streak block returned first)
   - `recording_logger.find(level='warning', event_type='stop_condition_fired')[0]['reason'] == 'consecutive_failures'`.

5. **`test_zero_streak_cancel_race_during_abort`** (AC-4). Seed `max_trials=30, parallelism=1` with a vanilla stub adapter. Monkeypatch `orchestrator._last_n_all_zero` → `AsyncMock(return_value=True)` AND `study_state.fail_study` → `AsyncMock(side_effect=study_state.InvalidStateTransition("cancelled-mid-flight"))`. Monkeypatch the recording logger. Drive the orchestrator; wait for the orchestrator task to terminate (timeout 30s) using a try/except that asserts no exception escapes — the task should complete normally. Assert:
   - The orchestrator task ended without raising
   - `recording_logger.find(level='info', event_type='orchestrator_race_lost')` returns at least one record whose payload includes `attempted_reason='no_signal' AND study_id=<fixture.study_id>`
   - (No assertion on `study.status` — the simulated raise does not perform a real cancel transition, so the row stays at `running`; this is documented in AC-4's "Production-state note".)

6. **`test_last_n_all_zero_helper_boundary_cases`** (FR-1 + FR-5 matrix). Parameterized with `@pytest.mark.parametrize`; each subcase calls `seed_study(...)` fresh (or reuses one study but inserts trials directly into separate study rows via `repo.create_study` + `repo.create_trial` — pick the simpler implementation; the rule is "no shared state between matrix rows"). Subcases (each asserts `_last_n_all_zero(db, study_id, n=20)` returns the expected boolean):
   - 0 trials → False
   - 19 zero-metric `complete` trials (`optuna_trial_number=0..18`) → False
   - 20 zero-metric `complete` trials (`optuna_trial_number=0..19`) → True
   - 20 trials all `complete`, one row at `optuna_trial_number=10` has `primary_metric=0.5` → False
   - 20 trials, one row at `optuna_trial_number=10` has `status='failed'` (others `complete` zero) → False
   - 20 trials, one row at `optuna_trial_number=10` has `status='pruned'` → False
   - 20 trials all `complete`, one row at `optuna_trial_number=10` has `primary_metric=NULL` → False
   - 25 trials where the FIRST 5 (`optuna_trial_number=0..4`) are `complete` `primary_metric=0.5` and the LAST 20 (`optuna_trial_number=5..24`) are zero-metric `complete` → True (the older outliers fall outside the recent-20 window)

   The test uses `repo.create_trial` directly (matching the pattern at [`backend/app/db/repo/trial.py:53`](../../../../backend/app/db/repo/trial.py): `async def create_trial(db, **fields) -> Trial`), populating `id` (uuidv7), `study_id`, `optuna_trial_number`, `params={}`, `primary_metric`, `metrics={}`, `status`, `started_at=None`, `ended_at=None`. Each subcase tears down via `cleanup_study` (per the existing fixture).

**Definition of Done (DoD)**

- [ ] `build_zero_scoring_hits_response(query_ids, top_k=10)` added to `handbuilt_qrels.py` with docstring.
- [ ] All 6 new tests pass: `pytest backend/tests/integration/test_study_lifecycle.py -v -k 'zero_streak or last_n_all_zero'` returns ≥ 13 PASSED (5 `test_zero_streak_*` tests + the `test_last_n_all_zero_helper_boundary_cases` parameterized test counts as 8 PASSED for the 8 matrix subcases; total = 5 + 8 = 13).
- [ ] The existing `test_ac5_five_consecutive_failures_fail_the_study` test still passes (FR-4 precedent regression check — also asserted by the precedence test).
- [ ] `make test-integration` clean overall (no regressions in other lifecycle tests).
- [ ] AC-1 test asserts the structlog `event_type="stop_condition_fired", reason="no_signal"` at WARNING — proves FR-3's observability contract.
- [ ] AC-5 test asserts `_last_n_all_zero.call_count == 0` when failure-streak fires — proves FR-4 precedence.
- [ ] AC-4 test asserts no exception escapes the orchestrator task on `InvalidStateTransition` — proves the new abort block's cancel-race handling.
- [ ] FR-1/FR-5 boundary test covers all 8 matrix subcases listed in Task 6.

---

## UI Guidance

**No UI Guidance section required.** This feature has zero frontend scope — no story creates, moves, or removes UI. The existing `StudyHeader.failed_reason` renderer at [`ui/src/components/studies/study-header.tsx:85-90`](../../../../ui/src/components/studies/study-header.tsx) displays the new `failed_reason` string verbatim with no code change.

**No legacy behavior parity table required** — no user-facing component >100 LOC is being deleted or migrated in this plan. (The spec §11 confirms zero frontend code change.)

**Information architecture placement:** the new failure mode surfaces via the existing `/studies/[id]` page's `StudyHeader` "Failed reason" row. No navigation change.

---

## 3) Testing workstream (required)

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Scope: not required at the unit layer for this feature. The unit suite is strictly DB-free (per [`docs/05_quality/testing.md`](../../../../docs/05_quality/testing.md)), and every behavior in this feature seeds real trial rows or runs the real orchestrator's polling loop. The precedence and cancel-race tests live at the **integration** layer accordingly (Story 1.2 tests 4 and 5).
- Tasks: none.
- DoD: N/A.

### 3.2 Integration tests

- Location: `backend/tests/integration/test_study_lifecycle.py`
- Scope: helper SQL semantics, end-to-end orchestrator abort behavior, code-structure assertions on the loop block.
- Tasks:
  - [ ] (Story 1.2) Add `test_zero_streak_20_consecutive_zeros_fails_the_study` (AC-1 + FR-3).
  - [ ] (Story 1.2) Add `test_zero_streak_nonzero_outlier_in_recent_window_does_not_fire` (AC-2).
  - [ ] (Story 1.2) Add `test_zero_streak_interleaved_failures_does_not_fire` (AC-3).
  - [ ] (Story 1.2) Add `test_zero_streak_precedence_failure_streak_runs_first` (AC-5 / FR-4).
  - [ ] (Story 1.2) Add `test_zero_streak_cancel_race_during_abort` (AC-4).
  - [ ] (Story 1.2) Add `test_last_n_all_zero_helper_boundary_cases` (FR-1 + FR-5, 8 parameterized subcases).
- DoD:
  - [ ] All 6 new tests pass via `make test-integration`.
  - [ ] The existing `test_ac5_five_consecutive_failures_fail_the_study` still passes.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: not required. No API surface change.
- Tasks: none.
- DoD: N/A.

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: not required. No new UI route or interaction; the existing `StudyHeader.failed_reason` rendering is covered by existing component tests against the same DOM.
- Tasks: none.
- DoD: N/A.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| [`backend/tests/integration/test_study_lifecycle.py`](../../../../backend/tests/integration/test_study_lifecycle.py) | `test_ac5_five_consecutive_failures_fail_the_study` (existing) | 1 | **No change.** This test asserts the existing failure-streak abort; it must continue to pass after Story 1.1 lands (FR-4 precedent regression check). The new precedence test (Story 1.2 test 4) additionally asserts that ordering. |
| [`ui/src/components/studies/study-header.test.tsx`](../../../../ui/src/components/studies/study-header.test.tsx) (if it exists) | `failed_reason` render | unknown | **No change needed.** The renderer is shape-agnostic; it displays any string. (Confirmed by reading [`study-header.tsx:85-90`](../../../../ui/src/components/studies/study-header.tsx) — the conditional renders `{study.failed_reason}` directly with no string-matching.) |

### 3.5 Migration verification

- Not applicable. **No schema change in this plan.** Alembic head stays at `0015_trials_per_query_metrics` (verified via `ls migrations/versions/ | sort | tail -1`).

### 3.6 CI gates

- [ ] `make test-unit` (regression check — should be unchanged)
- [ ] `make test-integration` (includes the 6 new tests + the existing precedent test)
- [ ] `make test-contract` (regression check — this PR introduces no new contract failures; 2 pre-existing local failures in `test_error_codes.py` are unrelated and tracked at `bug_contract_test_stub_missing_target_filter_kwarg/`)
- [ ] `make lint && make typecheck` (regression check)
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test` (regression check — should be unchanged, no frontend code touched)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

**`state.md`** — update at finalization (post-merge) to:
- [ ] Move the feature folder to `implemented_features/2026_XX_XX_feat_orchestrator_zero_streak_abort/` (per impl-execute finalization step).
- [ ] Add a "Most recent meaningful changes" entry with the squash SHA, integration test count delta, and the new `failed_reason` string for future grep.

**`architecture.md`** — no change needed. The new helper / threshold constant is internal to `backend/workers/orchestrator.py` and not a new layer / data flow / integration; the existing pointer to `orchestrator.py` covers it.

**`CLAUDE.md`** — no change needed. No new convention, env var, build command, or absolute rule.

### 4.1 Architecture docs (`docs/01_architecture/`)

- [ ] No change. No endpoint, error code, column, or invariant added that isn't already covered by the existing `feat_study_lifecycle` architecture docs.

### 4.2 Product docs (`docs/02_product/`)

- [ ] After merge: move `docs/00_overview/planned_features/feat_orchestrator_zero_streak_abort/` → `docs/00_overview/implemented_features/2026_XX_XX_feat_orchestrator_zero_streak_abort/` per the finalization convention.

### 4.3 Runbooks (`docs/03_runbooks/`)

- [ ] No change required for MVP1. A future addition to a not-yet-existing `study-debugging.md` runbook could mention the new `failed_reason` string — but that runbook doesn't exist yet, and adding a section for one string is not warranted.

### 4.4 Security docs (`docs/04_security/`)

- [ ] No change. No new threat surface, no new secret, no new external network call.

### 4.5 Quality docs (`docs/05_quality/`)

- [ ] No change. Integration tests follow the existing pattern.

**Documentation DoD**

- [ ] `state.md` updated at finalization with the new "Most recent meaningful changes" entry.
- [ ] Feature folder moved to `implemented_features/` at finalization.

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals

- None — this is a pure additive change. No duplication is being eliminated; the existing `_last_n_all_failed` precedent is intentionally preserved (NOT factored into a shared helper) because the two guards have different predicate shapes (`status='failed'` is a 1-tuple check; `status='complete' AND primary_metric IS NOT NULL AND primary_metric=0.0` is a 3-tuple check), and the precedent's stability is more valuable than the small DRY win.

### 5.2 Planned refactor tasks

- None.

### 5.3 Refactor guardrails

- [ ] FR-4 precedent preservation: the existing `_last_n_all_failed` block and the `test_ac5_five_consecutive_failures_fail_the_study` test must remain functionally unchanged. The precedence test (Story 1.2 test 4) is the canary.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_study_lifecycle` Phase 2 orchestrator + `study_state.fail_study` service | Story 1.1 | **Implemented** (PR #25, 2026-05-11). | N/A — already shipped. |
| `_last_n_all_failed` precedent at `orchestrator.py:268` | Story 1.1 (modeling pattern) | **Implemented**. | N/A — already shipped. |
| `RecordingLogger` test helper at `backend/tests/_log_helpers.py` | Story 1.2 (structlog assertions on AC-1, AC-4, AC-5) | **Implemented** (PR #114, 2026-05-14). | If unavailable, fall back to `structlog.testing.capture_logs()`; per `_log_helpers.py` docstring, the cache-warmth issue may make the assertions flaky. `RecordingLogger` is the correct tool. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Implementer pre-filters the SQL `WHERE` clause on status/metric (the F1 cycle-1+2 finding scenario) — produces false-positive aborts | Medium | High | Story 1.1 Task 2 explicitly states "SQL filters on `study_id` ONLY; predicate evaluated in Python on the recent-`n` window"; Story 1.2 test 6 (boundary matrix) is the canary that fails immediately on this regression. |
| Implementer inserts the new block BEFORE `_last_n_all_failed` — breaks FR-4 precedence | Low | Medium | Story 1.1 Task 3 specifies block ordering explicitly; Story 1.2 test 4 (precedence) asserts ordering directly. |
| Float-equality assertion (`primary_metric == 0.0`) trips on floating-point noise | Very Low | Low | Per spec §19 decision log and verified by reading [`backend/app/eval/scoring.py:186-194`](../../../../backend/app/eval/scoring.py), `score()` emits exactly `0.0` (arithmetic mean of pytrec_eval's `[0.0, 0.0, ...]`) for the empty-qrels-intersection case — no tolerance band needed. |
| `RecordingLogger` monkey-patch target is wrong (e.g., patches `backend.workers.orchestrator.logger` but the test sees an older cached binding) | Low | Medium | `_log_helpers.py` docstring documents this exact case at line 11-20; the pattern is `monkeypatch.setattr("backend.workers.orchestrator.logger", rec)`. Story 1.2 tasks use this pattern. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Cluster index deleted mid-study | Operator runs `DELETE` against the target index after the orchestrator has dispatched | 20 trials complete with `primary_metric=0.0` → new abort block fires → study transitions to `failed` with the no-signal `failed_reason` | Operator inspects `failed_reason`, re-creates the index, opens a new study |
| Auth token silently expires mid-study | Cluster credentials rotate; adapter falls back to anonymous | Same as above (zero-overlap searches → zero-metric trials → abort) | Operator rotates auth, re-creates cluster row, opens new study |
| Template body breaks at a specific param value Optuna keeps sampling | TPE samples a degenerate point | If 20 consecutive samples all hit that degenerate region → abort. If samples diverge → study continues normally | Operator inspects winning trials, fixes the template, opens a new study |
| Cancel race during abort | Operator cancels via `cancel_study` between the helper return and `fail_study` | `study_state.fail_study` raises `InvalidStateTransition`; orchestrator rolls back, logs `orchestrator_race_lost` at INFO, exits | None needed; operator's cancel wins (study is `cancelled`) |
| Postgres unavailable during the helper query | `OperationalError` from `db.execute` | Re-raises through the `session_factory()` context manager → Arq retries the `start_study` job → fresh orchestrator instance resumes via the running-study path | Existing Arq retry mechanism |

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — backend orchestrator change. Verify with existing `test_ac5_five_consecutive_failures_fail_the_study` (must still pass).
2. **Story 1.2** — fixture helper + 6 new integration tests. Run the full integration suite at the end.

### Parallelization opportunities

- None. Story 1.2 depends on Story 1.1's code being in place (the tests in 1.2 import `orchestrator._ZERO_STREAK_THRESHOLD` and `orchestrator._last_n_all_zero` for monkeypatching). Stories are strictly sequential.

## 8) Rollout and cutover plan

- **Rollout stages:** single-shot. No feature flag. Roll back via revert if regressions surface.
- **Feature flag strategy:** none. The guard is hardcoded; reverting the commit fully disables the new behavior.
- **Migration/cutover steps:** none — no schema change.
- **Reconciliation/repair strategy:** N/A — no persisted state introduced.

## 9) Execution tracker (copy/paste section)

### Current sprint

- [x] Story 1.1 — `_last_n_all_zero` helper + orchestrator abort block (commit `ac64a2a`)
- [x] Story 1.2 — 6 integration tests + `build_zero_scoring_hits_response` fixture helper (commit `4f0691b`)

### Blocked items

- (none)

### Done this sprint

- [x] Story 1.1 + Story 1.2 implemented; 13/13 new integration tests pass; AC-5 precedent regression test still passes.

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Key interfaces implemented with the documented signatures
- [ ] Required tests added/updated for the integration layer (only layer touched)
- [ ] Commands executed and passed:
    - [ ] `make backend-lint`
    - [ ] `make backend-typecheck`
    - [ ] `make test-unit` (regression — should be unchanged)
    - [ ] `make test-integration` (includes 6 new tests on Story 1.2)
    - [ ] `make test-contract` (regression check — no new contract failures introduced by this PR; pre-existing local stub-signature drift tracked separately at `bug_contract_test_stub_missing_target_filter_kwarg/`)
- [ ] No migration changes — no round-trip verification needed
- [ ] Related docs/checklists updated in same PR when behavior changed (only `state.md` finalization update, at the end of Story 1.2)

## 11) Plan consistency review (required before execution)

1. **Spec ↔ plan endpoint count**: spec §8.1 lists 0 new endpoints (only 2 existing endpoints surface the new state via existing `failed_reason` field). Plan: 0 new endpoints across all stories. ✓ Match.

2. **Spec ↔ plan error code coverage**: spec §8.5 lists 0 new error codes (the locked decision is to NOT allocate `STUDY_NO_SIGNAL`). Plan: 0 new error codes; no contract tests required. ✓ Match.

3. **Spec ↔ plan FR coverage**: all 5 FRs (FR-1 through FR-5) have rows in §1 traceability table and are assigned to Story 1.1 and/or Story 1.2. ✓ Match.

4. **Story internal consistency**:
   - Story 1.1 modifies exactly one file (`backend/workers/orchestrator.py`); no ownership conflict.
   - Story 1.2 modifies exactly two files (`handbuilt_qrels.py`, `test_study_lifecycle.py`); no ownership conflict.
   - Story 1.1's DoD asserts no other file is modified; Story 1.2's DoD asserts the 6 new tests pass.

5. **Test file count**: §3.2 enumerates 6 new test functions + 1 fixture helper across 2 files. Stories assign all 6 + 1 to Story 1.2. ✓ Match.

6. **Gate arithmetic**: no "all N endpoints live" gate (no endpoints added). The DoD gate is "all 6 new integration tests pass" — matches the 6 tests in §3.2.

7. **Open questions resolved**: spec §19 lists 0 open questions ("None"). ✓ No unresolved questions.

8. **Frontend UI Guidance completeness**: N/A — no stories have frontend scope. The "UI Guidance" section above explicitly states this.

9. **Plan ↔ codebase verification**:
   - `backend/workers/orchestrator.py:69` is `_CONSECUTIVE_FAILURE_THRESHOLD = 5` — **verified** by direct read.
   - `backend/workers/orchestrator.py:268-284` is the `_last_n_all_failed` helper — **verified**.
   - `backend/workers/orchestrator.py:188-210` is the failure-streak block — **verified** (188 is the `if await _last_n_all_failed(...)` line; 210 is `return`).
   - `backend/app/services/study_state.py:233-256` is `fail_study` — **verified**.
   - `backend/tests/integration/fixtures/handbuilt_qrels.py:52` is `build_hits_response` — **verified**.
   - `backend/tests/integration/test_study_lifecycle.py:218-251` is `test_ac5_five_consecutive_failures_fail_the_study` — **verified**.
   - `backend/tests/_log_helpers.py:68` is `RecordingLogger` — **verified**.
   - `backend/app/db/repo/trial.py:53` is `create_trial(db, **fields)` — **verified**.

10. **Infrastructure path verification**:
    - Migration directory: `migrations/versions/` (not `backend/alembic/versions/`) — **verified** via `ls migrations/versions/ | tail -5`. Current head: `0015_trials_per_query_metrics`. No new migration in this plan.
    - Router registration: N/A — no router changes.

11. **Frontend data plumbing verification**: N/A — no frontend changes.

12. **Persistence scope consistency**: N/A — no `localStorage` / `sessionStorage` usage.

13. **Enumerated value contract audit**: this feature touches the `Study.status` enum without adding a new value. Spec §8.4 cites `backend/app/db/models/study.py` (the column declaration + `studies_status_check` CHECK). The plan does not add any new `<select>` / filter dropdown on the frontend. ✓ No drift surface.

14. **Audit-event coverage audit**: MVP1 — `audit_log` lands at MVP2. N/A per spec §6.

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New/Modified files, Endpoints (or N/A), Key interfaces (or N/A), Tasks, DoD.
- [x] Test layers (integration only — others N/A) are explicitly scoped.
- [x] Documentation updates across docs/01-05 are planned (most N/A; `state.md` + folder move at finalization).
- [x] Lean refactor scope is explicit (none).
- [x] Phase/epic gates are measurable (Story 1.1 DoD; Story 1.2 DoD; CI gates §3.6).
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed with no unresolved findings.
