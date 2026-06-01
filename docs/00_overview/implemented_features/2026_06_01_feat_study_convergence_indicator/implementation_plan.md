# Implementation Plan — Study convergence indicator

**Date:** 2026-05-31
**Status:** Complete (PR #352, merged 2026-06-01)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../../CLAUDE.md), [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md), [`docs/01_architecture/ui-architecture.md`](../../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Spec traceability first: every story maps to one or more FRs.
- Single-phase delivery (per spec §3 / D-7); no deferred phases, no `phase2_idea.md`.
- All three engines are read-side neutral — this feature reads the `trials` table only and ships **no adapter changes**.
- The plan is **Opus-only reviewed** at operator request (see Review log §13).

### Name-collision discipline (operator-mandated, first-class concern)

The shipped [`feat_pr_metric_confidence`](../../../implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md) already defines:

- `ConvergenceRegime = Literal["early_held", "late_rising", "noisy"]` at `backend/app/domain/study/confidence.py:117` — classifies *winner-trial-number timing* (when within the run the winner appeared), NOT metric-plateau.
- `CONVERGENCE_MIN_COMPLETE: int = 3` at `confidence.py:102` — minimum trials to compute the existing `ConfidenceShape.convergence.regime`.
- `StudyDetail.confidence.convergence: ConfidenceConvergenceShape` already carries that regime on the same response object this feature touches.

**Implementers MUST NOT redefine `ConvergenceRegime` or `CONVERGENCE_MIN_COMPLETE`.** This feature lives in a **new** module path `backend/app/domain/study/convergence.py` (note the singular `convergence`, not `confidence`) and uses a **dedicated** namespace:

- Type symbol: `ConvergenceVerdict = Literal["converged", "still_improving", "too_few_trials"]`
- Constants: `CONVERGENCE_FLAT_EPSILON` (re-exported from `auto_followup.py::AUTO_FOLLOWUP_LIFT_EPSILON`), `CONVERGENCE_FLAT_WINDOW: int = 20`, `CONVERGENCE_FLAT_MIN_COMPLETE: int = 5`.
- Pydantic field: `StudyDetail.convergence: ConvergenceShape | None` (sibling to, not replacing, `StudyDetail.confidence`).

The two convergence concepts coexist on `StudyDetail` — one keyed off `confidence.convergence.regime` (winner timing), the other off `convergence.verdict` (metric plateau). When grep-ing or auto-completing in editor, implementers MUST verify the module path (`confidence.py` vs `convergence.py`) before importing or asserting against any "convergence" symbol.

### Epsilon-constant hoist discipline (FR-2)

Currently the literal `0.005` is inlined at two sites in `backend/app/domain/study/auto_followup.py`:

- Line 74 — `ChainGateOutcome.epsilon: float = 0.005` (dataclass field default)
- Line 121 — `evaluate_chain_gate(..., epsilon: float = 0.005, ...)` (kwarg default)

**Story 1.1 is dedicated to the hoist** with its own verification gate. After the hoist:

- A new module-level constant `AUTO_FOLLOWUP_LIFT_EPSILON: float = 0.005` lives at the top of `auto_followup.py`.
- Both inline `0.005` literals become `AUTO_FOLLOWUP_LIFT_EPSILON`.
- `convergence.py` re-exports the same value via `from backend.app.domain.study.auto_followup import AUTO_FOLLOWUP_LIFT_EPSILON as CONVERGENCE_FLAT_EPSILON`.

**Verification gate** (per spec FR-2 / AC-17 / D-6 — `is`-identity is explicitly forbidden):

- **Value-equality test** — `AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` AND `CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON == 0.005`. Use `==`, never `is`.
- **AST/grep guard test** — scans every `*.py` under `backend/app/` and fails the test suite if any file (other than `auto_followup.py`'s declaration line at the top of the module) contains a bare `0.005` literal in a context that resembles a convergence/lift epsilon (e.g., as a kwarg default named `epsilon`, as a dataclass-field default named `epsilon`, or as an `==` comparand against a name containing `lift` / `epsilon` / `improvement`).
- **All existing auto-followup tests must remain byte-identical green.** Behavior is unchanged; the hoist is purely a referential refactor.

This story ships **alone in Epic 1**; Stories 1.2 (the classifier) and the rest of the plan depend on the hoist having landed first so they can re-export the constant.

### Cross-PR coordination (FR-7 / AC-16)

AC-16 (autopilot integration) is **conditional on the `feat_overnight_autopilot` PR's CI lane**, NOT this spec's. This plan ships:

- The `ConvergenceVerdict` type symbol (Story 1.2).
- The `fetch_study_convergence(db, study_row)` helper (Story 2.2).
- A documented contract that autopilot's `StudyChainLink` Pydantic model gains an additive optional `convergence_verdict: ConvergenceVerdict | None = None` field (Story 6.1).

This plan does **NOT** wire the autopilot `/chain` endpoint — that wiring lives in the autopilot PR. AC-16 is asserted by autopilot's CI lane against its own integration test suite. Story 6.1's DoD captures the contract definition only; it does not block on AC-16 passing.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (pure classifier) | Epic 1 / Story 1.2 | New `backend/app/domain/study/convergence.py`. AC-1, AC-2, AC-3, AC-6, AC-7. |
| FR-2 (epsilon hoist) | Epic 1 / Story 1.1 | Dedicated story with value-lock + AST/grep guard verification gate. AC-17. |
| FR-3 (read-side aggregator) | Epic 2 / Story 2.1 (repo) + Story 2.2 (service) | New repo helper + new service module mirroring the `study_confidence` precedent. AC-4, AC-5, AC-6, AC-10. |
| FR-4 (StudyDetail integration) | Epic 3 / Story 3.1 | Pydantic field + `_detail` wiring + contract-test extension. AC-8, AC-9, AC-10. |
| FR-5 (ConvergencePanel frontend) | Epic 4 / Story 4.1 (component) + Story 4.2 (mount + enum discipline) | New panel + enum array + value-lock vitest. AC-11, AC-12, AC-13, AC-13b, AC-13c, AC-18, AC-20. |
| FR-6 (digest threading) | Epic 5 / Story 5.1 (worker + user prompt) + Story 5.2 (system prompt) | Worker call site + Jinja `{% if convergence %}` + system-prompt framing rule. AC-14, AC-15. |
| FR-7 (autopilot soft contract) | Epic 6 / Story 6.1 | Export `ConvergenceVerdict`; document the integration contract. NO autopilot-side wiring. AC-16 is autopilot's CI lane. |
| FR-8 (glossary keys) | Epic 4 / Story 4.1 | 3 new entries in `ui/src/lib/glossary.ts`, ≤140-char `short` text each. Referenced by AC-19. |
| FR-9 (runbook + CLAUDE.md row) | Epic 7 / Story 7.1 | `docs/03_runbooks/convergence-verdict.md` + CLAUDE.md "Key Runbooks" table row + glossary "Learn more" anchor. AC-19. |

**Phase coverage:** Single-phase spec — all 9 FRs ship in this plan. No deferred phases; **no `phase2_idea.md` to create.** (Confirmed: `ls docs/00_overview/planned_features/02_mvp2/feat_study_convergence_indicator/` shows only `idea.md`, `feature_spec.md`, `pipeline_status.md`.)

## 2) Delivery structure — Epic → Story → Tasks → DoD

### Conventions (project-specific)

- Repo functions take `db: AsyncSession` first; use `db.flush()`; caller commits. Export via `__all__`.
- Services are `async` and accept `db: AsyncSession` + typed args; no business-table mutation in this feature (read-side only).
- Domain layer is pure — `convergence.py` has no DB, no I/O, no `async`.
- Pydantic schemas live in `backend/app/api/v1/schemas.py`; nested shapes may be defined in the owning domain module and re-imported (precedent: `ConfidenceShape`).
- Frontend uses shadcn primitives (`<Card>`, `<Badge>`), TanStack Query, Recharts, `<InfoTooltip glossaryKey="...">`.
- Enum wire values live in `ui/src/lib/enums.ts` with the source-of-truth comment per CLAUDE.md "Enumerated Value Contract Discipline."
- All new code carries SPDX headers.

### AI Agent Execution Protocol (applies to every story)

0. Load context: re-read `architecture.md`, `state.md`, and the spec's relevant FR + ACs before starting.
1. Read scope: verify story outcome + endpoints + interfaces + DoD.
2. Implement backend first: domain → repo → service → schema → router wiring.
3. Run backend tests (unit + integration + contract for touched surface).
4. Implement frontend (Epic 4).
5. Run frontend vitest + the one Playwright smoke (Epic 4 Story 4.2 DoD).
6. Update docs in the same PR (Epic 7).
7. Verify no migration needed — this feature reads existing columns only.
8. Attach evidence: commands run, pass/fail, files changed.
9. After the final story, update `state.md` (last-5-merges + alembic head check) and `architecture.md` (mount-point note in `ui-architecture.md`).

---

## Epic 1 — Domain foundation (epsilon hoist + pure classifier)

### Story 1.1 — Hoist `0.005` to `AUTO_FOLLOWUP_LIFT_EPSILON` (FR-2)

**Outcome:** The convergence-vs-lift epsilon lives at a single named module-level constant. Existing `evaluate_chain_gate` behavior is byte-identical. The constant is importable from `auto_followup.py` and re-exportable from the new `convergence.py`.

**New files**

| File | Purpose |
|---|---|
| _(none)_ | This story is a referential refactor. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/auto_followup.py` | Add module-level `AUTO_FOLLOWUP_LIFT_EPSILON: float = 0.005` near the top of the file (above `ChainGateOutcome`). Change `ChainGateOutcome.epsilon: float = 0.005` at line 74 to `epsilon: float = AUTO_FOLLOWUP_LIFT_EPSILON`. Change `evaluate_chain_gate(..., epsilon: float = 0.005, ...)` at line 121 to `epsilon: float = AUTO_FOLLOWUP_LIFT_EPSILON`. No other lines change. |
| `backend/tests/unit/domain/study/test_auto_followup.py` | Add a value-lock test asserting `AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` and that the dataclass + kwarg defaults match it (value-equality `==`, NEVER `is`). |

**Key interfaces**

```python
# backend/app/domain/study/auto_followup.py — new module constant
AUTO_FOLLOWUP_LIFT_EPSILON: float = 0.005
```

**Tasks**

1. Add the module-level constant in `auto_followup.py` directly under the imports block / module docstring.
2. Replace both inline `0.005` defaults (line 74 dataclass field, line 121 kwarg) with `AUTO_FOLLOWUP_LIFT_EPSILON`.
3. Run `make test-unit` — every existing `test_auto_followup.py` assertion MUST stay green without edits.
4. Add the value-lock test (one assertion block).
5. Note: the **AST/grep guard test** lives with Story 1.2 (next to the classifier tests) because it depends on `convergence.py` existing as the second legitimate consumer; the hoist alone leaves the literal in only one place (`auto_followup.py`'s declaration).

**Definition of Done (DoD)**

- [ ] `AUTO_FOLLOWUP_LIFT_EPSILON` declared exactly once in `auto_followup.py`.
- [ ] Both inline `0.005` defaults removed; only the named constant remains in `auto_followup.py`.
- [ ] Unit test asserts `AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` using value equality.
- [ ] `make test-unit` passes (every pre-existing auto-followup test stays green — no behavioral drift).
- [ ] `make lint && make typecheck` clean.

### Story 1.2 — `ConvergenceShape` + `classify_convergence(...)` pure classifier (FR-1)

**Outcome:** Pure-domain classifier deterministically returns `ConvergenceShape | None` for any sequence of trials per the §9 decision matrix. New module `backend/app/domain/study/convergence.py` is the single source of truth for `ConvergenceVerdict`, `ConvergenceShape`, `CurvePoint`, `CONVERGENCE_FLAT_WINDOW`, `CONVERGENCE_FLAT_MIN_COMPLETE`, and re-exports `CONVERGENCE_FLAT_EPSILON`.

**Name-collision discipline reminder**

This module is `convergence.py` (singular), NOT `confidence.py`. It introduces brand-new names — `ConvergenceVerdict`, `ConvergenceShape`, `CONVERGENCE_FLAT_EPSILON`, `CONVERGENCE_FLAT_WINDOW`, `CONVERGENCE_FLAT_MIN_COMPLETE`. **Do NOT** import or shadow `confidence.py`'s `ConvergenceRegime` or `CONVERGENCE_MIN_COMPLETE` — those mean different things (winner-trial timing, not metric plateau).

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/convergence.py` | Pure-domain module: constants, `ConvergenceVerdict` Literal, `CurvePoint` + `ConvergenceShape` Pydantic models, `classify_convergence(...)` function. |
| `backend/tests/unit/domain/study/test_convergence.py` | Unit tests for §9 decision matrix + monotonicity invariant + boundary cases + value-lock + AST/grep guard. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/__init__.py` | (optional) — only if the existing convention exports domain symbols. Inspect at impl time; don't add an `__all__` block unless one exists. |

**Key interfaces**

```python
# backend/app/domain/study/convergence.py — pure domain (no DB, no I/O, no async)
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel

from backend.app.domain.study.auto_followup import (
    AUTO_FOLLOWUP_LIFT_EPSILON as CONVERGENCE_FLAT_EPSILON,
)
from backend.app.eval.optuna_runtime import STUDIES_TPE_WARMUP_FLOOR

CONVERGENCE_FLAT_WINDOW: int = 20
CONVERGENCE_FLAT_MIN_COMPLETE: int = 5

ConvergenceVerdict = Literal["converged", "still_improving", "too_few_trials"]


class CurvePoint(BaseModel):
    trial_number: int
    best_so_far: float


class ConvergenceShape(BaseModel):
    verdict: ConvergenceVerdict
    direction: Literal["maximize", "minimize"]
    window_size: int
    epsilon: float
    warmup_floor: int
    total_complete_trials: int
    improvement_in_window: float
    best_so_far_curve: list[CurvePoint]


def classify_convergence(
    complete_trials: Sequence[Any],
    *,
    direction: Literal["maximize", "minimize"],
) -> ConvergenceShape | None: ...
```

Algorithm (matches spec §9 / Window-indexing semantic at line 458 / FR-1 invariants):

1. Filter input: keep only `t.status == "complete" AND t.is_baseline is False AND t.primary_metric is not None`. Sort by `optuna_trial_number ASC`.
2. If filtered count `< CONVERGENCE_FLAT_MIN_COMPLETE` (5) → return `None`.
3. Build the best-so-far curve via running max (`direction="maximize"`) or running min (`direction="minimize"`).
4. `window_size = min(CONVERGENCE_FLAT_WINDOW, max(5, total_complete_trials // 5))`.
5. `improvement_in_window = curve[-1].best_so_far - curve[-window_size].best_so_far` (maximize) or sign-flipped (minimize). Always `>= 0`.
6. Decision matrix (first match wins):
   - `total_complete_trials < STUDIES_TPE_WARMUP_FLOOR` (50) → `verdict = "too_few_trials"`.
   - `improvement_in_window <= CONVERGENCE_FLAT_EPSILON` → `verdict = "converged"`.
   - Else → `verdict = "still_improving"`.
7. Return populated `ConvergenceShape` (all sub-fields, never `None`).

**Tasks**

1. Create `backend/app/domain/study/convergence.py` with SPDX header + the constants/types/Pydantic shapes above.
2. Implement `classify_convergence(...)` per the algorithm.
3. Write `test_convergence.py` covering every case in §14 of the spec:
   - All four decision-matrix branches (converged / still_improving / too_few_trials / None).
   - Direction-aware minimize.
   - `is_baseline=True` filtering (mixed set including a baseline row with `optuna_trial_number=-1`).
   - `primary_metric IS NULL` defensive filter.
   - Window-clamp boundary cases at N ∈ {5, 7, 24, 49, 50, 51, 100, 200, 1000}.
   - Slow-drift case (200 trials, each window-step gains 0.004, below epsilon → `converged`).
   - Single-late-jump case (200 flat + 1 trial gaining 0.05 → `still_improving`).
   - Noisy-tail case (100 baseline + 20 noisy near a fixed best → `converged`).
   - Monotonicity invariant: every emitted `best_so_far_curve` is monotonic in the right direction.
4. Add the **value-lock test**: `CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON == 0.005` using `==`.
5. Add the **AST/grep guard test** in the same file. Open every `*.py` under `backend/app/`, parse with `ast`, walk for any module that contains a bare `0.005` float-constant in a context resembling a lift/convergence epsilon (kwarg default named `epsilon`, dataclass field default named `epsilon`, `==` comparand against a name containing `lift` / `epsilon` / `improvement`). Allow exactly ONE site: `backend/app/domain/study/auto_followup.py`'s `AUTO_FOLLOWUP_LIFT_EPSILON = 0.005` declaration line. Any other match fails the test.

**Definition of Done (DoD)**

- [ ] `classify_convergence(...)` deterministic — same input yields same output across 100 calls (asserted by a property-style test).
- [ ] Every §9 decision-matrix branch covered by a dedicated unit test.
- [ ] Monotonicity invariant asserted for both directions.
- [ ] Window-clamp boundary tests at all 9 listed N values pass.
- [ ] Value-lock test green: `CONVERGENCE_FLAT_EPSILON == AUTO_FOLLOWUP_LIFT_EPSILON == 0.005`.
- [ ] AST/grep guard test green: zero stray `0.005` literals in `backend/app/` outside `auto_followup.py`'s declaration line.
- [ ] `make test-unit` + `make lint` + `make typecheck` clean.

---

## Epic 2 — Repo + service aggregator (read-side)

### Story 2.1 — Repo helper `list_complete_optuna_trials_for_study` (FR-3)

**Outcome:** A single SELECT pushes the `status = 'complete' AND is_baseline = FALSE AND primary_metric IS NOT NULL` filter into SQL and orders by `optuna_trial_number ASC`. Existing `list_trials_for_study` is unchanged.

**New files**

| File | Purpose |
|---|---|
| _(none)_ | New function added to existing `trial.py`. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/trial.py` | Add `async def list_complete_optuna_trials_for_study(db: AsyncSession, study_id: str) -> Sequence[Trial]` after `list_trials_for_study`. SQL: `SELECT * FROM trials WHERE study_id=:id AND status='complete' AND is_baseline IS FALSE AND primary_metric IS NOT NULL ORDER BY optuna_trial_number ASC`. |
| `backend/app/db/repo/__init__.py` | Export the new function via `__all__` (or whatever the existing convention is — inspect first). |

**Key interfaces**

```python
# backend/app/db/repo/trial.py
async def list_complete_optuna_trials_for_study(
    db: AsyncSession, study_id: str
) -> Sequence[Trial]: ...
```

**Tasks**

1. Add the new repo function alongside `list_trials_for_study`.
2. Export from `repo/__init__.py`.
3. Write an integration test under `backend/tests/integration/test_trial_repo.py` (or extend existing file): seed a study with 50 Optuna trials + 1 baseline + 2 failed + 1 pruned + 1 complete-but-`primary_metric=None` → assert the helper returns exactly the 50 usable Optuna trials, sorted ASC by `optuna_trial_number`.

**Definition of Done (DoD)**

- [ ] Helper returns SQL-filtered rows (verified by integration test on the mixed seed).
- [ ] Ordering is `optuna_trial_number ASC`.
- [ ] No `primary_metric IS NULL`, no `is_baseline=True`, no non-`complete` rows in the result.
- [ ] `__init__.py` exports updated.
- [ ] `make test-integration` includes the new test and passes.

### Story 2.2 — Service `fetch_study_convergence` + direction resolver + WARN logging (FR-3)

**Outcome:** `_detail()` can call `fetch_study_convergence(db, row)` and get `ConvergenceShape | None`. The function handles in-flight short-circuit, invalid-direction graceful degrade, and classifier-exception graceful degrade — and never crashes the underlying GET.

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/study_convergence.py` | Async glue mirroring `services/study_confidence.py`: resolve direction, load trials via Story 2.1 helper, call `classify_convergence`, handle null + exception paths. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/__init__.py` | (optional — only if existing convention re-exports services; check first.) |

**Key interfaces**

```python
# backend/app/services/study_convergence.py
async def fetch_study_convergence(
    db: AsyncSession, study_row: Study
) -> ConvergenceShape | None: ...


def _resolve_direction(
    objective: dict[str, Any] | None,
) -> Literal["maximize", "minimize"] | None: ...
```

Logic (matches spec FR-3):

1. If `study_row.status in ("queued", "running")` → return `None` (no in-flight classification).
2. Resolve direction via `_resolve_direction(study_row.objective)`. Default `"maximize"` when the key is absent (precedent: `studies.py:165`). Return `None` for any other string.
3. If direction resolution returned `None` → emit structured WARN (`event_type="convergence_invalid_direction"`, `study_id=`, `raw_direction=`) and return `None`.
4. Load trials via `repo.list_complete_optuna_trials_for_study(db, study_row.id)`.
5. Wrap `classify_convergence(trials, direction=direction)` in `try/except Exception`. On exception: emit structured WARN (`event_type="convergence_classifier_exception"`, `study_id=`, `exception_type=`, `exception_str=`) and return `None`.
6. On success: emit DEBUG (`event_type="convergence_classified"`, `study_id=`, `verdict=`, `total_complete_trials=`, `window_size=`, `improvement_in_window=`) and return the shape.

**Tasks**

1. Create `study_convergence.py` with SPDX header + the function above. Use `structlog.get_logger(__name__)` matching the codebase convention.
2. Write integration test at `backend/tests/integration/test_study_convergence_integration.py`:
   - Seed completed study + 275 converged trials → assert returned shape has `verdict="converged"`.
   - Seed running study + 80 complete trials → assert `None`, classifier NOT invoked (monkeypatch + spy).
   - Seed completed study + 4 complete trials → assert `None`.
   - Seed completed study + 50 Optuna + 1 baseline → assert `total_complete_trials == 50`, no `trial_number == -1` in curve.
   - Seed completed study with `objective={"direction": "minimize"}` + 200 minimize-converged trials → assert `verdict="converged"` with monotonic non-increasing curve.
   - Seed completed study with `objective={"direction": "max"}` (invalid) → assert `None` + WARN log captured + classifier NOT invoked.
   - Monkeypatch `classify_convergence` to raise `ValueError` → assert `None` + WARN log captured + GET still succeeds (covered in Epic 3 contract test).

**Definition of Done (DoD)**

- [ ] In-flight short-circuit verified (classifier spy never called).
- [ ] Invalid `direction` returns `None` + emits `convergence_invalid_direction` WARN.
- [ ] Classifier exception returns `None` + emits `convergence_classifier_exception` WARN.
- [ ] Success path emits DEBUG `convergence_classified`.
- [ ] Integration test for all six scenarios above passes.

---

## Epic 3 — Wire `convergence` into the StudyDetail response

### Story 3.1 — Extend `StudyDetail` Pydantic + `_detail` builder + contract test (FR-4)

**Outcome:** `GET /api/v1/studies/{id}` and `POST /api/v1/studies/{id}/cancel` both return `convergence: ConvergenceShape | None` (additive, default-None). Contract test asserts the shape on the OpenAPI surface.

**No new endpoints.** Per spec §8.1 + D-5: convergence rides in the existing detail/cancel responses; no new route.

**New files**

| File | Purpose |
|---|---|
| _(none)_ | Pure additive extension. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `from backend.app.domain.study.convergence import ConvergenceShape as ConvergenceShape` (named re-export to satisfy mypy `no_implicit_reexport`, matching the `ConfidenceShape` precedent at line 31). Add `convergence: ConvergenceShape \| None = None` on `StudyDetail` (line ~818, immediately after `confidence`). Docstring: "Per-study convergence verdict (feat_study_convergence_indicator FR-4). `None` for in-flight studies, sub-MIN trial counts, or graceful-degrade null paths from FR-3." |
| `backend/app/api/v1/studies.py` | At line 127 (`_detail` body), add `convergence = await fetch_study_convergence(db, row)` after the confidence fetch. Pass `convergence=convergence` into the `StudyDetail(...)` constructor (immediately after `confidence=confidence,` at line 157). Import `fetch_study_convergence` from `backend.app.services.study_convergence`. |
| `backend/tests/contract/test_studies_api_contract.py` | Extend the existing `StudyDetail` shape assertions (lines 80–88 pattern): assert `"convergence"` is a key in the schema, typed `Optional[ConvergenceShape]`. Add a new sub-test asserting the JSON-schema sub-fields on `ConvergenceShape` match §8.3 exactly (`verdict`, `direction`, `window_size`, `epsilon`, `warmup_floor`, `total_complete_trials`, `improvement_in_window`, `best_so_far_curve`). |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/studies/{id}` | — | `200` — existing `StudyDetail` body PLUS `convergence: ConvergenceShape \| None` | `STUDY_NOT_FOUND` (404, unchanged) |
| `POST` | `/api/v1/studies/{id}/cancel` | (existing) | `200` — existing `StudyDetail` body PLUS `convergence` populated against the now-cancelled study | (unchanged — `InvalidStateTransition` etc. all pre-existing) |

Error envelope shape (unchanged): `{ "detail": { "error_code": "STUDY_NOT_FOUND", "message": "study <id> not found", "retryable": false } }`. Auth: N/A — MVP2 has no auth surface.

**Tasks**

1. Add the named re-import + `convergence` field on `StudyDetail` in `schemas.py`.
2. Wire the fetch into `_detail` in `studies.py` (single line addition + constructor kwarg).
3. Extend the contract test with the shape + sub-field assertions.
4. Write integration test verifying AC-8, AC-9, AC-10:
   - Completed study with 275 trials → GET returns `convergence.verdict == "converged"`, full curve length 275.
   - Running study → GET returns `convergence == null`.
   - Running study with 80 complete trials → POST `.../cancel` succeeds, response carries populated `convergence` (likely `still_improving` or `too_few_trials` depending on curve shape).

**Definition of Done (DoD)**

- [ ] `StudyDetail` JSON schema carries `convergence: ConvergenceShape | None`.
- [ ] Contract test asserts every §8.3 sub-field with the correct type.
- [ ] Integration tests for AC-8, AC-9, AC-10 pass.
- [ ] Classifier-exception path verified end-to-end: monkeypatch raises → GET returns `200` with `convergence: null` (not `500`).
- [ ] `make test-contract` + `make test-integration` pass.

---

## Epic 4 — Frontend: `<ConvergencePanel>` + glossary + enum discipline

### Story 4.1 — `<ConvergencePanel>` component + 3 glossary keys (FR-5 + FR-8)

**Outcome:** New React component renders the verdict badge (always visible), the improvement-in-window summary line, and a collapsible Recharts curve. Three new glossary entries with `≤140`-char `short` text drive the three `<InfoTooltip>` instances.

**Name-collision discipline reminder (frontend)**

The existing `<ConfidencePanel>` at `ui/src/components/studies/confidence-panel.tsx` already imports + maps `ConvergenceRegime` (winner-timing). The new `<ConvergencePanel>` lives in a different file and consumes a different wire field. **Do NOT** re-use the existing `CONVERGENCE_BADGE` mapping or import it — the verdict values (`converged` / `still_improving` / `too_few_trials`) are different from the regime values (`early_held` / `late_rising` / `noisy`).

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/studies/convergence-panel.tsx` | Pure component consuming `convergence: ConvergenceShape \| null`, `studyStatus: StudyStatusWire`, `trialsSummary: TrialsSummaryShape`. Renders badge + improvement line + collapsible curve. |
| `ui/src/__tests__/components/studies/convergence-panel.test.tsx` | Vitest covering AC-11 / AC-12 / AC-13 / AC-13b / AC-13c / AC-20 (a11y label). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/glossary.ts` | Add 3 new entries with `short` text (max 140 chars each, copy from spec §11 tooltips table / FR-8): `convergence_verdict`, `convergence_curve`, `convergence_window`. The `convergence_verdict` entry MUST carry a `long` field or "Learn more" href pointing at the runbook `docs/03_runbooks/convergence-verdict.md` (or the rendered equivalent) so AC-19 passes. Use the existing `// Source-of-truth: backend/app/domain/study/convergence.py ConvergenceVerdict` comment shape immediately above the new entries. |

**Pydantic schemas (frontend mirror)**

```ts
// Consumed via the auto-generated `components['schemas']['ConvergenceShape']` after
// the OpenAPI regeneration; no manual TypeScript interface needed beyond the prop type.
import type { components } from '@/lib/types';
type ConvergenceShape = components['schemas']['ConvergenceShape'];
```

**UI element inventory**

| Element | Type | Label / source | Behavior |
|---|---|---|---|
| Card | `<Card data-testid="convergence-panel">` | static | always rendered when component mounts |
| Card title | `<CardTitle>Convergence</CardTitle>` + `<InfoTooltip glossaryKey="convergence_verdict" />` | static | tooltip on hover/focus |
| Verdict badge | `<Badge variant=... data-testid="cs-convergence-verdict" aria-label={...}>{label}</Badge>` | mapping table | always visible; variant maps to verdict per spec §4 canonical copy table |
| Improvement line | `<p>Improved by {improvement_in_window} in the last {window_size} trials</p>` + `<InfoTooltip glossaryKey="convergence_window" />` | shape | only renders when `convergence !== null` |
| Collapsible section | `<details>` + `<summary>Show convergence curve <InfoTooltip glossaryKey="convergence_curve" /></summary>` | static | `open` attribute set when `verdict !== "converged"` (or null path) |
| Curve | Recharts `<ResponsiveContainer><LineChart><CartesianGrid/><XAxis/><YAxis/><Tooltip/><Line/><ReferenceArea/></LineChart></ResponsiveContainer>` | `best_so_far_curve` | `<ReferenceArea>` shades the right-most `window_size` trials when `verdict ∈ {converged, still_improving}`; `aria-label` on the container per AC-20 |
| Em-dash placeholder | `<p>—</p>` | static | renders inside the details body when `convergence === null` (in-flight or sub-MIN); no chart mounted |

**Badge mapping (matches spec §4 canonical copy table)**

```ts
// Values must match backend/app/domain/study/convergence.py ConvergenceVerdict.
// Note: distinct from CONVERGENCE_BADGE in confidence-panel.tsx (different concept).
const VERDICT_BADGE: Record<
  ConvergenceShape['verdict'],
  { label: string; variant: 'success' | 'warning' }
> = {
  converged: { label: 'Converged', variant: 'success' },
  still_improving: { label: 'Still improving when it stopped', variant: 'warning' },
  too_few_trials: { label: 'Too few trials to tell', variant: 'warning' },
};
```

Three null-state mappings (per spec §4 + AC-13/13b/13c):

- `convergence === null && studyStatus in {"queued","running"}` → label `"Verdict pending — still running"`, variant `neutral`.
- `convergence === null && studyStatus is terminal && trialsSummary.complete < 5` → label `"Verdict pending — not enough trials yet"`, variant `neutral`.
- `convergence === null && studyStatus is terminal && trialsSummary.complete >= 5` → label `"Verdict unavailable"`, variant `neutral`.

**Analogous markup patterns (copy-paste reference)**

```tsx
{/* Card + InfoTooltip header — from ui/src/components/studies/confidence-panel.tsx:60-73 */}
<Card data-testid="convergence-panel">
  <CardHeader>
    <CardTitle className="text-base flex items-center gap-1">
      Convergence
      <InfoTooltip glossaryKey="convergence_verdict" />
    </CardTitle>
  </CardHeader>
  <CardContent className="space-y-4">
    {/* badge + improvement line + collapsible curve */}
  </CardContent>
</Card>
```

```tsx
{/* Recharts ResponsiveContainer + LineChart — adapted from
    ui/src/components/common/parameter-importance-chart.tsx:25-35 */}
<div
  data-testid="convergence-curve"
  style={{ width: '100%', height: 240 }}
  aria-label={`Convergence curve: ${verdict} after ${total_complete_trials} trials; window ${window_size}; improvement ${improvement_in_window.toFixed(4)}`}
>
  <ResponsiveContainer width="100%" height="100%">
    <LineChart data={best_so_far_curve} margin={{ top: 8, right: 16, bottom: 8, left: 24 }}>
      <CartesianGrid strokeDasharray="3 3" />
      <XAxis dataKey="trial_number" type="number" />
      <YAxis type="number" />
      <Tooltip formatter={(value: number) => value.toFixed(4)} />
      <Line type="monotone" dataKey="best_so_far" stroke="#3b82f6" dot={false} />
      {(verdict === 'converged' || verdict === 'still_improving') && (
        <ReferenceArea
          x1={best_so_far_curve[best_so_far_curve.length - window_size].trial_number}
          x2={best_so_far_curve[best_so_far_curve.length - 1].trial_number}
          strokeOpacity={0}
          fillOpacity={0.08}
          fill="#3b82f6"
        />
      )}
    </LineChart>
  </ResponsiveContainer>
</div>
```

```tsx
{/* InfoTooltip pattern — from ui/src/components/studies/confidence-panel.tsx:77-78 */}
<p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
  Improved by {improvement_in_window.toFixed(4)} in the last {window_size} trials
  <InfoTooltip glossaryKey="convergence_window" />
</p>
```

**Tooltip inventory (matches spec §11)**

| Element | Glossary key | Source-of-truth comment target |
|---|---|---|
| Panel title `(i)` icon | `convergence_verdict` | `backend/app/domain/study/convergence.py ConvergenceVerdict` |
| Curve collapsible header `(i)` icon | `convergence_curve` | `backend/app/domain/study/convergence.py (FR-1 algorithm)` |
| `window_size` subscript `(i)` icon | `convergence_window` | `backend/app/domain/study/convergence.py CONVERGENCE_FLAT_WINDOW` |

**Tasks**

1. Add the 3 glossary entries to `ui/src/lib/glossary.ts` with `short` ≤140 chars each (use spec FR-8 verbatim copy). Add `long` or "Learn more" anchor to `convergence_verdict` pointing at the runbook.
2. Create `convergence-panel.tsx` per the markup patterns above. Use the `VERDICT_BADGE` mapping with the source-of-truth comment.
3. Write `convergence-panel.test.tsx`:
   - AC-11 — converged → badge label "Converged", variant success, `<details>` has no `open` attribute, `data-testid="cs-convergence-verdict"` present, aria-label mirrors verdict.
   - AC-12 — still_improving → `<details>` has `open` attribute.
   - AC-13 — `convergence === null && studyStatus === 'running'` → badge "Verdict pending — still running", em-dash in body, NO Recharts mount (assert via testing-library `queryByTestId('convergence-curve')` is `null`).
   - AC-13b — `convergence === null && status === 'completed' && trialsSummary.complete === 4` → "Verdict pending — not enough trials yet".
   - AC-13c — `convergence === null && status === 'completed' && trialsSummary.complete === 100` → "Verdict unavailable".
   - AC-20 — converged shape → curve `aria-label` reads exactly `"Convergence curve: converged after 275 trials; window 20; improvement 0.0008"`.
4. Glossary value-lock test (existing pattern at `ui/src/__tests__/lib/glossary*.test.ts`): assert the 3 new keys exist and `short` length ≤140 chars.

**Definition of Done (DoD)**

- [ ] All 6 vitest cases above pass.
- [ ] Glossary entries have `short` ≤140 chars; `convergence_verdict` has `long`/href pointing at the runbook.
- [ ] No `<select>` or filter introduced — the panel renders only static badges + chart. (Therefore no `as const` enum array is required from this story; Story 4.2 covers the enum-discipline value-lock for the badge mapping.)

### Story 4.2 — Mount `<ConvergencePanel>` on `/studies/[id]` + enum-discipline value-lock (FR-5 + AC-18)

**Outcome:** Panel mounts between `<ConfidencePanel>` and `<TrialsCard>` at the correct line; `CONVERGENCE_VERDICT_VALUES` lives in `ui/src/lib/enums.ts` with the discipline comment + value-lock vitest. One Playwright real-backend smoke spec ships per spec §14.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/lib/enums-convergence-discipline.test.ts` | Vitest asserting `CONVERGENCE_VERDICT_VALUES.length === 3` AND values are exactly `['converged', 'still_improving', 'too_few_trials']` in that order. |
| `ui/tests/e2e/convergence-panel.spec.ts` | One lightweight real-backend Playwright smoke (spec §14 FR-11 — NO `page.route()`). Seeds two studies via API helpers (one converged, one still_improving), navigates via `page.goto`, asserts the badge text + `data-testid="cs-convergence-verdict"` + `<details>` open state. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/enums.ts` | Add `// Values must match backend/app/domain/study/convergence.py ConvergenceVerdict.` then `export const CONVERGENCE_VERDICT_VALUES = ['converged', 'still_improving', 'too_few_trials'] as const;` plus `export type ConvergenceVerdict = (typeof CONVERGENCE_VERDICT_VALUES)[number];`. |
| `ui/src/app/studies/[id]/page.tsx` | Insert `<ConvergencePanel convergence={study.convergence ?? null} studyStatus={study.status} trialsSummary={study.trials_summary} />` between line 110 (`<ConfidencePanel ...>`) and line 111 (`<TrialsCard ...>`). Import the component. |

**Tasks**

1. Add `CONVERGENCE_VERDICT_VALUES` array + type to `ui/src/lib/enums.ts` with the discipline comment.
2. Add the value-lock vitest asserting length === 3 and the exact array contents per AC-18.
3. Insert the mount on `page.tsx` at the precise location (between `<ConfidencePanel>` at line 110 and `<TrialsCard>` at line 111).
4. Add a companion **backend** value-lock test (extends `test_convergence.py` from Story 1.2): assert the Python `Literal["converged", "still_improving", "too_few_trials"]` has those exact members via `typing.get_args(ConvergenceVerdict)`.
5. Write the Playwright smoke at `ui/tests/e2e/convergence-panel.spec.ts`. Setup via API helpers (use the existing `helpers/` pattern). Anchor on `signup_flow.spec.ts` style — real backend, real `page.goto`, real DOM assertions. No `page.route()`. Two scenarios in one spec: converged study → collapsed; still_improving study → expanded.

**Definition of Done (DoD)**

- [ ] Frontend value-lock vitest passes (AC-18).
- [ ] Backend value-lock test asserts the Literal members match.
- [ ] Mount is at the correct location (visual smoke via the Playwright spec).
- [ ] Playwright smoke spec green against the real backend.
- [ ] `cd ui && pnpm test` + `pnpm typecheck` + `pnpm lint` clean.

---

## Epic 5 — Digest worker + prompts integration

### Story 5.1 — Thread `convergence` through worker + user prompt (FR-6)

**Outcome:** The digest worker fetches the convergence shape, dumps it via Pydantic, and passes it to `render_digest_user_prompt(..., convergence=...)`. The Jinja user template gains a `{% if convergence %}` block following the existing `{% if confidence %}` precedent.

**Modified files**

| File | Change |
|---|---|
| `backend/app/llm/digest_prompt.py` | Add `convergence: dict \| None = None` to `render_digest_user_prompt(...)` signature (after the existing `confidence` parameter, line 116). Pass `convergence=convergence` to the Jinja `template.render(...)` call (line 148 block — extend the kwargs). Update docstring with a new "convergence" entry mirroring the "confidence" entry. |
| `backend/workers/digest.py` | At line 944 (immediately after `confidence_shape = await fetch_study_confidence(db, study)` and the `confidence_payload` derivation), add `convergence_shape = await fetch_study_convergence(db, study)` + `convergence_payload = convergence_shape.model_dump() if convergence_shape is not None else None`. Pass `convergence=convergence_payload` into `render_digest_user_prompt(...)` (line 948 block — extend the kwargs). Add import for `fetch_study_convergence` next to the existing `fetch_study_confidence` import at line 91. |
| `prompts/digest_narrative.user.jinja` | Add a `{% if convergence %}<convergence>...</convergence>{% endif %}` block following the existing `{% if confidence %}` precedent. Block content: `<verdict>{{ convergence.verdict }}</verdict><direction>{{ convergence.direction }}</direction><window_size>{{ convergence.window_size }}</window_size><total_complete_trials>{{ convergence.total_complete_trials }}</total_complete_trials><improvement_in_window>{{ convergence.improvement_in_window }}</improvement_in_window>`. (The curve is NOT rendered in the prompt — only the verdict + small numerics; full curve would inflate tokens.) |

**Tasks**

1. Extend `render_digest_user_prompt(...)` signature + docstring + Jinja render kwargs.
2. Add the `{% if convergence %}` block to the Jinja template.
3. Wire the worker call site to fetch + dump + pass.
4. Write an integration test under `backend/tests/integration/test_digest_worker_convergence.py` (or extend an existing digest worker test):
   - Seed a still_improving study → run the worker → assert `render_digest_user_prompt` is called with a non-None `convergence` kwarg containing `{"verdict": "still_improving", ...}` (use `monkeypatch` to patch + spy on the renderer).
   - Render the user prompt against the same convergence payload → assert the output contains `<convergence>` + `<verdict>still_improving</verdict>`.

**Definition of Done (DoD)**

- [ ] AC-14 passes: spy confirms `convergence=` kwarg flows through with the correct payload AND the rendered prompt contains the `<convergence><verdict>` block.
- [ ] When the aggregator returns `None`, the prompt renders without the `<convergence>` block (existing `{% if confidence %}` precedent — graceful degrade).
- [ ] `make test-integration` passes.

### Story 5.2 — Digest system prompt framing rule (FR-6)

**Outcome:** The digest system prompt instructs the LLM to lead with "re-run with a larger trial budget" when `convergence.verdict ∈ {still_improving, too_few_trials}` and demote narrow/widen to secondary.

**Modified files**

| File | Change |
|---|---|
| `prompts/digest_narrative.system.md` | Add a new section: "**Convergence-aware lead recommendation.** When the `<convergence><verdict>` element is `still_improving` or `too_few_trials`, lead the recommendation with 're-run with a larger trial budget' and frame any `narrow` / `widen` followups as secondary. When `<verdict>` is `converged` or absent, follow the existing recommendation framing without modification." Place this section adjacent to the existing recommendation-framing guidance. |

**Tasks**

1. Patch `digest_narrative.system.md` with the framing rule.
2. Add a unit test under `backend/tests/unit/llm/test_digest_prompt.py` (or wherever existing prompt-string tests live) asserting the rendered system prompt contains BOTH the substring `"still_improving"` AND the substring `"re-run with a larger trial budget"` (AC-15).

**Definition of Done (DoD)**

- [ ] AC-15 passes: system prompt string contains both required substrings.
- [ ] No behavioral change for converged or null verdicts (existing tests stay green).

---

## Epic 6 — Cross-PR contract for autopilot (FR-7)

### Story 6.1 — Export `ConvergenceVerdict` + document the autopilot integration contract (FR-7)

**Outcome:** `ConvergenceVerdict` is re-exportable from `backend.app.domain.study.convergence`. The autopilot PR (lands separately) consumes it for its `StudyChainLink.convergence_verdict: ConvergenceVerdict | None = None` additive field. This plan's PR does NOT modify `StudyChainLink` — that wiring lives in the autopilot PR.

**Cross-PR coordination scope reminder**

- **This PR ships:** the type symbol + helper. Story 6.1 verifies the symbol is importable + documents the contract.
- **This PR does NOT ship:** the `StudyChainLink` field, the per-link `fetch_study_convergence` call in the autopilot `/chain` endpoint, AC-16 assertion.
- **Autopilot PR ships:** the field, the call site, AC-16 in its own CI lane.

**New files**

| File | Purpose |
|---|---|
| _(none)_ | Documentation-only story; the type is already exported by Story 1.2. |

**Modified files**

| File | Change |
|---|---|
| `docs/00_overview/planned_features/02_mvp2/feat_study_convergence_indicator/feature_spec.md` | No edit — the spec already documents the contract in FR-7. |
| `architecture.md` (in the Documentation workstream §11) | Patch the `ui-architecture.md` note (when Epic 7 lands) to mention the `<ConvergencePanel>` mount + the autopilot soft contract. |

**Tasks**

1. Verify `ConvergenceVerdict` is exported from `backend/app/domain/study/convergence.py`'s public namespace (Story 1.2 already added it; this is the verification step).
2. Add an import test under `backend/tests/unit/domain/study/test_convergence.py`: assert `from backend.app.domain.study.convergence import ConvergenceVerdict` succeeds and `typing.get_args(ConvergenceVerdict) == ("converged", "still_improving", "too_few_trials")`.
3. Add a one-line note in this plan's "Documentation update workstream" §4 entry for `architecture.md` mentioning the autopilot soft contract (so future readers find it).

**Definition of Done (DoD)**

- [ ] `ConvergenceVerdict` importable from `backend.app.domain.study.convergence`.
- [ ] Import + Literal-membership test passes.
- [ ] No autopilot files touched (verify with `git diff --stat` — should not include `feat_overnight_autopilot/` paths or any `StudyChainLink` reference).
- [ ] AC-16 is explicitly NOT asserted in this spec's CI lane (per FR-7 conditional gating).

---

## Epic 7 — Documentation (runbook + glossary "Learn more" + CLAUDE.md row + architecture patches)

### Story 7.1 — Operator runbook + CLAUDE.md row + arch patches (FR-9 + AC-19)

**Outcome:** Operator-facing runbook exists, CLAUDE.md "Key Runbooks" table carries a new row pointing at it, glossary `convergence_verdict.long`/href points at the runbook, and architecture docs note the panel mount + autopilot soft contract.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/convergence-verdict.md` | Operator-facing runbook covering: (1) what each verdict means + when to trust it, (2) plain-language algorithm summary (one paragraph), (3) "re-run with larger budget" recommended action with exact wizard presets (`Standard (200)` / `Deep (1000)`), (4) troubleshooting noisy-tail mis-classification using the curve, (5) one concrete minimize example. |

**Modified files**

| File | Change |
|---|---|
| `CLAUDE.md` | Add a row in the "Key Runbooks" table (line 588 region): `Interpreting the convergence verdict` → `docs/03_runbooks/convergence-verdict.md` (`feat_study_convergence_indicator`). |
| `docs/01_architecture/data-model.md` | Patch the `trials` section with a one-line note that `feat_study_convergence_indicator` reads `optuna_trial_number` / `primary_metric` / `status` / `is_baseline` to build the convergence curve — no schema delta. |
| `docs/01_architecture/ui-architecture.md` | Add a note documenting the `<ConvergencePanel>` mount position between `<ConfidencePanel>` and `<TrialsCard>` on `/studies/[id]`. Also note the autopilot soft contract (Story 6.1). |
| `ui/src/lib/glossary.ts` | (already touched in Story 4.1) — verify the `convergence_verdict` entry's `long` or `learnMoreHref` resolves to the runbook path. |
| `state.md` | Update "Last 5 merges" with the one-liner after the merge (per the §4 documentation workstream). |

**Tasks**

1. Write `docs/03_runbooks/convergence-verdict.md` per the 5-section outline above. Keep it short (≤200 lines).
2. Add the row to CLAUDE.md "Key Runbooks" table.
3. Patch `data-model.md` + `ui-architecture.md`.
4. Add the docs unit test (existing pattern under `backend/tests/unit/docs/`): assert the runbook exists, CLAUDE.md contains a row matching `"Interpreting the convergence verdict"` in the Key Runbooks table, and the glossary `convergence_verdict` entry's `long`/href points at `/docs/03_runbooks/convergence-verdict.md` (or the equivalent path).

**Definition of Done (DoD)**

- [ ] Runbook file exists, ≤200 lines, covers the 5 required sections (verdict meanings, plain-language algorithm, re-run framing with preset names, troubleshooting, minimize example).
- [ ] CLAUDE.md table carries the new row.
- [ ] Glossary `convergence_verdict` has a "Learn more" target pointing at the runbook.
- [ ] AC-19 docs assertion test passes.
- [ ] `state.md` updated (final-story step).

---

## 3) Testing workstream (required)

### 3.1 Unit tests

- Location: `backend/tests/unit/domain/study/test_convergence.py` (new), `backend/tests/unit/domain/study/test_auto_followup.py` (extend), `backend/tests/unit/llm/test_digest_prompt.py` (extend or new).
- Scope: classifier decision matrix, monotonicity invariant, baseline filter, NULL filter, window-clamp boundary cases, slow-drift / single-late-jump / noisy-tail behaviors, value-lock + AST/grep guard, prompt-string framing rule.
- Owned by: Story 1.1, Story 1.2, Story 5.2, Story 6.1.

### 3.2 Integration tests

- Location: `backend/tests/integration/test_study_convergence_integration.py` (new), `backend/tests/integration/test_trial_repo.py` (extend or new), `backend/tests/integration/test_digest_worker_convergence.py` (new).
- Scope: aggregator end-to-end against a seeded DB (in-flight short-circuit, sub-MIN → null, baseline filter, invalid direction WARN, classifier exception WARN); GET/cancel responses carry the field; digest worker passes payload through.
- Owned by: Story 2.1, Story 2.2, Story 3.1, Story 5.1.

### 3.3 Contract tests

- Location: `backend/tests/contract/test_studies_api_contract.py` (extend the existing file's `StudyDetail` shape block at lines 80–88).
- Scope: assert `StudyDetail.convergence` is `Optional[ConvergenceShape]` in the OpenAPI schema; assert every §8.3 sub-field appears with the correct type.
- Error codes: NONE — this feature introduces no new error codes (per spec §8.6). The existing `STUDY_NOT_FOUND` (404) covers the only failure path on `GET /studies/{id}`; the cancel endpoint's pre-existing failure paths (`InvalidStateTransition`) are not modified.
- Owned by: Story 3.1.

### 3.4 E2E tests

- Location: `ui/tests/e2e/convergence-panel.spec.ts` (new — one lightweight smoke per spec §14 FR-11).
- Scope: real backend; seed two studies (one converged, one still_improving) via API helpers; `page.goto('/studies/{id}')`; assert verdict badge text + `data-testid="cs-convergence-verdict"` + `<details>` open state.
- **No `page.route()` mocking** (per CLAUDE.md E2E rule + spec §14 FR-11). Setup via API helpers, assertions via `page`.
- Owned by: Story 4.2.

### 3.5 Frontend vitest

- Location: `ui/src/__tests__/components/studies/convergence-panel.test.tsx` (new), `ui/src/__tests__/lib/enums-convergence-discipline.test.ts` (new), `ui/src/__tests__/lib/glossary*.test.ts` (extend existing).
- Scope: all 6 verdict-badge variants (3 verdicts + 3 null states), `<details>` open/collapsed defaults, no-Recharts-mount on null, AC-20 aria-label string, value-lock for `CONVERGENCE_VERDICT_VALUES`, glossary entry presence + length.
- Owned by: Story 4.1, Story 4.2.

### 3.6 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/contract/test_studies_api_contract.py` | `StudyDetail` shape | 1 | Extend (Story 3.1) — add the optional `convergence` key + sub-field assertions. |
| `backend/tests/unit/domain/study/test_confidence.py` | `assert CONVERGENCE_MIN_COMPLETE == 3` (line 605) | 1 | **No change.** That constant still means what it meant. This feature's constants live in a different module. |
| `backend/tests/unit/domain/study/test_auto_followup.py` | Existing `evaluate_chain_gate` test suite | many | Stays byte-identical green (Story 1.1 is a pure refactor). Add the AUTO_FOLLOWUP_LIFT_EPSILON value-lock test alongside. |
| Playwright specs touching `/studies/[id]` | DOM assertions by panel index | TBD — grep at impl time | If any spec asserts panels by positional index, anchor on `data-testid` instead — but the new panel is additive between existing panels, so most index-based specs will still pass. Captured as test debt per spec §2 Existing test impact. |
| `backend/tests/unit/docs/test_claude_md_sections.py` (existing) | Section presence + structure | 1 | (Optional) — if the runbook row is asserted by an existing CLAUDE.md docs test, that test will pass once the row is added; otherwise the new docs test in Story 7.1 covers it. |

### 3.7 Migration verification

- **No schema changes.** Alembic head stays at `0022_solr_engine_auth_check`. No migration round-trip required. (Documented in §9 of the spec.)

### 3.8 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test` (vitest)
- [ ] `cd ui && pnpm typecheck`
- [ ] `cd ui && pnpm lint`
- [ ] `cd ui && pnpm build`
- [ ] Playwright smoke: `cd ui && pnpm test:e2e -- convergence-panel.spec.ts` (or the project's standard real-backend lane)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

- **`state.md`** — add the merge one-liner after the merge (per CLAUDE.md "Last 5 merges" pattern). Alembic head does not change.
- **`architecture.md`** — patch the topical doc references to `data-model.md` and `ui-architecture.md` (touched below); no top-level architecture changes.
- **`CLAUDE.md`** — add the "Key Runbooks" table row (Story 7.1). Feature status section update: this feature is MVP2 — add to that section if it's tracked there (inspect at impl time).

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] `data-model.md` §"trials" — one-line note that `feat_study_convergence_indicator` reads existing columns to build the convergence curve (no schema delta). Owned by Story 7.1.
- [ ] `ui-architecture.md` — note `<ConvergencePanel>` mount position + autopilot soft contract. Owned by Story 7.1.

### 4.2 Product docs

- [ ] No patch — no new user story emerges (per spec §15).

### 4.3 Runbooks

- [ ] `docs/03_runbooks/convergence-verdict.md` (new, Story 7.1).

### 4.4 Security docs

- [ ] No patch — no new threat surface (per spec §10, §15).

### 4.5 Quality docs

- [ ] No patch — existing test-layer convention covers the new tests.

**Documentation DoD**

- [ ] `state.md`, `architecture.md`, `CLAUDE.md` consistent with shipped behavior.
- [ ] Runbook is operator-readable (≤200 lines, plain language, concrete wizard preset names).
- [ ] AC-19 docs assertion test passes.

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals

- Eliminate the inline `0.005` duplicate by hoisting to `AUTO_FOLLOWUP_LIFT_EPSILON` (Story 1.1).
- Add an AST/grep guard preventing future re-inlining (Story 1.2).
- No further refactors — every other change is additive.

### 5.2 Planned refactor tasks

- [ ] Backend: Story 1.1 hoist (2 line changes in `auto_followup.py`). No other refactors.
- [ ] Frontend: none.
- [ ] No dead-code removal — every existing surface stays.

### 5.3 Refactor guardrails

- [ ] All existing `evaluate_chain_gate` unit tests stay green byte-for-byte (Story 1.1 DoD).
- [ ] Lint + typecheck stay green.
- [ ] No expansion of product scope — verdict logic ships exactly as specified.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_overnight_autopilot` (sibling, idea-stage) | Story 6.1 contract documentation only | planned | Low — Story 6.1 ships the symbol + helper; autopilot consumes them in its own PR. AC-16 is NOT a merge-blocker for this PR. |
| `feat_study_sub_warmup_guard` (shipped 2026-05-29, PR #316) | Story 1.2 imports `STUDIES_TPE_WARMUP_FLOOR` | shipped | N/A — already on `main`. |
| `feat_auto_followup_studies` (shipped 2026-05-24) | Story 1.1 hoists from + Story 1.2 re-exports from `auto_followup.py` | shipped | N/A — already on `main`. |
| `feat_pr_metric_confidence` (shipped 2026-05-21) | Source of the `ConfidenceShape` precedent + name-collision context | shipped | N/A — already on `main`. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Implementer accidentally redefines `ConvergenceRegime` or `CONVERGENCE_MIN_COMPLETE` from `confidence.py` | M | H | The §0 plan-level discipline note + Story 1.2's name-collision reminder + the fact that this feature lives in `convergence.py` (not `confidence.py`) all reinforce the discipline. Code review checkpoint. |
| Implementer re-inlines a bare `0.005` literal elsewhere (drift) | L | M | AST/grep guard test in Story 1.2 fails CI if any other module contains a bare `0.005` in a lift/epsilon-shaped context. |
| Playwright smoke spec is flaky against the real backend | L | L | Use the same `signup_flow.spec.ts` real-backend pattern that's been stable since `feat_studies_ui`. Single chromium, single worker (the existing project config). |
| Cancel endpoint regression: cancel of a terminal study attempts to surface convergence | L | M | Spec AC-10 confirms cancel of terminal studies raises `InvalidStateTransition` (verified at `backend/app/services/study_state.py`). Integration test verifies running→cancelled produces a populated `convergence`; terminal→cancel-attempt 4xx is unchanged. |
| Classifier exception leaks → 500 on `GET /studies/{id}` | L | H | Story 2.2 wraps the classifier call in `try/except Exception` + WARN log + returns None. Integration test in Story 3.1 monkeypatches a raising classifier and asserts GET returns 200 with `convergence: null`. |
| Recharts `<ReferenceArea>` mis-renders when `window_size > total_complete_trials` (shouldn't happen post-classifier) | L | L | Boundary case at `len(curve) == window_size` (spec §9 §"Boundary case"): index `curve[-window_size]` is `curve[0]` — chart renders the band covering the entire curve. No special-case logic required. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Invalid persisted direction | `study.objective["direction"]` is a string other than `"maximize"`/`"minimize"` | Aggregator emits `convergence_invalid_direction` WARN; returns `None`; GET succeeds with `convergence: null`; panel renders "Verdict unavailable" badge | Manual data fix or accept null verdict |
| Classifier raises unexpected exception | Programmer bug in `classify_convergence` | Aggregator's `try/except` emits `convergence_classifier_exception` WARN; returns `None`; GET succeeds with `convergence: null`; panel renders "Verdict unavailable" | Investigate WARN log; ship fix |
| All trials have `primary_metric IS NULL` | Degenerate seed; orchestrator bug | Classifier filters all rows, filtered length < MIN → returns `None`; aggregator returns `None`; GET succeeds with `convergence: null` | Investigate orchestrator; no panel breakage |
| `is_baseline=True` row leaks into the curve | Filter bug | Curve would include sentinel `trial_number=-1`; monotonicity invariant test fails | Caught by unit test in Story 1.2 |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (Story 1.1 → Story 1.2). 1.1 first because 1.2 imports the hoisted constant.
2. **Epic 2** (Story 2.1 → Story 2.2). Repo helper first; service second.
3. **Epic 3** (Story 3.1). Wires backend end-to-end; the contract test gate verifies the response shape.
4. **Epic 4** (Story 4.1 → Story 4.2). Component first; mount + e2e + enum lock second.
5. **Epic 5** (Story 5.1 → Story 5.2). Worker threading first; system prompt patch second.
6. **Epic 6** (Story 6.1). Documentation-only verification of the symbol export.
7. **Epic 7** (Story 7.1). Runbook + arch patches + CLAUDE.md row + state.md update.

### Parallelization opportunities

- Epic 4 (frontend) can land in parallel with Epic 5 (digest) once Epic 3 has shipped the backend payload.
- Story 7.1 (docs) can begin once Epic 1 + Epic 2 lock the verdict semantics — does not need to wait for Epic 4 to finish.

---

## 8) Rollout and cutover plan

- **Feature flag strategy:** None. Feature is additive + read-only (per spec §16).
- **Rollout stages:** Single-stage. Merge → operators see the panel on first GET post-deploy.
- **Migration/backfill:** **None.** No schema delta. Studies completed before this feature shipped have their verdict computed on first GET post-deploy.
- **Reconciliation/repair:** N/A — no external systems involved.

---

## 9) Execution tracker (copy/paste section)

### Current sprint

- [ ] Story 1.1 — hoist epsilon
- [ ] Story 1.2 — classifier + tests + AST guard
- [ ] Story 2.1 — repo helper
- [ ] Story 2.2 — service aggregator
- [ ] Story 3.1 — StudyDetail field + contract test
- [ ] Story 4.1 — `<ConvergencePanel>` + glossary
- [ ] Story 4.2 — mount + enum lock + Playwright smoke
- [ ] Story 5.1 — digest worker + user prompt
- [ ] Story 5.2 — digest system prompt framing rule
- [ ] Story 6.1 — symbol export verification + contract docs
- [ ] Story 7.1 — runbook + CLAUDE.md row + arch patches + state.md

### Blocked items

- (none at plan time)

### Done this sprint

- (none yet)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables).
- [ ] Endpoint contract implemented exactly as documented (Story 3.1 only — every other story adds zero endpoints).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added/updated for all four layers where applicable.
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (Stories 2.1+ touch DB)
  - [ ] `make test-contract` (Story 3.1)
  - [ ] `cd ui && pnpm test` (Story 4.1, 4.2)
  - [ ] `cd ui && pnpm test:e2e` smoke (Story 4.2)
- [ ] **No new error codes introduced** (confirmed by visual inspection of `studies.py` `_err` call sites — should match pre-feature state).
- [ ] **AST/grep guard test green** (Story 1.2 onward) — no stray `0.005` outside `auto_followup.py`'s declaration line.
- [ ] **Name-collision discipline verified** — no `ConvergenceRegime` / `CONVERGENCE_MIN_COMPLETE` import or redefinition in this feature's new code; all symbols come from `convergence.py` (singular).
- [ ] Related docs updated in the same PR when behavior/contract changed.

---

## 11) Plan consistency review (executed before status flipped to Ready)

1. **Spec ↔ plan endpoint count.** Spec §8.1: 0 new endpoints, 2 existing endpoints' responses extended. Plan §3.3 + Story 3.1 endpoint table: 0 new, same 2 existing. **Match.**
2. **Spec ↔ plan error code coverage.** Spec §8.6: no new error codes. Plan §3.3: no new error codes. **Match.**
3. **Spec ↔ plan FR coverage.** All 9 FRs mapped in §1 traceability table; every FR is assigned to at least one story. **Verified.**
4. **Story internal consistency.** Every story's "New files" + "Modified files" tables verified against the codebase: `auto_followup.py:74,121` confirmed; `confidence.py:102,117` confirmed; `studies.py:125-158` confirmed; `schemas.py:793-824` confirmed; `digest_prompt.py:115-167` confirmed; `digest.py:944-948` confirmed; `page.tsx:109-111` confirmed; existing `parameter-importance-chart.tsx` Recharts pattern confirmed; existing `confidence-panel.tsx` `<Card>` + `<InfoTooltip>` pattern confirmed; `glossary.ts` + `enums.ts` precedents confirmed.
5. **Test file count + assignment.** Every test file in §3 is assigned to a story DoD:
   - `test_convergence.py` (unit) → Story 1.2 (and value-lock owned by Story 4.2 backend-side).
   - `test_auto_followup.py` extension → Story 1.1.
   - `test_trial_repo.py` extension → Story 2.1.
   - `test_study_convergence_integration.py` → Story 2.2.
   - `test_studies_api_contract.py` extension → Story 3.1.
   - `test_digest_worker_convergence.py` → Story 5.1.
   - `test_digest_prompt.py` (system prompt assertion) → Story 5.2.
   - `convergence-panel.test.tsx` → Story 4.1.
   - `enums-convergence-discipline.test.ts` → Story 4.2.
   - `convergence-panel.spec.ts` (Playwright) → Story 4.2.
   - Docs assertion test (CLAUDE.md row + runbook + glossary "Learn more") → Story 7.1.
6. **Gate arithmetic.** No epic gates state explicit endpoint counts; gates are story-level DoD checklists. **N/A.**
7. **Open questions.** Spec §19 reports all open questions resolved (D-1 through D-7 in the decision log). **Verified.**
8. **Frontend UI Guidance completeness.** Story 4.1's UI element inventory + analogous markup patterns + tooltip inventory + badge mapping table cover the panel. Story 4.2's mount table cites the precise insertion point (line 110-111 of `page.tsx`). **Verified.**
9. **Legacy behavior parity.** No user-facing component >100 LOC is being deleted or migrated in this plan. The `<ConvergencePanel>` is purely additive. **No legacy behavior parity table required.**
10. **Enumerated value contract verification.** `CONVERGENCE_VERDICT_VALUES` in `ui/src/lib/enums.ts` (Story 4.2) cites `backend/app/domain/study/convergence.py ConvergenceVerdict` as source-of-truth. Value-lock vitest + backend Literal-membership test ensure character-for-character agreement. **Verified.**
11. **Audit-event coverage.** Spec §6 documents no state-mutating endpoints or service functions. The aggregator is read-only; the digest worker (which DOES mutate) gets its audit instrumentation when `audit_log` lands at MVP3 — this spec's only delta is a new kwarg on `render_digest_user_prompt`. **No audit-event coverage gap.**

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (where applicable), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/vitest/e2e smoke) are explicitly scoped.
- [x] Documentation updates across `docs/01_architecture/` (data-model, ui-architecture), `docs/03_runbooks/` (new), and `CLAUDE.md` (Key Runbooks row + Feature Status) are planned and owned.
- [x] Lean refactor scope (epsilon hoist) and guardrails are explicit.
- [x] Epic gates / story DoDs are measurable.
- [x] Story-by-Story Verification Gate (§10) is included.
- [x] Plan consistency review (§11) executed with all checks "Verified" / "Match" / "N/A as appropriate".

---

## 13) Review log

- **Mode:** Generate.
- **Source spec:** [`feature_spec.md`](feature_spec.md) (755 lines, 9 FRs, 22 ACs, 7 decision-log entries).
- **GPT-5.5 cross-model review: SKIPPED at operator request.** Operator decision (2026-05-31): Opus-only internal passes per the umbrella instruction set for this batch of three plans on `feature/mvp2-top5-plans`. Plan was reviewed by Opus across two passes:
  - **Pass A (structural):** spec ↔ plan FR/endpoint/error coverage; story DoD ↔ endpoint shape consistency; test file assignment audit. Findings: zero blocking; one minor (added explicit "no new error codes" assertion to the Verification Gate §10 to make the spec-§8.6 invariant easier to audit at story-completion time). Applied.
  - **Pass B (codebase accuracy):** verified every claimed file path + line number against the codebase via `Read` / `grep`:
    - `auto_followup.py:74` (`ChainGateOutcome.epsilon: float = 0.005`) — confirmed.
    - `auto_followup.py:121` (`evaluate_chain_gate(..., epsilon: float = 0.005, ...)`) — confirmed.
    - `confidence.py:102` (`CONVERGENCE_MIN_COMPLETE: int = 3`) — confirmed.
    - `confidence.py:117` (`ConvergenceRegime = Literal["early_held", "late_rising", "noisy"]`) — confirmed.
    - `studies.py:125-158` (`_detail` builder) — confirmed.
    - `schemas.py:793-824` (`StudyDetail` Pydantic) — confirmed.
    - `digest_prompt.py:115-167` (`render_digest_user_prompt`) — confirmed.
    - `digest.py:944, 948` (worker call site + render) — confirmed.
    - `page.tsx:109-111` (mount-point neighbors) — confirmed.
    - `confidence-panel.tsx:60-78` (Card + InfoTooltip pattern) — confirmed.
    - `parameter-importance-chart.tsx:25-35` (Recharts ResponsiveContainer pattern) — confirmed.
    - `optuna_runtime.py:39` (`STUDIES_TPE_WARMUP_FLOOR: int = 50`) — confirmed.
    - Alembic head `0022_solr_engine_auth_check` — confirmed via `ls migrations/versions/`. No new migration.
    - Existing tests at `test_studies_api_contract.py:80-88` — confirmed shape-assertion pattern.
- **Findings classified.** Zero **Major** findings (no spec / endpoint contract drift, no story-scope ambiguity, no codebase-claim mismatch). One **Minor** finding (no-new-error-code Verification Gate addition) applied without gating per the operator's blanket pre-approval.
- **Hard blockers:** 0.
- **Deferred phase tracking:** N/A — spec is single-phase; no `phase2_idea.md` created.
