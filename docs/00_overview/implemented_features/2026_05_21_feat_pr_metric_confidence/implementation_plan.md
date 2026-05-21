# Implementation Plan — PR Metric Confidence (Phase 1)

**Date:** 2026-05-21
**Status:** Complete (PR #180, merged 2026-05-21 as squash `d0a8358`)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md), [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md), [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs from the spec.
- Phase gates are hard stops: Story 1.1 (migration) must merge before any other story's persistence dependency lands.
- Fail-loud tests: every degraded path from spec FR-7 is exercised by a dedicated test case.
- Match existing repo / router / domain / service / worker conventions byte-for-byte — no inventing new patterns when a precedent exists.
- Story increments are narrow enough that each can be reviewed independently (no story exceeds ~400 LOC of code+tests).

## 1) Scope traceability (FR → epics/stories)

| FR ID | Story | Notes |
|---|---|---|
| FR-1 (persist per_query_metrics) | Epic 1 / Story 1.1 (migration) + Story 1.2 (worker write) | Migration adds nullable JSONB column + DB CHECK; worker writes on success branch only. |
| FR-2 (compute_study_confidence) | Epic 1 / Story 1.3 (domain helper) | Async function; 4-query read pattern; partial-population contract. |
| FR-3 (winner-vs-runner-up reference) | Epic 1 / Story 1.3 | Lock `comparison_against = "runner_up"` unconditionally in Phase 1. |
| FR-4 (locked thresholds + methods) | Epic 1 / Story 1.3 | All thresholds from spec §7 FR-4 + §7 FR-4a coded as module constants. |
| FR-4a (regressor threshold table) | Epic 1 / Story 1.3 | `REGRESSOR_THRESHOLDS: dict[str, float]` module constant. |
| FR-5a (StudyDetail enrichment) | Epic 1 / Story 1.4 (`ConfidenceShape` + API wiring) | New Pydantic model + `_detail()` enrichment. |
| FR-5b (PR body section) | Epic 1 / Story 1.5 (PR body + worker plumbing) | Renderer extension to `_render_pr_body_study_backed`. |
| FR-5c (ConfidencePanel UI) | Epic 2 / Story 2.2 (panel + page mount) | New component + page integration. |
| FR-5d (PR worker plumbing) | Epic 1 / Story 1.5 | Worker fetches Study + awaits `compute_study_confidence` + passes into renderer. |
| FR-6 (digest narrative prompt) | Epic 1 / Story 1.6 (digest prompt + worker plumbing) | XML blocks + system-prompt edit. |
| FR-7 (graceful degradation paths) | Epic 1 / Story 1.3 (test coverage) + Story 1.4 (response contract) + Story 2.2 (UI gating) | Every degraded sub-field is independent; tests cover each combination. |

All 8 FRs are covered by 9 stories across 2 epics. Phase 2 (deferred orchestrator baseline-trial work) is tracked in [`phase2_idea.md`](phase2_idea.md) — no in-flight FRs left untracked.

## 2) Delivery structure

**Epic → Story → Tasks → DoD** (preferred — this is product-facing work with a clear backend → frontend cut).

### Conventions (RelyLoop project-specific)

```
- All repo functions take db: AsyncSession as first arg; use db.flush() — caller commits
- Services are async; orchestrators create job_run records (N/A here — no new service-layer orchestrator)
- Domain layer is pure: no DB access except via passed-in db handle, no I/O except via callables
- Models use Mapped[] typed columns, String(36) UUIDs (UUIDv7 generated client-side)
- Routers return typed Pydantic response models; errors use HTTPException with _err() envelope
- Settings via pydantic-settings; never hardcode LLM model names — read from Settings.openai_model
- All __init__.py exports updated via __all__
- Migrations: sequential numeric revision IDs (0015_trials_per_query_metrics next); include downgrade(); round-trip verified
- Conventional Commits (commit-msg hook enforced)
```

### AI Agent Execution Protocol

Per RelyLoop CLAUDE.md Absolute Rule #9, this plan is executed via `/impl-execute`. Each story:

0. **Load context first**: Read `architecture.md` and `state.md` before starting.
1. **Read scope**: verify story outcome + endpoints + interfaces + DoD.
2. **Implement backend first**: migration → models → repo → domain → service → router → schemas.
3. **Run backend tests**: `make test-unit`, then targeted integration + contract for touched endpoints.
4. **Implement frontend** (Story 2.* only).
5. **Run E2E**: `cd ui && pnpm playwright test tests/e2e/...` for touched paths.
6. **Update docs/state.md** if behavior changed (Story 1.1 moves Alembic head; Story 1.3 adds new domain module).
7. **Verify migration round-trip** (Story 1.1 only).
8. **Attach evidence** in PR description: commands run, pass/fail, files changed.
9. **After the final story**, update `state.md` (Alembic head bump, feature ship status) and `architecture.md` (`backend/app/domain/study/confidence.py` is the new module worth a line).

---

## Epic 1 — Backend persistence, analytics, and PR/digest surfaces

### Story 1.1 — Alembic migration `0015_trials_per_query_metrics`

**Outcome:** The `trials` table gains a nullable JSONB column `per_query_metrics` with a CHECK constraint enforcing `IS NULL OR jsonb_typeof = 'object'`. Migration round-trips cleanly. Existing rows stay NULL (no backfill).

**FRs:** FR-1, AC-1 setup, AC-17.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0015_trials_per_query_metrics.py` | Alembic revision 0015. `upgrade()` adds the column + CHECK. `downgrade()` drops the CHECK + column. Revision string is `"0015"` (matches the 4-char convention from `0014_clusters_target_filter.py:18`). |
| `backend/tests/integration/test_trials_per_query_metrics_migration.py` | 3 round-trip tests following the pattern at [`backend/tests/integration/test_clusters_target_filter_migration.py`](../../../../backend/tests/integration/test_clusters_target_filter_migration.py) (cited in state.md as the most recent migration-test precedent). |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/db/models/trial.py`](../../../../backend/app/db/models/trial.py) | Add `per_query_metrics: Mapped[dict[str, Any] \| None] = mapped_column(JSONB, nullable=True)` after the existing `metrics` column (line 61). Add the CHECK constraint to `__table_args__` (currently lines 34-39). Update the module docstring to mention the new column. |

**Key interfaces**

```python
# migrations/versions/0015_trials_per_query_metrics.py
revision: str = "0015"
down_revision: str | None = "0014"

def upgrade() -> None:
    op.add_column(
        "trials",
        sa.Column("per_query_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "trials_per_query_metrics_object_check",
        "trials",
        "per_query_metrics IS NULL OR jsonb_typeof(per_query_metrics) = 'object'",
    )

def downgrade() -> None:
    op.drop_constraint("trials_per_query_metrics_object_check", "trials", type_="check")
    op.drop_column("trials", "per_query_metrics")
```

**Tasks**
1. Write the migration file at `migrations/versions/0015_trials_per_query_metrics.py` following the shape of [`migrations/versions/0014_clusters_target_filter.py`](../../../../migrations/versions/0014_clusters_target_filter.py).
2. Add the ORM column and CHECK constraint to `backend/app/db/models/trial.py`.
3. Write integration test `test_trials_per_query_metrics_migration.py` with 3 cases:
   - `test_migration_adds_column_with_null_default`: pre-existing trial row stays NULL.
   - `test_migration_round_trip`: `upgrade head → downgrade -1 → upgrade head` succeeds with no errors and the column reappears NULL.
   - `test_check_constraint_rejects_non_object`: `INSERT ... per_query_metrics='[]'::jsonb` raises CHECK violation. The asyncpg-level error is wrapped by SQLAlchemy AsyncSession as `sqlalchemy.exc.IntegrityError`; assert on that type and check `.orig.__class__.__name__ == "CheckViolationError"` for the inner wrapped exception (cycle-3 GPT-5.5 F3 fix — SQLAlchemy doesn't surface asyncpg exceptions directly).
4. Run `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` locally.
5. Update [`state.md`](../../../../state.md) Alembic head section from `0014_clusters_target_filter` → `0015_trials_per_query_metrics`.

**Definition of Done (DoD)**
- [ ] Migration file exists at `migrations/versions/0015_trials_per_query_metrics.py` with both `upgrade()` and `downgrade()`.
- [ ] `make test-integration` passes including 3 new cases in `test_trials_per_query_metrics_migration.py`.
- [ ] Migration round-trip verified on the populated dev DB.
- [ ] `state.md` updated with the new Alembic head.
- [ ] ORM `Trial` model exposes `per_query_metrics: dict[str, Any] | None`.

---

### Story 1.2 — Persist `per_query_metrics` in the `run_trial` worker

**Outcome:** On every successful trial, `pytrec_eval`'s `per_query` dict is persisted to `trials.per_query_metrics`. Failed trials leave the column NULL.

**FRs:** FR-1, AC-1, AC-2.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_run_trial_per_query_persistence.py` | 2 cases — happy path persistence + failed-path NULL. Uses the existing `infra_optuna_eval` integration-test scaffold + stubbed adapter. |

**Modified files**

| File | Change |
|---|---|
| [`backend/workers/trials.py`](../../../../backend/workers/trials.py) | Line 440 — add `per_query_metrics=scored["per_query"]` kwarg to the `repo.create_trial(...)` call. The line currently writes `metrics=scored["aggregate"]` — the new kwarg goes immediately after it. The failed-path call at line 500 stays unchanged (it already writes `metrics={}` with no per_query_metrics — that's the intended NULL contract). |
| [`backend/app/db/repo/trial.py`](../../../../backend/app/db/repo/trial.py) | `create_trial()` signature — add `per_query_metrics: dict[str, Any] | None = None` as a new kwarg. Pass it through to `Trial(...)` constructor. Default None preserves existing callers (test fixtures may not provide it). |

**Key interfaces**

```python
# backend/app/db/repo/trial.py
async def create_trial(
    db: AsyncSession,
    *,
    id: str,
    study_id: str,
    optuna_trial_number: int,
    params: dict[str, Any],
    primary_metric: float | None,
    metrics: dict[str, Any],
    duration_ms: int | None,
    status: str,
    error: str | None,
    started_at: datetime | None,
    ended_at: datetime | None,
    per_query_metrics: dict[str, Any] | None = None,  # NEW (FR-1) — default None preserves legacy callers
) -> Trial:
    ...
```

**Tasks**
1. Read the current `create_trial` signature at `backend/app/db/repo/trial.py` and extend with the new optional kwarg. Update `Trial(...)` instantiation to pass it.
2. Modify `backend/workers/trials.py:433-446` to add `per_query_metrics=scored["per_query"]` to the success-path call.
3. Write `test_run_trial_per_query_persistence.py` with:
   - `test_successful_trial_writes_per_query_metrics`: seed cluster + qs + queries + judgment list + template, enqueue 1 trial via the standard scaffold, await completion, assert `SELECT per_query_metrics FROM trials WHERE id = ?` returns non-NULL dict shaped `{qid: {ndcg, map, precision, recall, mrr: float}}`. Use `MetricCatalog` keys (`ndcg`, `precision`, `recall`, etc.) — NOT pytrec_eval wire forms.
   - `test_failed_trial_leaves_per_query_metrics_null`: simulate adapter raise during trial, assert resulting Trial row has `status='failed'` AND `per_query_metrics IS NULL`.
4. Run `make test-integration` locally; verify both new cases pass.

**Definition of Done (DoD)**
- [ ] `run_trial` worker writes `per_query_metrics` on success path (one-line addition).
- [ ] `repo.create_trial` accepts the new kwarg with default None.
- [ ] Both integration tests pass — covers AC-1 + AC-2.
- [ ] No existing tests break (the new kwarg is optional).

---

### Story 1.3 — Domain module `backend/app/domain/study/confidence.py` + `ConfidenceShape` Pydantic model

**Outcome:** Pure-Python async helper `compute_study_confidence(db, study)` returns a `ConfidenceShape | None` per FR-2's contract. Every locked threshold from FR-4 + FR-4a is a module constant. Every degraded path from FR-7 has a dedicated unit test. **`ConfidenceShape` and all 7 sub-shapes are defined in this story** (cycle-1 GPT-5.5 F6 fix — Story 1.4 cannot import a type that doesn't exist yet, so the type ownership lives with the assembler).

**FRs:** FR-2, FR-3, FR-4, FR-4a, FR-7 (test coverage). FR-5a piece: `ConfidenceShape` definition (the wiring to `StudyDetail` stays in Story 1.4).

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/confidence.py` | The domain module. Exports `compute_study_confidence`, `ConfidenceShape` + 7 sub-models, the 3 new Literals (`ConvergenceRegime`, `RunnerUpClassification`, `ComparisonAgainst`), the `CIMethod` Literal, the locked constants (`BOOTSTRAP_N=1000`, `BOOTSTRAP_SEED=42`, `BOOTSTRAP_CI_LEVEL=0.95`, `BOOTSTRAP_MIN_N_QUERIES=5`, `REGRESSOR_THRESHOLDS: dict[str, float]`, `RUNNER_UP_PLATEAU_BAND=0.005`, `LATE_TRIAL_WINDOW_FRAC=0.2`, `LATE_TRIAL_WINDOW_MIN=5`, `LATE_TRIAL_MIN_COMPLETE=10`, `EARLY_HELD_TRIAL_NUMBER_FRAC=0.5`, `EARLY_HELD_LATE_WINDOW_FRAC=0.25`, `LATE_RISING_TRIAL_NUMBER_FRAC=0.9`, `CONVERGENCE_MIN_COMPLETE=3`, `RUNNER_UP_GAP_MIN_COMPLETE=2`, `TOP_REGRESSORS_CAP=5`), and the 8 pure helper functions (see key interfaces). |
| `backend/tests/unit/domain/study/test_confidence.py` | 25+ unit test cases covering: bootstrap_ci_95 (seed determinism, N<5 suppression, N=20 expected interval); classify_runner_up_gap (returns full `RunnerUpGapShape \| None`; robust_plateau / sharp_peak / 2-trial edge / N<2 suppression); compute_late_trial_stddev (window math at N=10/20/50/100, N<10 suppression); classify_convergence_regime (early_held with late-window probe, late_rising at 90%, noisy fallback, N<3 suppression); compute_outcome_summary (improved/unchanged/regressed counts per FR-4a threshold table + `regressor_candidates: list[tuple[qid, winner, comparison, delta]]` sorted by absolute delta); build_regressor_rows (5-cap, query_text join via lookup arg); compute_study_confidence orchestrator (whole-object null when best_trial_id IS NULL or row missing; partial when per_query_metrics IS NULL; partial when N<5 queries; full when all data present). |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/domain/study/__init__.py`](../../../../backend/app/domain/study/__init__.py) | Add `from . import confidence` and update `__all__` if present. |

**Key interfaces**

```python
# backend/app/domain/study/confidence.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Study, Trial

# IMPORTANT: do NOT import ObjectiveMetric from backend.app.api.v1.schemas — that creates a
# circular import (cycle-2 GPT-5.5 F1 fix). schemas.py imports ConfidenceShape from this
# module (one-direction); reciprocal import would deadlock at app startup. HeadlineShape.metric
# uses bare `str` instead — the upstream value is already validated by the existing
# ObjectiveMetric Literal at the create-study endpoint (schemas.py:214) so the wire contract
# is preserved.

# Locked constants — every value referenced from FR-4 / FR-4a.
BOOTSTRAP_N: int = 1000
BOOTSTRAP_SEED: int = 42
BOOTSTRAP_CI_LEVEL: float = 0.95
BOOTSTRAP_MIN_N_QUERIES: int = 5
REGRESSOR_THRESHOLDS: dict[str, float] = {
    "ndcg": 0.01, "precision": 0.01, "recall": 0.01,
    "map": 0.02, "mrr": 0.02,
}
RUNNER_UP_PLATEAU_BAND: float = 0.005
LATE_TRIAL_WINDOW_FRAC: float = 0.2
LATE_TRIAL_WINDOW_MIN: int = 5
LATE_TRIAL_MIN_COMPLETE: int = 10
EARLY_HELD_TRIAL_NUMBER_FRAC: float = 0.5
EARLY_HELD_LATE_WINDOW_FRAC: float = 0.25
LATE_RISING_TRIAL_NUMBER_FRAC: float = 0.9
CONVERGENCE_MIN_COMPLETE: int = 3
RUNNER_UP_GAP_MIN_COMPLETE: int = 2
TOP_REGRESSORS_CAP: int = 5

ConvergenceRegime = Literal["early_held", "late_rising", "noisy"]
RunnerUpClassification = Literal["robust_plateau", "sharp_peak"]
ComparisonAgainst = Literal["runner_up", "baseline"]  # Phase 1 only emits "runner_up"
CIMethod = Literal["bootstrap_n1000"]


# Pydantic shapes — exported and re-imported by `schemas.py` in Story 1.4 to extend StudyDetail.
class HeadlineShape(BaseModel):
    metric: str  # one of `ObjectiveMetric` values per schemas.py:214 — validated upstream at create-study
    value: float
    k: int | None
    n_queries: int | None  # None when winner has per_query_metrics IS NULL

class CIShape(BaseModel):
    low: float
    high: float
    method: CIMethod
    n_samples: int

class RunnerUpGapShape(BaseModel):
    value: float
    classification: RunnerUpClassification  # non-null: whole shape suppressed to None when classification can't be determined
    top10_within: float
    runner_up_metric: float

class LateTrialStddevShape(BaseModel):
    value: float
    window_size: int
    min_window_required: int  # always LATE_TRIAL_MIN_COMPLETE = 10

class ConvergenceShape(BaseModel):
    best_at_trial: int
    total_trials: int
    regime: ConvergenceRegime

class RegressorRowShape(BaseModel):
    query_id: str
    query_text: str
    winner_score: float
    comparison_score: float
    delta: float

class PerQueryOutcomesShape(BaseModel):
    improved: int
    unchanged: int
    regressed: int
    comparison_against: ComparisonAgainst
    top_regressors: list[RegressorRowShape]  # ≤ TOP_REGRESSORS_CAP

class ConfidenceShape(BaseModel):
    headline: HeadlineShape
    ci_95: CIShape | None
    runner_up_gap: RunnerUpGapShape | None
    late_trial_stddev: LateTrialStddevShape | None
    convergence: ConvergenceShape | None
    per_query_outcomes: PerQueryOutcomesShape | None


@dataclass(frozen=True)
class _OutcomeSummary:
    """Internal — produced by `compute_outcome_summary`; consumed by orchestrator + `build_regressor_rows`."""
    improved: int
    unchanged: int
    regressed: int
    regressor_candidates: list[tuple[str, float, float, float]]  # (qid, winner_score, comparison_score, delta), sorted by abs(delta) desc, capped at TOP_REGRESSORS_CAP


# Pure helpers — all synchronous, take numpy arrays / dicts.
def bootstrap_ci_95(per_query_values: list[float]) -> CIShape | None:
    """Percentile bootstrap with seed=42, N=1000 resamples. Returns None when len < BOOTSTRAP_MIN_N_QUERIES (5)."""

def classify_runner_up_gap(
    sorted_primary_metrics: list[float],  # descending, winner first; len ≥ RUNNER_UP_GAP_MIN_COMPLETE
) -> RunnerUpGapShape | None:
    """Returns the full RunnerUpGapShape with `value`, `classification`, `top10_within`, `runner_up_metric` populated. Returns None when len < RUNNER_UP_GAP_MIN_COMPLETE (2)."""

def compute_late_trial_stddev(
    primary_metrics_in_trial_order: list[float],
) -> LateTrialStddevShape | None:
    """Returns LateTrialStddevShape with value + window_size + min_window_required. None when N < LATE_TRIAL_MIN_COMPLETE (10)."""

def classify_convergence_regime(
    winner_trial_number: int,
    primary_metrics_by_trial_number: dict[int, float],  # complete trials only
) -> ConvergenceShape | None:
    """Returns ConvergenceShape with best_at_trial + total_trials + regime. None when N < CONVERGENCE_MIN_COMPLETE (3)."""

def compute_outcome_summary(
    winner_per_query: dict[str, dict[str, float]],
    comparison_per_query: dict[str, dict[str, float]],
    metric: str,  # one of REGRESSOR_THRESHOLDS keys
) -> _OutcomeSummary | None:
    """Returns counts + regressor_candidates (qids only, no text). Returns None when either input is empty/None.
    Sorts candidates by absolute delta descending, caps at TOP_REGRESSORS_CAP. Pure — no DB."""

def build_regressor_rows(
    candidates: list[tuple[str, float, float, float]],  # (qid, winner_score, comparison_score, delta)
    query_text_by_id: dict[str, str],  # hydrated from Q4 of the 4-query read pattern
) -> list[RegressorRowShape]:
    """Hydrates each candidate with query_text. If a qid is missing from the dict (deleted query — cascade race), the row is omitted."""

async def compute_study_confidence(
    db: AsyncSession,
    study: Study,
) -> ConfidenceShape | None:
    """Orchestrator — fires the 4-query read pattern from FR-2 + assembles ConfidenceShape.
    Returns None on whole-object-degraded paths per FR-7. Pseudocode:

        winner = await Q1(db, study.best_trial_id)
        if winner is None: return None  # FR-7 whole-object case (best_trial_id NULL or deleted)

        runner_up = await Q2(db, study.id, exclude=winner.id)
        complete_trials_summary = await Q3(db, study.id)  # projection: (primary_metric, optuna_trial_number)

        # Aggregate signals — independent of per_query data
        runner_up_gap = classify_runner_up_gap(sorted_primary_metrics_from_summary)  # may be None
        late_trial_stddev = compute_late_trial_stddev(primary_metrics_in_trial_order)  # may be None
        convergence = classify_convergence_regime(winner.optuna_trial_number, primary_metrics_by_trial_number)  # may be None

        # Winner-only per-query signals — depend only on winner's per_query_metrics
        # (cycle-2 GPT-5.5 F2 fix — AC-16 requires CI to populate even with 1 complete trial)
        if winner.per_query_metrics:
            winner_values_for_metric = [
                v[metric] for v in winner.per_query_metrics.values() if metric in v
            ]
            ci_95 = bootstrap_ci_95(winner_values_for_metric)  # may be None for N<5
            n_queries = len(winner_values_for_metric)
        else:
            ci_95 = None
            n_queries = None

        # Comparison-based per-query signals — require BOTH winner + runner_up to have per_query_metrics
        if winner.per_query_metrics and runner_up and runner_up.per_query_metrics:
            outcome = compute_outcome_summary(winner.per_query_metrics, runner_up.per_query_metrics, metric)
            query_text_by_id = await Q4(db, [qid for (qid, *_) in outcome.regressor_candidates])  # conditional — skipped if no candidates
            regressor_rows = build_regressor_rows(outcome.regressor_candidates, query_text_by_id)
            per_query_outcomes = PerQueryOutcomesShape(
                improved=outcome.improved, unchanged=outcome.unchanged, regressed=outcome.regressed,
                comparison_against='runner_up',  # FR-3 locked for Phase 1
                top_regressors=regressor_rows,
            )
        else:
            per_query_outcomes = None

        return ConfidenceShape(
            headline=HeadlineShape(metric=study.objective['metric'], value=study.best_metric, k=study.objective.get('k'), n_queries=...),
            ci_95=ci_95,
            runner_up_gap=runner_up_gap,
            late_trial_stddev=late_trial_stddev,
            convergence=convergence,
            per_query_outcomes=per_query_outcomes,
        )
    """
```

**Tasks**
1. Write `backend/app/domain/study/confidence.py` with the 7 pure helpers + the async orchestrator.
2. Inside `compute_study_confidence`, execute the 4-query read pattern from spec FR-2:
   - Q1: `SELECT * FROM trials WHERE id = :winner_id` — fetch winner.
   - Q2: `SELECT * FROM trials WHERE study_id = :sid AND status = 'complete' AND id != :winner_id ORDER BY primary_metric DESC NULLS LAST LIMIT 1` — fetch runner-up.
   - Q3: `SELECT primary_metric, optuna_trial_number FROM trials WHERE study_id = :sid AND status = 'complete' ORDER BY optuna_trial_number ASC` — summary list (projection only, no per_query_metrics).
   - Q4 (conditional): `SELECT id, query_text FROM queries WHERE id = ANY(:regressor_qids)` — only if `top_regressors` produced any rows.
3. Wire each helper to the appropriate sub-field of `ConfidenceShape` (the shapes are defined IN THIS STORY's `backend/app/domain/study/confidence.py`; Story 1.4 only re-exports + adds the field to `StudyDetail`).
4. Write `backend/tests/unit/domain/study/test_confidence.py` with 25+ cases covering every FR-7 degraded branch.
5. Lock numpy import at module top — no lazy-import dance; numpy is a hard dep via pytrec_eval.

**Definition of Done (DoD)**
- [ ] `backend/app/domain/study/confidence.py` exists with the 7 pure helpers + the async orchestrator.
- [ ] 25+ unit cases pass via `make test-unit`.
- [ ] Every FR-7 degraded sub-field path has an explicit test case.
- [ ] Bootstrap CI seed determinism asserted (AC-4 covered at unit layer).
- [ ] No `except Exception:` in the module (FR-7 invariant: errors propagate; degraded paths return None explicitly).

---

### Story 1.4 — `ConfidenceShape` Pydantic model + `StudyDetail` enrichment

**Outcome:** `GET /api/v1/studies/{id}` response gains an optional `confidence: ConfidenceShape | None` field. The OpenAPI schema is shape-locked. Old clients that don't deserialize the field continue to work.

**FRs:** FR-5a, FR-7 (wire contract).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_studies_api_confidence.py` | 11 integration tests covering AC-3, AC-3a, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-15, AC-16 (cycle-1 GPT-5.5 F9 added AC-6/AC-8/AC-9 at integration layer). Uses extended `_digest_helpers.py` seed pattern + configurable `optuna_trial_number` distribution to synthesize convergence-regime scenarios. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) | Re-export `ConfidenceShape` (defined in Story 1.3's `backend/app/domain/study/confidence.py`) via `from backend.app.domain.study.confidence import ConfidenceShape`. Add `confidence: ConfidenceShape \| None = None` to `StudyDetail` (insert after `trials_summary` at line 636). NOTE: The shape itself is defined in Story 1.3 (cycle-1 GPT-5.5 F6 fix — domain module owns the Pydantic types because it is the assembler). |
| [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) | `_detail()` at line 118 — `await compute_study_confidence(db, row)` and pass into the `StudyDetail(...)` constructor at line 134 (insert just before the closing paren). |
| [`backend/tests/contract/test_studies_api_contract.py`](../../../../backend/tests/contract/test_studies_api_contract.py) | Add 2 cases: `test_study_detail_includes_confidence_field` (OpenAPI shape lock — assert the JSON schema for `StudyDetail` contains the `confidence` property), `test_confidence_shape_has_six_subfields` (assert the schema's `ConfidenceShape` has `headline`, `ci_95`, `runner_up_gap`, `late_trial_stddev`, `convergence`, `per_query_outcomes`). |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/{study_id}` | — | `200` `StudyDetail` (existing shape + new `confidence: ConfidenceShape \| null` field) | `STUDY_NOT_FOUND` (404 — existing) |

No new error codes per spec §8.5.

**Pydantic schemas**

The `ConfidenceShape` and 7 sub-shapes are defined in Story 1.3 at `backend/app/domain/study/confidence.py` (see that story's Key interfaces section for the full Pydantic class definitions). Story 1.4 only re-exports them through `schemas.py` and adds the field to `StudyDetail`:

```python
# backend/app/api/v1/schemas.py
from backend.app.domain.study.confidence import ConfidenceShape  # NEW import — re-export for typing convenience

class StudyDetail(BaseModel):
    # ... existing 17 fields (id, name, cluster_id, target, ...) ...
    trials_summary: TrialsSummaryShape
    confidence: ConfidenceShape | None = None  # NEW (FR-5a)
```

**Tasks**
1. Add `from backend.app.domain.study.confidence import ConfidenceShape` to the imports of `backend/app/api/v1/schemas.py` (the shapes themselves live in Story 1.3's domain module per the cycle-1 sequencing fix).
2. Modify `StudyDetail` to add the `confidence: ConfidenceShape | None = None` field after `trials_summary`.
3. Modify `backend/app/api/v1/studies.py::_detail()` to `await compute_study_confidence(db, row)` and pass the result into the `StudyDetail(...)` constructor.
4. Add 11 integration test cases to `test_studies_api_confidence.py` per the AC mapping in the FR row (cycle-1 GPT-5.5 F9 expansion).
5. Add 2 contract test cases to `test_studies_api_contract.py` for OpenAPI shape lock.
6. Run `make test-integration && make test-contract` locally.

**Definition of Done (DoD)**
- [ ] `ConfidenceShape` and 7 sub-shapes are defined in `backend/app/domain/study/confidence.py` (Story 1.3); this story (1.4) only adds the `from backend.app.domain.study.confidence import ConfidenceShape` re-export at the top of `schemas.py`.
- [ ] `StudyDetail` has the new `confidence` field; `_detail()` populates it.
- [ ] 11 integration cases pass; 2 contract cases pass.
- [ ] OpenAPI schema includes the new shape (verified by the existing OpenAPI-surface contract test family — see `test_openapi_surface.py`).
- [ ] AC-3, AC-3a, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-15, AC-16 all green.

---

### Story 1.5 — PR body `## Confidence` section + PR-worker plumbing

**Outcome:** The `open_pr` worker fetches confidence before rendering, and `_render_pr_body_study_backed` emits the new section between `## Metric delta` and `## Config diff`. Section gracefully degrades when sub-fields are null. Section is entirely absent when `confidence is None`.

**FRs:** FR-5b, FR-5d, FR-7 (PR body gating).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/contract/test_pr_body_confidence_section.py` | 4 contract cases covering AC-11, AC-12, the partial-confidence rendering path (AC-3 mirror), and the section-omitted path when confidence is None. |
| `backend/tests/integration/test_open_pr_worker_confidence_plumbing.py` | 1 integration test that drives the real `open_pr` worker path end-to-end (NOT just the pure renderer) to verify FR-5d's worker-side data plumbing. |

**Modified files**

| File | Change |
|---|---|
| [`backend/workers/git_pr.py`](../../../../backend/workers/git_pr.py) | (a) Modify `_render_pr_body_study_backed` (line 488-528) — add a `confidence: ConfidenceShape \| None = None` kwarg; insert the `## Confidence` section between `## Metric delta` (line 504) and `## Config diff` (line 510) when `confidence is not None`. Render sub-blocks independently (each gated on its sub-field being non-null). (b) Modify the `open_pr` worker function (search `_render_pr_body_study_backed` callers at line ~904) — before calling the renderer, `await compute_study_confidence(db, study)` and pass into `_render_pr_body_study_backed(..., confidence=...)`. |

**Key interfaces**

```python
# backend/workers/git_pr.py
def _render_pr_body_study_backed(
    *,
    proposal: Any,
    study: Any,
    digest: Any,
    config_diff: dict[str, Any],
    chart_md: str,
    base_url: str | None,
    confidence: ConfidenceShape | None = None,  # NEW (FR-5b) — Pydantic object directly, per spec FR-5d
) -> str:
    ...

# `open_pr` worker function (existing) — extend the call site:
from backend.app.domain.study.confidence import compute_study_confidence

study = await repo.get_study(db, proposal.study_id)
confidence = await compute_study_confidence(db, study)  # Pydantic ConfidenceShape | None
body = _render_pr_body_study_backed(
    proposal=proposal,
    study=study,
    digest=digest,
    config_diff=proposal.config_diff,
    chart_md=chart_md,
    base_url=base_url,
    confidence=confidence,  # passed as Pydantic object — renderer reads .ci_95, .runner_up_gap, etc. directly
)
```

Note: Only the Jinja prompt rendering path (Story 1.6) serializes the shape via `.model_dump()` because Jinja consumes dicts. The PR-body renderer keeps the typed object — cycle-1 GPT-5.5 F3 fix.

**Tasks**
1. **Grep all `_render_pr_body_study_backed(` call sites** with `grep -rn "_render_pr_body_study_backed(" backend/`. At minimum the `open_pr` worker function calls it; if any other call site exists (e.g., a future test scaffold), every site MUST be updated to pass `confidence` per FR-5d (cycle-1 GPT-5.5 F11 fix). Current expectation per spec audit: one call site only (line ~904 in git_pr.py).
2. Add the `confidence` kwarg to `_render_pr_body_study_backed`. Construct the section markdown:
   - Section heading: `## Confidence`
   - CI line: `- {metric}@{k}: {value:.3f} (95% CI {low:.3f}-{high:.3f}, N={n_queries} queries)` — only when `confidence.ci_95` is non-null.
   - Per-query line: `- Queries: {improved} improved · {unchanged} unchanged · {regressed} regressed (vs {comparison_against})` — only when `confidence.per_query_outcomes` is non-null.
   - Regressor block: `- Queries that regressed: `\`{query_text}\`` ({comparison_score:.3f} → {winner_score:.3f}), ...` joined with `·` — only when `per_query_outcomes.regressed > 0`.
   - Runner-up gap line: `- Runner-up gap {value:.3f} ({classification or 'unclassified'})` — only when `runner_up_gap` non-null.
   - Noise floor line: `- Late-trial 1σ = {value:.3f}` — only when `late_trial_stddev` non-null.
   - Convergence line: `- Convergence: {regime} (best at trial {best_at_trial} of {total_trials})` — only when `convergence` non-null.
2. Modify the `open_pr` worker call site to fetch confidence and pass it through. Import `compute_study_confidence` from `backend.app.domain.study.confidence`.
3. Write the 4 contract test cases. Use direct calls to `_render_pr_body_study_backed(...)` with **factory-constructed `ConfidenceShape` instances** (cycle-2 GPT-5.5 F3 fix — renderer signature requires the typed Pydantic object; dicts would re-introduce drift). Add a small test helper `make_test_confidence(**overrides)` that builds a `ConfidenceShape` with sensible defaults and accepts per-test-case overrides for each sub-field.
4. Write the 1 integration test that drives the real worker function with a seeded completed study + per_query_metrics.

**Definition of Done (DoD)**
- [ ] `_render_pr_body_study_backed` emits the `## Confidence` section per the rendering contract above.
- [ ] `open_pr` worker fetches + passes confidence before rendering.
- [ ] AC-11 contract test (full-confidence path) passes.
- [ ] AC-12 contract test (whole-object null path — no section) passes.
- [ ] Partial-confidence contract test (per FR-7) passes.
- [ ] Integration test against real worker path passes — covers FR-5d.

---

### Story 1.6 — Digest narrative prompt extension

**Outcome:** `digest_narrative.user.jinja` carries `<confidence>` + `<per_query_outcomes>` XML blocks. `digest_narrative.system.md` opening guidance is edited per FR-6. The digest worker passes the serialized `ConfidenceShape` through to `render_digest_user_prompt`.

**FRs:** FR-6, AC-14.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`prompts/digest_narrative.user.jinja`](../../../../prompts/digest_narrative.user.jinja) | Insert `<confidence>` and `<per_query_outcomes>` blocks after the existing `</baseline_vs_achieved>` block (line 13) — use the exact Jinja from spec §7 FR-6. |
| [`prompts/digest_narrative.system.md`](../../../../prompts/digest_narrative.system.md) | (a) Lines 13-25 — extend the XML-block list to document blocks 8 (`<confidence>`) and 9 (`<per_query_outcomes>`) and their conditional inclusion. (b) Line 29-30 — replace the substring `Open with the headline metric delta.` with the **exact spec FR-6 string including backticks around XML names**: `Open with the headline metric delta, immediately followed by a one-sentence confidence framing that mentions the CI band (when `<confidence>` is present), the per-query outcome counts (when `<per_query_outcomes>` is present), and the worst-regressed query by name (when `<per_query_outcomes>` has regressors). Then explain *why*` — i.e., the markdown backticks around `<confidence>` and `<per_query_outcomes>` MUST be preserved per cycle-1 GPT-5.5 F4. |
| [`backend/app/llm/digest_prompt.py`](../../../../backend/app/llm/digest_prompt.py) | `render_digest_user_prompt` (line 67) — add `confidence: dict[str, Any] \| None = None` kwarg; pass through to the jinja render. |
| [`backend/workers/digest.py`](../../../../backend/workers/digest.py) | In the digest-generation function (search `render_digest_user_prompt` callers; existing code at ~line 690-700 already passes `baseline_metric` + `achieved_metric`) — `await compute_study_confidence(db, study)` and pass the serialized result through as the new `confidence` kwarg. |
| [`backend/tests/unit/workers/test_digest_prompt_render.py`](../../../../backend/tests/unit/workers/test_digest_prompt_render.py) | Add **5** new cases (cycle-1 GPT-5.5 F10 fix): (1) user-prompt contains `<confidence>` block with full data; (2) user-prompt OMITS `<confidence>` when `confidence=None`; (3) user-prompt contains `<per_query_outcomes>` block when nested data present; (4) user-prompt OMITS `<per_query_outcomes>` when `confidence.per_query_outcomes is None`; (5) **system-prompt** (rendered via `render_digest_system_prompt()`) contains the exact FR-6 replacement substring `Open with the headline metric delta, immediately followed by a one-sentence confidence framing that mentions the CI band (when ``<confidence>``...` AND the documented XML-block list entries for `<confidence>` and `<per_query_outcomes>` — covers AC-14's system-prompt half. |

**Tasks**
1. Edit `prompts/digest_narrative.user.jinja` to add the two new Jinja blocks.
2. Edit `prompts/digest_narrative.system.md` per the precise replacements above.
3. Extend `render_digest_user_prompt` with the new optional kwarg.
4. Modify the digest worker to fetch confidence and pass it through.
5. Add the 5 new test cases to `test_digest_prompt_render.py` (4 user-prompt + 1 system-prompt per cycle-1 F10).

**Definition of Done (DoD)**
- [ ] System prompt has the exact replacement string from spec FR-6.
- [ ] User jinja template renders `<confidence>` and `<per_query_outcomes>` blocks conditionally.
- [ ] `render_digest_user_prompt` accepts one new `confidence: dict | None` kwarg (NOT two — `per_query_outcomes` is nested inside per spec FR-6).
- [ ] Digest worker fetches + passes confidence.
- [ ] AC-14 unit test passes.

---

## Epic 1 gate (hard stop — do not enter Epic 2 until all pass)

- [ ] All 6 stories in Epic 1 are complete with green tests.
- [ ] `GET /api/v1/studies/{id}` returns a populated `confidence` field on a seeded study with per_query_metrics — verified live via `curl` against the local stack.
- [ ] A real-PR open against a completed study with per_query_metrics renders the `## Confidence` section in the PR body (verified by the integration test in Story 1.5).
- [ ] Alembic head is `0015_trials_per_query_metrics`; round-trip verified.

---

## Epic 2 — Frontend ConfidencePanel

### Story 2.1 — TypeScript types + wire-value enums

**Outcome:** The auto-generated `ui/src/lib/types.ts` reflects the new `ConfidenceShape` from the OpenAPI schema. `ui/src/lib/enums.ts` adds 3 new wire-value Literal arrays with source-of-truth comments per CLAUDE.md "Enumerated Value Contract Discipline."

**FRs:** FR-5c (precondition), supports §8.4 enumerated value contract.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/types.ts`](../../../../ui/src/lib/types.ts) | Regenerate from the live OpenAPI schema (run `cd ui && pnpm openapi:types` or the project's equivalent — checked into the repo via the pre-commit hook). Diff should show: new `ConfidenceShape` type + 7 sub-types + 4 new Literal types + extension of `StudyDetail` with the `confidence?: ConfidenceShape \| null` field. |
| [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) | Add 3 new wire-value arrays after the existing `OBJECTIVE_METRIC_VALUES` (line 68): `CONVERGENCE_REGIME_VALUES = ['early_held', 'late_rising', 'noisy'] as const;` + `RUNNER_UP_CLASSIFICATION_VALUES = ['robust_plateau', 'sharp_peak'] as const;` + `COMPARISON_AGAINST_VALUES = ['runner_up', 'baseline'] as const;` — each preceded by a source-of-truth comment `// Values must match backend/app/domain/study/confidence.py ConvergenceRegime` (etc.) per the project's enumerated-value-contract discipline. |

**Source-of-truth verification**

Per CLAUDE.md "Enumerated Value Contract Discipline":

| Wire value array | Backend source | Frontend file |
|---|---|---|
| `CONVERGENCE_REGIME_VALUES` | `backend/app/domain/study/confidence.py` `ConvergenceRegime = Literal["early_held", "late_rising", "noisy"]` (cycle-2 GPT-5.5 F1: types live in domain module, NOT schemas.py — schemas.py only re-exports `ConfidenceShape`) | `ui/src/lib/enums.ts` |
| `RUNNER_UP_CLASSIFICATION_VALUES` | `backend/app/domain/study/confidence.py` `RunnerUpClassification = Literal["robust_plateau", "sharp_peak"]` | `ui/src/lib/enums.ts` |
| `COMPARISON_AGAINST_VALUES` | `backend/app/domain/study/confidence.py` `ComparisonAgainst = Literal["runner_up", "baseline"]` (Phase 1 only emits `"runner_up"`; `"baseline"` reserved for Phase 2) | `ui/src/lib/enums.ts` |

**Tasks**
1. Regenerate `ui/src/lib/types.ts` from the live OpenAPI schema (after Story 1.4 has merged). Verify the diff covers `ConfidenceShape` + sub-shapes + the `StudyDetail.confidence` field.
2. Add the 3 wire-value Literal arrays to `ui/src/lib/enums.ts` with source-of-truth comments.
3. Run `cd ui && pnpm typecheck` — verify no type errors.
4. Run `cd ui && pnpm test` — verify no regressions in the existing 285+ test suite.

**Definition of Done (DoD)**
- [ ] `ui/src/lib/types.ts` regenerated and committed.
- [ ] `ui/src/lib/enums.ts` has 3 new arrays with source-of-truth comments.
- [ ] `pnpm typecheck` green.
- [ ] No existing vitest case breaks.

---

### Story 2.2 — `<ConfidencePanel>` component + glossary + page mount

**Outcome:** A new `<ConfidencePanel>` component renders on `/studies/[id]` between the study header card and the trials table. Renders nothing when `confidence === null` (no empty-state shell). Each sub-field is independently gated on its non-null state.

**FRs:** FR-5c.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/confidence-panel.tsx` | The new component. Takes one prop: `confidence: ConfidenceShape \| null \| undefined`. Renders nothing when `confidence == null`. Otherwise renders 4 sections: headline + CI band, per-query outcome chips + regressor table (when applicable), secondary callouts row (runner-up gap, late-trial 1σ, convergence). |
| `ui/src/__tests__/components/studies/confidence-panel.test.tsx` | 12 vitest cases — full-data render, null-confidence (renders nothing), partial render (each sub-field independently null), regressor table cap-at-5, "vs runner-up" / "vs baseline" label switching, tooltip presence + content, every degraded-path branch from FR-7. |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx) | Mount `<ConfidencePanel confidence={study.confidence} />` between the existing study header card and the trials table. Pass `study.confidence` from the `useStudy` hook's response. |
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | Add 6 new entries: `confidence.ci_95`, `confidence.runner_up_gap`, `confidence.late_trial_stddev`, `confidence.convergence_regime`, `confidence.per_query_outcomes`, `confidence.comparison_against`. Each entry follows the existing pattern at this file (short form for `<InfoTooltip>`, optional long form for `<HelpPopover>`). Use the tooltip text from spec §11 "Tooltips and contextual help" table verbatim. |
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) | The existing parity test (per `feat_contextual_help`) ensures glossary keys match enum values. Verify the 6 new keys appear; add a parity assertion for the 3 new wire-value enums from Story 2.1 if not auto-covered. |

**UI element inventory**

| Element | Source data | Interaction |
|---|---|---|
| Section heading "Confidence" | static text | none |
| Headline + CI band: e.g., "NDCG@10 = 0.840 (95% CI 0.78–0.89, N=20 queries)" | `confidence.headline` + `confidence.ci_95` (latter optional) | none |
| Per-query outcome chips: "14 Improved · 4 Unchanged · 2 Regressed (vs runner-up)" | `confidence.per_query_outcomes.{improved,unchanged,regressed,comparison_against}` (`COMPARISON_AGAINST_VALUES`) | hover on each chip → `<InfoTooltip>` (glossary key `confidence.per_query_outcomes`) |
| Named regressor table (up to 5 rows) | `confidence.per_query_outcomes.top_regressors` | none — read-only inline display |
| Runner-up gap label: "Runner-up gap 0.005 (Robust plateau)" | `confidence.runner_up_gap.{value, classification}` (`RUNNER_UP_CLASSIFICATION_VALUES`) | hover on classification badge → `<InfoTooltip>` (glossary key `confidence.runner_up_gap`) |
| Late-trial 1σ value | `confidence.late_trial_stddev.value` + `.window_size` | hover → `<InfoTooltip>` (glossary key `confidence.late_trial_stddev`) |
| Convergence call-out: "Early-and-held (best at trial 387 of 1000)" | `confidence.convergence.{regime, best_at_trial, total_trials}` (`CONVERGENCE_REGIME_VALUES`) | hover on regime badge → `<InfoTooltip>` (glossary key `confidence.convergence_regime`) |

**Source-of-truth comments**

Every JSX branch in `confidence-panel.tsx` that switches on a wire enum MUST include a comment citing the backend source:
```tsx
// Values must match backend/app/domain/study/confidence.py ConvergenceRegime
{regime === 'early_held' ? <Badge variant="success">Early-and-held</Badge> :
 regime === 'late_rising' ? <Badge variant="warning">Late-rising</Badge> :
 <Badge variant="warning">Noisy</Badge>}
```

**Tasks**
1. Read [`ui/src/components/studies/digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx) (the closest existing analogous component) as the structural template.
2. Read [`ui/src/components/studies/study-header.tsx`](../../../../ui/src/components/studies/study-header.tsx) for the badge + section layout idiom.
3. Implement `confidence-panel.tsx` with the 4 sections from the inventory. Use the project's existing `<Badge>` + `<InfoTooltip>` primitives.
4. Mount the panel in `ui/src/app/studies/[id]/page.tsx` between the existing header card render and the trials table.
5. Add the 6 glossary entries.
6. Write 12 vitest cases against the new component.

**Definition of Done (DoD)**
- [ ] `confidence-panel.tsx` exists and renders all 4 sections gated independently.
- [ ] Mounted on `/studies/[id]` page.
- [ ] 12 vitest cases pass.
- [ ] 6 glossary entries added; glossary parity test passes.
- [ ] `pnpm typecheck && pnpm lint && pnpm test` all green.
- [ ] Visual smoke check: `make up`, navigate to a seeded study with per_query_metrics, confirm the panel renders.

---

### Story 2.3 — Playwright real-backend E2E for ConfidencePanel

**Outcome:** 2 new real-backend Playwright cases extend `ui/tests/e2e/studies.spec.ts` (or a new spec file) covering the panel-renders + panel-absent paths.

**FRs:** FR-5c (browser-layer verification), AC-13.

**New files**

None — extend the existing spec.

**Modified files**

| File | Change |
|---|---|
| [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) | Add 2 new test cases. Both run real-backend (no `page.route()` mocking per CLAUDE.md E2E policy). |
| [`ui/tests/e2e/helpers/seed.ts`](../../../../ui/tests/e2e/helpers/seed.ts) | Add a new helper `seedCompletedStudyWithPerQueryMetrics()` that wraps the existing `seedStudyCompletedWithDigest()` AND extends the existing `_test/studies/seed-completed` endpoint (or its sibling backend test-seed helper at [`backend/tests/integration/_digest_helpers.py`](../../../../backend/tests/integration/_digest_helpers.py)) to populate `per_query_metrics` on the winner + runner-up trial rows it creates. **Do NOT add a new `/api/v1/_test/trials/set-per-query-metrics` test endpoint** (would conflict with the spec's "zero new endpoints" contract — cycle-1 GPT-5.5 F1). Either: (a) extend the existing seed-completed test endpoint to accept an optional `winner_per_query: dict` + `runner_up_per_query: dict` field and persist them, or (b) extend the backend `_digest_helpers.py` to populate per-query data, and call that helper via the existing test endpoint. Pick whichever the backend test infra already uses for similar seeding. |

**Tasks**
1. Add `seedCompletedStudyWithPerQueryMetrics()` to the seed helper. Reuse the existing `seedStudyCompletedWithDigest` scaffold; populate per-query data on the winner + runner-up trial rows via the most appropriate test endpoint or direct SQL.
2. Add 2 new test cases:
   - `ConfidencePanel renders for a completed study with per_query_metrics`: seed → navigate to `/studies/{id}` → assert the "Confidence" section heading is visible → assert the headline-with-CI text matches expected pattern → assert at least one outcome chip is visible.
   - `ConfidencePanel renders nothing for a study with confidence=null`: seed a study with no completed trials (or with `best_trial_id=NULL`) → navigate → assert the "Confidence" heading is NOT visible.
3. Run `cd ui && pnpm playwright test tests/e2e/studies.spec.ts` locally.

**Definition of Done (DoD)**
- [ ] 2 new Playwright cases pass against the real backend.
- [ ] No `page.route()` mocking introduced.
- [ ] AC-13 covered.

---

## Epic 2 gate

- [ ] All 3 stories in Epic 2 complete with green tests.
- [ ] `cd ui && pnpm test` shows all UI vitest cases green (including the 12 new confidence-panel cases).
- [ ] `cd ui && pnpm playwright test tests/e2e/studies.spec.ts` shows the 2 new cases green.
- [ ] Visual smoke check: panel renders correctly on a seeded study.

---

## UI Guidance

### Reference: current component structure

[`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx) — 114 lines total. Reads `useStudy(studyId)` and renders a header card + the trials table. Clean canvas for the new panel.

The closest existing analog for the new ConfidencePanel is [`ui/src/components/studies/digest-panel.tsx`](../../../../ui/src/components/studies/digest-panel.tsx) — renders study-end data conditionally (`if digest === null → render nothing`), uses `<InfoTooltip>` primitives from `feat_contextual_help`, and uses the project's standard badge + section layout. Read this file first when implementing Story 2.2.

### Insertion point

In `ui/src/app/studies/[id]/page.tsx`: between the existing `<StudyHeader>` render and the existing `<TrialsTable>` render. No code is removed. The new mount is one `<ConfidencePanel confidence={study.confidence} />` JSX node.

### Analogous markup patterns

Mount pattern — from `ui/src/app/studies/[id]/page.tsx` (existing trials table render):
```tsx
{/* Existing — keep as-is */}
<StudyHeader study={study} />

{/* NEW — add between header and trials table (Story 2.2) */}
<ConfidencePanel confidence={study.confidence} />

{/* Existing — keep as-is */}
<TrialsTable studyId={studyId} />
```

Conditional render pattern — from `ui/src/components/studies/digest-panel.tsx`:
```tsx
{/* If null/undefined, render nothing — no empty-state shell */}
export function ConfidencePanel({ confidence }: { confidence: ConfidenceShape | null | undefined }) {
  if (!confidence) return null;
  return (
    <section className="...">
      {/* sub-sections, each gated on its sub-field */}
    </section>
  );
}
```

Badge pattern — from `ui/src/components/studies/study-header.tsx` (status badge):
```tsx
{/* Use the existing Badge primitive; vary `variant` based on the wire-enum value */}
<Badge variant={regime === 'early_held' ? 'success' : 'warning'}>
  {regime === 'early_held' ? 'Early-and-held' : regime === 'late_rising' ? 'Late-rising' : 'Noisy'}
</Badge>
```

InfoTooltip pattern — from `ui/src/components/studies/digest-panel.tsx`:
```tsx
<span>
  95% CI
  <InfoTooltip glossaryKey="confidence.ci_95" />
</span>
```

### Layout and structure

The panel is a single `<section>` with 4 vertically stacked sub-sections:
1. Headline + CI band (single line, large font)
2. Per-query outcome chips row (3 chips side-by-side; horizontal)
3. Regressor table (when present; up to 5 rows, narrow inline table)
4. Secondary callouts row (3 callouts side-by-side: runner-up gap, late-trial 1σ, convergence — narrow horizontal layout)

Responsive: on screens <768px the 3-chip row and 3-callout row collapse to vertical stacks via existing Tailwind classes.

### Information architecture placement

Per spec §11: between study header card and trials table on `/studies/[id]`. No new nav, no new tab. Discoverable by anyone who lands on a study detail page.

### Tooltips and contextual help

Tooltips use the existing `<InfoTooltip glossaryKey="..." />` primitive (from `feat_contextual_help`). All tooltip text comes from the glossary, NOT inlined in the component — keeps the parity tests at `glossary.test.ts` green.

| Element | Glossary key | Primitive |
|---|---|---|
| "95% CI" label | `confidence.ci_95` | `<InfoTooltip>` |
| Outcome chips group | `confidence.per_query_outcomes` | `<InfoTooltip>` |
| Runner-up gap badge | `confidence.runner_up_gap` | `<InfoTooltip>` |
| Late-trial 1σ label | `confidence.late_trial_stddev` | `<InfoTooltip>` |
| Convergence regime badge | `confidence.convergence_regime` | `<InfoTooltip>` |
| Comparison label ("vs runner-up") | `confidence.comparison_against` | `<InfoTooltip>` |

### Visual consistency

| New element | CSS pattern source |
|---|---|
| Section heading "Confidence" | Matches `<h3>` in `ui/src/components/studies/digest-panel.tsx` |
| Headline + CI band | Mimics the metric-delta line in `ui/src/components/studies/study-header.tsx` |
| Outcome chips | Use `<Badge>` primitive at `ui/src/components/ui/badge.tsx` |
| Regressor table | Use existing inline narrow-table pattern (no `<DataTable>` — keep it simple; just `<table>` with Tailwind classes) |
| Tooltip triggers | `<InfoTooltip>` primitive at `ui/src/components/common/info-tooltip.tsx` |

### Component composition

The panel is a single new component, NOT extracted into sub-components. Each sub-section is inline JSX inside `<ConfidencePanel>`. Rationale: keeps the surface area small for review; the panel is read-only and the sub-sections don't have independent lifecycle. If a future feature needs to reuse one sub-section, it can be extracted at that time.

The panel takes ONE prop: `confidence: ConfidenceShape | null | undefined`. No callbacks, no shared state, no parent communication.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Navigate to `/studies/[id]` for a completed study with per_query_metrics | `useStudy` hook fetches study; `confidence` is part of the response; panel renders | `GET /api/v1/studies/{id}` (existing; no new endpoint) |
| Hover any tooltip trigger | `<InfoTooltip>` displays the glossary text | none |
| Visit `/studies/[id]` for a study with `confidence === null` | Panel renders nothing; no empty-state shell | (same GET) |

### Handler function patterns

No new handlers. The panel is read-only display. All interactivity is via the existing `<InfoTooltip>` primitive.

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** The trials table extension proposed in the original idea was dropped at spec-gen (Decision C2-F2 / cycle-2 GPT-5.5 review F10). The new ConfidencePanel is additive; the existing study-detail page keeps every prior behavior.

---

## 3) Testing workstream

### 3.1 Unit tests
- Location: `backend/tests/unit/domain/study/test_confidence.py` (Story 1.3) — 25+ cases
- Location: `backend/tests/unit/workers/test_digest_prompt_render.py` — 5 new cases (Story 1.6 — 4 user-prompt + 1 system-prompt per cycle-1 F10)
- Scope: domain helpers (bootstrap_ci, classify_runner_up_gap, compute_late_trial_stddev, classify_convergence_regime, classify_query_outcomes, top_regressors), `compute_study_confidence` orchestrator, every FR-7 degraded path, digest prompt rendering with/without confidence
- DoD:
  - [ ] All 25+ confidence cases pass deterministically
  - [ ] Bootstrap CI seed determinism asserted (AC-4)
  - [ ] Every FR-7 sub-field degraded path has an explicit test

### 3.2 Integration tests
- Location: `backend/tests/integration/test_trials_per_query_metrics_migration.py` (Story 1.1) — 3 cases
- Location: `backend/tests/integration/test_run_trial_per_query_persistence.py` (Story 1.2) — 2 cases
- Location: `backend/tests/integration/test_studies_api_confidence.py` (Story 1.4) — 11 cases
- Location: `backend/tests/integration/test_open_pr_worker_confidence_plumbing.py` (Story 1.5) — 1 case
- Scope: migration round-trip; worker persistence on success + failure; full GET /studies/{id} response with confidence; real PR worker drives end-to-end
- DoD:
  - [ ] All 17 integration cases pass (3 + 2 + 11 + 1)
  - [ ] AC-1, AC-2, AC-3, AC-3a, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-15, AC-16, AC-17 covered (cycle-1 GPT-5.5 F9)

### 3.3 Contract tests
- Location: `backend/tests/contract/test_studies_api_contract.py` — 2 new cases (Story 1.4)
- Location: `backend/tests/contract/test_pr_body_confidence_section.py` (Story 1.5) — 4 cases
- Scope: OpenAPI shape lock for `ConfidenceShape`; PR body section markdown shape across all 4 confidence-population states (full / partial / per-query-only-missing / whole-object-null)
- DoD:
  - [ ] 6 new contract cases pass
  - [ ] AC-11, AC-12 covered

### 3.4 E2E tests
- Location: `ui/tests/e2e/studies.spec.ts` — 2 new cases (Story 2.3)
- Scope: real-backend; ConfidencePanel renders for seeded completed study; panel renders nothing for confidence=null
- Rule: **Must use real browser interactions via Playwright's `page` object.** No `page.route()` mocking. API helpers acceptable for setup; assertions must verify browser-visible DOM elements.
- DoD:
  - [ ] Both new Playwright cases pass via `pnpm playwright test`
  - [ ] AC-13 covered

### 3.5 Migration verification
- [ ] `migrations/versions/0015_trials_per_query_metrics.py` includes `downgrade()` (Story 1.1)
- [ ] `alembic upgrade head` succeeds
- [ ] Round-trip verified: `alembic downgrade -1 && alembic upgrade head`
- [ ] DB CHECK constraint `trials_per_query_metrics_object_check` is active after upgrade (test in Story 1.1)

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm playwright test tests/e2e/studies.spec.ts`

### 3.7 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_studies_api.py` | Asserts `StudyDetail` shape | ≥1 | Add assertion that `confidence` key is present (may be null). No existing assertion breaks. |
| `backend/tests/integration/test_digest_zero_trials.py` | Digest worker with `best_metric=None` | 1 | No change — assert `confidence is None` propagates correctly. |
| `backend/tests/integration/test_digest_zero_trials_with_openai_unconfigured.py` | Degraded-mode digest | 1 | No change — same as above. |
| `backend/tests/integration/_digest_helpers.py` | Test seed helper | — | Optional extension: add `per_query_metrics` parameter so tests that need confidence data can seed it. |
| `backend/tests/contract/test_openapi_surface.py` | OpenAPI snapshot | — | Snapshot will change to include `ConfidenceShape`. Re-bake the snapshot in Story 1.4 (precedent: `feat_cluster_target_filter` did the same for `target_filter`). |

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] `state.md` — update on Story 1.1 (Alembic head bump to `0015_trials_per_query_metrics`); update on final story (feature ship status, branch context)
- [ ] `architecture.md` — add a line under "Where the code lives" → "domain/" describing `backend/app/domain/study/confidence.py` (new module). Optional: add a critical-flow bullet for "confidence computation on StudyDetail read" if the dashboard pattern warrants it.
- [ ] `CLAUDE.md` — no update required (no new convention, no new rule)

### 4.1 Architecture docs

- [ ] `docs/01_architecture/data-model.md` — add `trials.per_query_metrics` to the per-table column reference. Note nullable + post-`0015` semantics. Add forward-ref note under `studies.baseline_metric` that Phase 2 will add `baseline_trial_id` (per [`phase2_idea.md`](phase2_idea.md)).
- [ ] `docs/01_architecture/optimization.md` — add a brief "Confidence signals" subsection. Reference the new domain module + the 4-query read pattern.

### 4.2 Product docs

- [ ] No update — this spec IS the product doc artifact.

### 4.3 Runbooks

- [ ] No new runbook required (no new operator action).

### 4.4 Security docs

- [ ] No update — no new security surface.

### 4.5 Quality docs

- [ ] No update — existing test-layer convention covers the new test files.

**Documentation DoD**
- [ ] `state.md`, `architecture.md` consistent with shipped behavior
- [ ] `docs/01_architecture/data-model.md` + `optimization.md` updated

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None planned. The feature is purely additive across all surfaces.

### 5.2 Planned refactor tasks

- [ ] None.

### 5.3 Refactor guardrails

- N/A — no refactor in this plan.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_digest_proposal` (PR #41) | Story 1.6 (digest prompt extension) | implemented | If reverted, the digest prompt update is unreachable; feature still ships at the API + UI layers. |
| `feat_github_pr_worker` (PR #45) | Story 1.5 (PR body section) | implemented | If reverted, the PR body extension is unreachable; feature still ships at the API + UI layers. |
| `feat_studies_ui` (PR #50) | Story 2.2 (ConfidencePanel mount) | implemented | If reverted, the UI panel has no host page; backend surfaces unaffected. |
| `feat_llm_judgments` (PR #35) | Story 1.2 (worker persistence) | implemented | Per-query metrics depend on judgments; missing judgments = empty per_query data (graceful via FR-7). |
| `feat_contextual_help` (PR #122) | Story 2.2 (tooltips + glossary) | implemented | If reverted, the `<InfoTooltip>` primitive is missing; tooltips would need a different implementation. |
| numpy 1.x (via pytrec_eval) | Story 1.3 (bootstrap CI) | transitive dep verified | Cannot ship without numpy. Confirmed installed at `.venv/lib/python3.13/site-packages/numpy/__init__.py`. |
| Alembic head `0014_clusters_target_filter` | Story 1.1 (migration sequencing) | confirmed via `ls migrations/versions/` | Required so `0015` applies cleanly. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bootstrap CI seed determinism fails — different numpy versions produce different sequences from the same seed | L | M | Pin numpy version in `pyproject.toml` (if not already pinned). Asserted via AC-4 integration test that re-reads the same study and confirms byte-equal CI values. |
| `compute_study_confidence` performance worse than budget (<100ms) on 1000-trial × 100-query studies | L | L | The 4-query read pattern guarantees ~30KB wire load. Bootstrap loop is ~5ms for N=100. Spec §13 explicitly budgets <100ms. If exceeded, fallback is to compute confidence asynchronously and stash on a denormalized column (future MVP2 work). |
| Test coverage gap on the digest prompt rendering | L | M | Story 1.6's 5 new test cases cover with/without confidence × per_query_outcomes present/absent matrix + the system-prompt FR-6 replacement string assertion (AC-14 system-prompt half). |
| The OpenAPI snapshot test breaks — Story 1.4 changes the schema | M | L | Precedent: `feat_cluster_target_filter` re-baked the snapshot in the same PR. Same approach here. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Winner trial row missing (cascade-delete race) | `study.best_trial_id` resolves to deleted row | `compute_study_confidence` returns None (whole-object null); existing `digest_best_trial_missing` log event fires; PR body has no `## Confidence` section | None needed — graceful per FR-7 |
| `pytrec_eval` produces empty `per_query` dict (judgments don't match query_ids) | Misconfigured judgment list | Worker writes empty dict to `per_query_metrics` (not NULL); analytics treat empty as "no per-query data"; ConfidencePanel renders aggregate-only | Operator regenerates judgments |
| numpy version mismatch on bootstrap | Operator uses a different numpy version than the one pinned | Could produce different CI numbers vs. test fixtures | Pin numpy in `pyproject.toml`; CI uses the same lockfile |
| StudyDetail response too large for old clients | A 1000-trial × 100-query study produces ~30KB confidence payload | Old clients ignore the field; new clients render normally | None needed |
| OpenAPI snapshot test fails after Story 1.4 | Snapshot test wasn't re-baked | CI fails | Re-bake snapshot in same PR (precedent: `feat_cluster_target_filter` PR #168) |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — Migration (unblocks everything else)
2. **Story 1.2** + **Story 1.3** in parallel — worker write (1.2) is one-line trivial; domain module (1.3) is the longest story
3. **Story 1.4** — API enrichment (depends on 1.3 for `ConfidenceShape` import; depends on 1.1 for column existence)
4. **Story 1.5** + **Story 1.6** in parallel — PR body (1.5) and digest prompt (1.6) both depend on 1.4
5. **Epic 1 gate** — verify all backend stories green
6. **Story 2.1** — types + enums (depends on 1.4 OpenAPI shape being merged)
7. **Story 2.2** — ConfidencePanel component + page mount
8. **Story 2.3** — E2E
9. **Epic 2 gate** + final state.md + architecture.md update

### Parallelization opportunities

- 1.2 + 1.3 can be developed by different contributors (no file overlap)
- 1.5 + 1.6 can be developed by different contributors (no file overlap)
- 2.1 must precede 2.2 (types are a hard prerequisite)
- E2E (2.3) is strictly last

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single-stage rollout. RelyLoop is single-tenant + local-only through MVP3 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md). Merge to main = available to all operators on their next `make up`.
- **Feature flag strategy:** None. The feature ships in one PR.
- **Migration / cutover steps:** Operators run `make migrate` after pulling main to apply `0015_trials_per_query_metrics`. Old trials retain `per_query_metrics IS NULL` and degrade gracefully (FR-7 + AC-3).
- **Reconciliation / repair strategy:** None — additive nullable column, no data loss on downgrade, no in-flight breaking change.

---

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Migration `0015_trials_per_query_metrics`
- [ ] Story 1.2 — Persist `per_query_metrics` in `run_trial`
- [ ] Story 1.3 — Domain module `confidence.py`
- [x] Story 1.4 — `ConfidenceShape` + StudyDetail enrichment
- [x] Story 1.5 — PR body section + worker plumbing
- [x] Story 1.6 — Digest narrative prompt extension
- [x] **Epic 1 gate**
- [x] Story 2.1 — TypeScript types + enums
- [x] Story 2.2 — `<ConfidencePanel>` component + glossary + page mount
- [x] Story 2.3 — Playwright E2E
- [x] **Epic 2 gate**
- [x] Final state.md + architecture.md update

### Blocked items

(none — feature has all dependencies satisfied)

### Done this sprint

(none yet — implementation has not started)

---

## 10) Story-by-Story Verification Gate

Before marking any story complete, the executing engineer or `/impl-execute` agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables)
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code)
- [ ] Key interfaces implemented with compatible signatures
- [ ] Required tests added/updated for all four layers where applicable
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset with explanation)
  - [ ] `make test-contract`
  - [ ] `cd ui && pnpm test`
  - [ ] `cd ui && pnpm playwright test tests/e2e/studies.spec.ts` (Story 2.3 only)
- [ ] Migration round-trip evidence included (Story 1.1 only)
- [ ] Related docs/checklists updated in same PR when behavior/contract changed

---

## 11) Plan consistency review

### Endpoint count
- Spec §8.1 lists 1 modified endpoint (`GET /api/v1/studies/{id}`).
- Plan covers it in Story 1.4. ✅

### Error code coverage
- Spec §8.5 lists 0 new error codes. ✅
- Plan introduces no new error codes. ✅

### FR coverage
- All 8 FRs (FR-1 through FR-7, with FR-4a separately) appear in §1 traceability table. ✅
- Every FR is assigned to at least one story. ✅

### Story internal consistency
- No file appears in more than one story's "New files" table. ✅
- Every "Modified files" entry exists in the codebase (verified by grep during plan-gen). ✅
- Endpoint table in Story 1.4 matches the Pydantic schemas in the same story. ✅

### Test file count and assignment

**New test files: 7.** (cycle-1 GPT-5.5 F5 fix — original arithmetic mis-stated this.)

| Layer | Path | Story | Case count |
|---|---|---|---|
| Unit | `backend/tests/unit/domain/study/test_confidence.py` | 1.3 | 25+ |
| Integration | `backend/tests/integration/test_trials_per_query_metrics_migration.py` | 1.1 | 3 |
| Integration | `backend/tests/integration/test_run_trial_per_query_persistence.py` | 1.2 | 2 |
| Integration | `backend/tests/integration/test_studies_api_confidence.py` | 1.4 | 11 |
| Integration | `backend/tests/integration/test_open_pr_worker_confidence_plumbing.py` | 1.5 | 1 |
| Contract | `backend/tests/contract/test_pr_body_confidence_section.py` | 1.5 | 4 |
| Component | `ui/src/__tests__/components/studies/confidence-panel.test.tsx` | 2.2 | 12 |

**Modified existing test files: 4.**

| Path | Story | Cases added |
|---|---|---|
| `backend/tests/contract/test_studies_api_contract.py` | 1.4 | 2 (OpenAPI shape lock) |
| `backend/tests/unit/workers/test_digest_prompt_render.py` | 1.6 | 5 (user + system prompt — cycle-1 F10) |
| `backend/tests/integration/_digest_helpers.py` | 1.4 | helper extension (optional `per_query_metrics` + `optuna_trial_number` params); not test cases per se |
| `ui/tests/e2e/studies.spec.ts` + `ui/tests/e2e/helpers/seed.ts` | 2.3 | 2 Playwright cases + new seed helper |

Every test file is owned by exactly one story; no orphans. ✅

### Gate arithmetic
- Epic 1 gate: 6 stories below — gate enumerates exactly 6 stories' completion. ✅
- Epic 2 gate: 3 stories below — gate enumerates 3 stories' completion. ✅

### Open questions resolved
- Spec §19 lists 0 open questions remaining (all 7 preflight questions resolved by Decision Log D1–D10). ✅
- Plan introduces no new open questions. ✅

### Frontend UI Guidance completeness
- Insertion point: documented ✅
- Analogous markup patterns: ✅ (mount pattern, conditional render, badge, InfoTooltip)
- Layout and structure: ✅
- Modal/dialog pattern: N/A — feature has no dialogs
- Visual consistency table: ✅
- Component composition: ✅ (single component, no extraction)
- Interaction behavior table: ✅
- Handler function patterns: N/A — read-only display, no handlers
- Information architecture placement: ✅
- Tooltips and contextual help: ✅ (6 glossary keys, primitive cited)
- Legacy behavior parity: explicitly N/A with citation ✅

### Plan ↔ codebase verification
- Migration path `migrations/versions/` verified (precedent: `0014_clusters_target_filter.py` at that path). ✅
- Current Alembic head `0014_clusters_target_filter` verified via `ls migrations/versions/ | tail -3`. ✅
- Router registration pattern verified at `backend/app/main.py:165-173`. ✅ (no new router this feature)
- `_render_pr_body_study_backed` at `backend/workers/git_pr.py:488` verified during spec-gen. ✅
- `scoring.py:194` return shape verified. ✅
- `trials.py:440` worker write line verified. ✅
- `StudyDetail` Pydantic at `backend/app/api/v1/schemas.py:613` verified. ✅
- `_K_REQUIRED_METRICS` at `schemas.py:521` verified. ✅
- `ObjectiveMetric` Literal at `schemas.py:214` verified. ✅
- `render_digest_user_prompt` at `backend/app/llm/digest_prompt.py:67` verified. ✅

### Infrastructure path verification
- Migration directory: `migrations/versions/` (NOT `backend/app/db/migrations/versions/`) ✅
- Revision numbering: `"0015"` (4-char convention from `0014`) ✅
- Domain module path: `backend/app/domain/study/confidence.py` matches existing pattern `backend/app/domain/study/search_space_defaults.py` from `feat_agent_propose_search_space` ✅
- Test file paths: `backend/tests/unit/domain/study/test_confidence.py` matches the precedent for the search-space-defaults parity test ✅

### Frontend data plumbing verification
- `ConfidencePanel` consumes `study.confidence` — verified that the existing `useStudy` hook returns the full `StudyDetail` shape (after Story 1.4 adds the field) ✅

### Persistence scope consistency
- N/A — feature uses no `localStorage` or `sessionStorage`.

### Enumerated value contract audit
- 3 new wire-enum value arrays added to `ui/src/lib/enums.ts` per Story 2.1, each with a source-of-truth comment citing `backend/app/api/v1/schemas.py`. ✅
- Spec §8.4 enumerated-value-contracts table covers all 4 new Literals + the reused `ObjectiveMetric`. ✅
- ConfidencePanel JSX includes per-branch source-of-truth comments per Story 2.2. ✅

### Admin control audit
- N/A — MVP4+ only. RelyLoop is single-tenant in MVP1.

### Audit-event coverage audit
- N/A — MVP2+ only. RelyLoop has no `audit_log` table yet in MVP1.

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR is mapped to stories/tasks/tests/docs updates (§1).
- [x] Every story includes New files, Modified files, Endpoints (when applicable), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/e2e) are explicitly scoped (§3).
- [x] Documentation updates across docs/01-05 are planned and owned (§4).
- [x] Lean refactor scope is empty by design — explicitly N/A (§5).
- [x] Phase/epic gates are measurable.
- [x] Story-by-Story Verification Gate is included (§10).
- [ ] Plan consistency review (§11) completed with no unresolved findings — pending cross-model review.
