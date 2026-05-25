# Implementation Plan — `feat_study_baseline_trial`

**Date:** 2026-05-25
**Status:** Draft — pending GPT-5.5 cross-model review
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy sources:** [`CLAUDE.md`](../../../../CLAUDE.md), [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs and the spec's ACs.
- Phase gates are hard stops — failing tests within a phase block the next phase.
- Fail-loud tests: assert explicit status/shape/error_code; never use bare-assertion `assert response.ok`.
- Backend-first ordering: migration → repo → domain → service → worker → orchestrator → API → frontend.
- Each story is independently verifiable — a story's DoD is the test layer that proves it.

## 1) Scope traceability (FR → epics)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (migration) | Epic 1 / Story 1.1 | 0020_studies_baseline_trial: `studies.baseline_trial_id` + `trials.is_baseline` + partial unique index `uq_trials_study_baseline_complete` |
| FR-2 (orchestrator) | Epic 1 / Story 1.7 | Inserts baseline phase between search-space parse and Optuna polling |
| FR-3 (resolver) | Epic 1 / Story 1.2 | 4-tier fallback: parent_proposal → parent_study → operator-supplied → template defaults |
| FR-4 (confidence) | Epic 2 / Story 2.1 | One-line conditional at `confidence.py:624` + new keyword arg |
| FR-5 (auto-followup) | Epic 2 / Story 2.2 | Direction-aware lift; rename `compute_first_decile_max` → `compute_first_decile_extremum` |
| FR-6 (`baseline_params`) | Epic 1 / Story 1.5 | New `StudyConfigSpec.baseline_params` typed `dict[str, primitives] \| None` |
| FR-7 (digest prompt) | Epic 2 / Story 2.3 | System-prompt 1-2 sentence addition + glossary tooltip refresh |
| FR-8 (`StudyDetail`) | Epic 1 / Story 1.5 | Expose `baseline_trial_id` + `is_baseline` via API schemas |
| FR-9 (UI filter) | Epic 3 / Story 3.1 | trials-table baseline filter + "Show baseline" toggle + Baseline badge |
| FR-10 (worker) | Epic 1 / Story 1.3 | `run_baseline_trial` Arq job + self-stamp on completion |
| FR-11 (repo filters) | Epic 1 / Story 1.6 | `is_baseline=FALSE` filters on aggregate / list / complete-trial reads |
| FR-12 (stamp helper) | Epic 1 / Story 1.4 | `services.study_state.stamp_baseline_trial` chokepoint |

**Deferred phases:** None — feature is single-phase by design (see spec §3 "Phase boundaries").

## 2) Delivery structure

Structure: **Epic → Story → Tasks → DoD**. Stories are sequential within an epic; epics are gated by phase gates (full test suite + cross-model review).

### Conventions (RelyLoop-specific)

- All repo functions take `db: AsyncSession` as first arg; use `db.flush()` (caller commits).
- Services are async; long-running services create a `job_run` record at start where applicable (N/A for this feature).
- Domain layer is pure — no DB access, no side effects (resolver is the exception; it takes `db` for parent-row lookups but does NO writes).
- Models use `Mapped[]` typed columns, `String(36)` UUIDs, `TIMESTAMPTZ` for time.
- Routers return typed Pydantic response models; errors use the `_err(status, code, msg, retryable)` helper at `backend/app/api/v1/studies.py:113`.
- Config via `pydantic-settings`; never hardcode model names (CLAUDE.md Absolute Rule #8).
- All `__init__.py` exports updated via `__all__`.
- Migrations include `downgrade()` + idempotency guards + round-trip verification (CLAUDE.md Absolute Rule #5).
- Test layering: unit → integration → contract → E2E. Mocked tests use `monkeypatch`; real-backend integration tests run against service-container Postgres in CI.

### AI Agent Execution Protocol

0. Load context: read `CLAUDE.md`, `architecture.md`, `state.md` before starting Story 1.1.
1. Read story scope: outcome + files + interfaces + DoD.
2. Implement backend in order: model → migration → repo → domain → service → worker → router → schemas.
3. Run touched-layer tests before moving to next story.
4. Implement frontend (if applicable).
5. Run E2E scope for touched paths.
6. Update docs in same PR.
7. Verify migration round-trip after Story 1.1.
8. After final story, update `state.md` and any architecture topical docs.

---

## Epic 1 — Foundation: schema + worker + service helpers (FR-1, FR-3, FR-6, FR-8, FR-10, FR-11, FR-12, FR-2)

The backend foundation lands first. Every Epic 2 / Epic 3 story depends on the columns + helpers from Epic 1.

### Story 1.1 — Migration 0020 + ORM + `repo.create_trial(is_baseline=…)` (FR-1, AC-13)

**Outcome:** `studies.baseline_trial_id` and `trials.is_baseline` columns exist in the DB. The partial unique index `uq_trials_study_baseline_complete` is in place. The ORM models reflect the new columns. `repo.create_trial` accepts the new `is_baseline` kwarg (default `False`, so all existing callers are byte-compatible). Migration round-trips cleanly AND is idempotent on re-run.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0020_studies_baseline_trial.py` | Alembic migration adding both columns + partial unique index. Reversible. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/study.py` | Add `baseline_trial_id: Mapped[str \| None] = mapped_column(String(36), nullable=True)` after `best_trial_id` at line 99-103. Mirror the docstring pattern. |
| `backend/app/db/models/trial.py` | Add `is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))` to the `Trial` class. Update class docstring with the column's purpose. |
| `backend/app/db/repo/trial.py` | Extend `create_trial` signature to accept `is_baseline: bool = False` (default keeps every existing caller byte-compatible). Plumb into the INSERT statement. Update `__all__` if its arg list is documented anywhere. (Plan F2: this lands here so Story 1.4 can use the new kwarg without a circular dependency.) |

**Endpoints:** N/A.

**Key interfaces:** N/A — schema-only story.

**Pydantic schemas:** N/A — schema-only story.

**Tasks**

1. Run `ls migrations/versions/` and confirm `0019_digests_suggested_followups_jsonb.py` is the current head.
2. Create `migrations/versions/0020_studies_baseline_trial.py` with `revision = "0020_studies_baseline_trial"`, `down_revision = "0019_digests_suggested_followups_jsonb"`.
3. In `upgrade()`: idempotently add `studies.baseline_trial_id String(36) NULL` via `op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'studies' AND column_name = 'baseline_trial_id') THEN ALTER TABLE studies ADD COLUMN baseline_trial_id VARCHAR(36); END IF; END $$;")`.
4. Idempotently add `trials.is_baseline BOOLEAN NOT NULL DEFAULT FALSE` via the same guard pattern.
5. Idempotently create the partial unique index: `CREATE UNIQUE INDEX IF NOT EXISTS uq_trials_study_baseline_complete ON trials (study_id) WHERE is_baseline = TRUE AND status = 'complete';`.
6. In `downgrade()`: DROP INDEX `uq_trials_study_baseline_complete`, DROP COLUMN `trials.is_baseline`, DROP COLUMN `studies.baseline_trial_id` (idempotency-guarded with `IF EXISTS`).
7. Update `backend/app/db/models/study.py:Study` to add the column with docstring.
8. Update `backend/app/db/models/trial.py:Trial` to add the column + import `Boolean` + `text` from sqlalchemy.
9. Verify round-trip: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head`.
10. Run `make test-integration` — confirm existing tests pass with new columns.

**Definition of Done**

- `alembic upgrade head` succeeds against a fresh Postgres.
- `alembic downgrade -1 && alembic upgrade head` round-trips cleanly (AC-13).
- `alembic upgrade head` is idempotent — re-running with the columns + index already present does not raise (covered by an explicit test in `test_baseline_migration_round_trip.py` that runs `op.run_migrations()` twice via the alembic Python API and asserts no exception). (Plan F7.)
- New integration test `backend/tests/integration/test_baseline_migration_round_trip.py` asserts:
  - `studies.baseline_trial_id` column exists with `VARCHAR(36)` type and is nullable.
  - `trials.is_baseline` column exists with `BOOLEAN NOT NULL DEFAULT FALSE`.
  - `uq_trials_study_baseline_complete` index exists with correct WHERE clause (verify via `pg_indexes` query).
  - Idempotent re-run: invoking the migration logic twice does not raise.
- Existing `backend/tests/integration/test_study_lifecycle_migration.py` updated to include the new columns in its column-list assertion (line 424).
- `repo.create_trial` accepts `is_baseline=True` and persists the column (unit test in `backend/tests/integration/test_create_trial_is_baseline.py`).
- `make test-integration` green.

---

### Story 1.2 — `resolve_baseline_params` domain helper (FR-3, AC-1, AC-2, AC-14)

**Outcome:** A pure-domain async function resolves baseline params via the 4-tier fallback (parent_proposal → parent_study → operator-supplied → template defaults). Caller (Story 1.7's orchestrator) passes a `Study` row + `db`; resolver returns `dict | None`.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/baseline_resolver.py` | 4-tier fallback resolver + per-tier helpers (`_resolve_from_parent_proposal`, `_resolve_from_parent_study`, `_resolve_from_operator_supplied`, `_resolve_from_template_defaults`). |
| `backend/tests/unit/domain/study/test_baseline_resolver.py` | Unit tests for every tier transition + edge cases (empty params, missing parent, log emission). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/__init__.py` | Export `resolve_baseline_params` via `__all__`. |

**Endpoints:** N/A.

**Key interfaces**

```python
# backend/app/domain/study/baseline_resolver.py
async def resolve_baseline_params(db: AsyncSession, study: Study) -> dict[str, Any] | None:
    """4-tier fallback resolver per spec FR-3.

    Returns None when the search-space has no declared params AND no
    explicit tier resolved (i.e., baseline trial should be skipped).
    """

def _template_midpoint(search_space: SearchSpace) -> dict[str, Any]:
    """Pure helper: return middle-of-range for every declared param.

    Float: (low + high) / 2.0 (or sqrt(low * high) for log=true).
    Int:   (low + high) // 2.
    Categorical: choices[(len(choices) - 1) // 2] (lower midpoint).
    """
```

**Pydantic schemas:** N/A.

**Tasks**

1. Create `baseline_resolver.py` with the four tier helpers + the orchestrator function.
2. Tier (d) `_resolve_from_parent_proposal`: if `study.parent_proposal_id` set, load `Proposal` via `repo.get_proposal(db, study.parent_proposal_id)`, then load the `Trial` at `proposal.study_trial_id` via `repo.get_trial`. Return `trial.params` if both exist; else log `event_type="baseline_resolve_parent_proposal_missing"` and return `None` (caller falls through).
3. Tier (c) `_resolve_from_parent_study`: if `study.parent_study_id` set, load `Study` + the trial at `parent.best_trial_id`. Return `trial.params` or `None`.
4. Tier (b) `_resolve_from_operator_supplied`: read `study.config.get("baseline_params")`. Return as-is (dict already typed by Pydantic at create-time).
5. Tier (a) `_template_midpoint`: parse `study.search_space` via `SearchSpace.model_validate`; iterate `params` and apply the type-discriminator midpoint formula.
6. `resolve_baseline_params` chains them: try (d) → (c) → (b) → (a). Return `None` if (a) returns `{}` (empty declared_params).
7. Write unit tests covering: each tier hit individually, fall-through cascades, missing parent trial (cascade-delete race), empty declared params, log emission verification via `caplog`.

**Definition of Done**

- Unit test coverage ≥ 95% on `baseline_resolver.py`.
- 12+ unit tests covering all 4 tiers + 6+ edge cases (deleted parent trial, deleted parent study, empty search space, log emission, log redaction).
- Resolver portions of AC-1, AC-2, AC-14 covered by unit tests (the full end-to-end "orchestrator stamps + Optuna proceeds" parts of AC-1/AC-2 are covered by Story 1.7's integration tests). (Plan F10.)

---

### Story 1.3 — `stamp_baseline_trial` service helper (FR-12, AC-1, AC-16)

(Reordered before the worker per plan F1 so Story 1.4 can call it without forward dependency.)

**Outcome:** A single service-layer chokepoint stamps `studies.baseline_trial_id` + `baseline_metric`. Idempotent. Used by the orchestrator (FR-2 step 7), the worker self-stamp (FR-10 step 7), and the resume path (§9 idempotency).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/services/test_stamp_baseline_trial.py` | Mocked-DB unit tests (uses `monkeypatch` on the SQL execution). |
| `backend/tests/integration/test_stamp_baseline_trial_integration.py` | Real-Postgres integration test. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/study_state.py` | Add `stamp_baseline_trial(db, study_id, trial_id, primary_metric) -> bool` + custom exceptions `BaselineTrialNotFound`, `InvalidBaselineTrialState`. |

**Endpoints:** N/A.

**Key interfaces**

```python
# backend/app/services/study_state.py
class BaselineTrialNotFound(Exception): ...
class InvalidBaselineTrialState(Exception): ...

async def stamp_baseline_trial(
    db: AsyncSession,
    study_id: str,
    trial_id: str,
    primary_metric: float,
) -> bool:
    """Stamp studies.baseline_trial_id + baseline_metric.

    Returns True if this caller stamped, False if a sibling already
    stamped (race-tolerant). Raises BaselineTrialNotFound if the trial
    row is missing; raises InvalidBaselineTrialState if the row's
    is_baseline / status / study_id don't match expectations.

    Idempotent via WHERE baseline_trial_id IS NULL predicate.
    Commit is left to the caller; both the orchestrator and the worker
    MUST call `await db.commit()` after this returns to durably land
    the stamp.
    """
```

**Pydantic schemas:** N/A.

**Tasks**

1. Add the two exception classes at the top of `study_state.py` (next to existing `InvalidStateTransition`).
2. Implement `stamp_baseline_trial`: load trial → assert `study_id`, `is_baseline=TRUE`, `status='complete'` → execute the idempotent UPDATE.
3. Use SQLAlchemy `text()` with **named bind parameters** (NOT asyncpg `$1, $2`): `text("UPDATE studies SET baseline_trial_id = :trial_id, baseline_metric = :primary_metric WHERE id = :study_id AND baseline_trial_id IS NULL RETURNING id")` invoked via `await db.execute(stmt, {"trial_id": ..., "primary_metric": ..., "study_id": ...})`. The `.rowcount` or `.fetchone()` tells us whether we stamped. (Plan F8.)
4. Return `True` on stamp (1 row affected), `False` if already-stamped (0 rows).
5. Write unit tests: happy path, race (already-stamped no-ops returning False), BaselineTrialNotFound, InvalidBaselineTrialState for each precondition (wrong study_id, is_baseline=FALSE, status≠'complete').
6. Write integration test: insert real `studies` + `trials` rows; call stamp helper + commit; assert UPDATE landed; call stamp helper again; assert idempotent.

**Definition of Done**

- Unit test coverage ≥ 95% on the new helper.
- 8+ unit tests + 3+ integration tests (real Postgres).
- AC-1, AC-16 covered by the contract that Story 1.4's worker self-stamp + Story 1.7's orchestrator stamp will depend on.

---

### Story 1.4 — `run_baseline_trial` worker (FR-10, AC-1, AC-3, AC-16)

(Reordered after the stamp helper per plan F1.)

**Outcome:** A new Arq job runs the baseline trial: renders the template, executes the engine query, scores, and persists a `Trial` row with `is_baseline=TRUE, optuna_trial_number=-1`. On completion, self-stamps `studies.baseline_trial_id` + `baseline_metric` via Story 1.3's helper, then commits. Idempotent via the pre-generated `trial_id`. Registered in `WorkerSettings.functions`. Includes a test-only fault seam for the late-completion integration test (plan F9).

**New files**

| File | Purpose |
|---|---|
| `backend/workers/baseline.py` | `run_baseline_trial(ctx, study_id, trial_id, params)` Arq job. |
| `backend/tests/unit/workers/test_baseline_trial.py` | Mocked-adapter unit tests for `run_baseline_trial`. |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/main.py` | Add `run_baseline_trial` to `WorkerSettings.functions`. |

**Endpoints:** N/A.

**Key interfaces**

```python
# backend/workers/baseline.py
async def run_baseline_trial(
    ctx: dict[str, Any],
    study_id: str,
    trial_id: str,
    params: dict[str, Any],
) -> None:
    """One-shot non-Optuna baseline trial. See spec FR-10."""

async def _existing_baseline_terminal_row(
    db: AsyncSession, trial_id: str
) -> Trial | None:
    """trial_id-based idempotency check (FR-10)."""
```

**Pydantic schemas:** N/A.

**Tasks**

1. Create `backend/workers/baseline.py` mirroring `backend/workers/trials.py` structure but stripped of all Optuna interaction.
2. On entry: idempotency check on `trial_id` (load `Trial` by id; if terminal, return no-op).
3. Load `Study`, `Cluster`, `QueryTemplate`, queries, qrels (same lookups as `run_trial`).
4. Build adapter via `build_adapter(cluster)`.
5. Render queries via `adapter.render(template, params, q.query_text)` for each query.
6. Resolve trial_timeout: `study.config.trial_timeout_s` or `Settings.studies_default_timeout_s`.
7. Call `adapter.search_batch(target, native_queries, top_k, strict_errors=False, timeout=trial_timeout_s)`.
8. Score via `score(qrels, run_dict, metrics_set)` (same metric set as `run_trial`: `{objective_key} | DEFAULT_SECONDARY_METRICS | study.config.secondary_metrics`).
9. INSERT the `Trial` row via `repo.create_trial(..., optuna_trial_number=-1, is_baseline=True, ...)` — need to extend `repo.create_trial` to accept `is_baseline` kwarg (default `False`).
10. On success: call `services.study_state.stamp_baseline_trial(db, study_id, trial_id, primary_metric)` (Story 1.3's helper) AND `await db.commit()` to durably land the stamp. (Plan F4: explicit commit required.)
11. On failure: persist `Trial` row with `status='failed'`, `is_baseline=TRUE`, `error=str(exc)[:500]`, then `await db.commit()`. Return normally (Arq treats as success).
12. Catch `IntegrityError` from the partial unique index — log + return (another worker already landed a complete baseline; this is the duplicate-INSERT-after-Arq-_job_id-bypass edge case).
13. Catch `SAOperationalError` and re-raise for Arq retry.
14. Wrap adapter aclose + structlog contextvars unbind in `try/finally`.
15. Add a **test-only fault seam** before the score step: `if os.environ.get("FEAT_STUDY_BASELINE_TRIAL_FAULT") == "delay_before_score": await asyncio.sleep(float(os.environ.get("FEAT_STUDY_BASELINE_TRIAL_FAULT_DELAY_S", "5")))`. Used by `test_baseline_late_completion_stamp.py` to force the orchestrator's wait to time out while the worker eventually completes. (Plan F9.)
16. Register in `backend/workers/main.py` `WorkerSettings.functions`.
17. Write unit tests with mocked adapter / scorer / qrels-loader: happy path, scorer raises, adapter raises, IntegrityError swallowed cleanly, structlog contextvars set + unset, the fault-seam delay path.

**Definition of Done**

- Unit test coverage ≥ 90% on `backend/workers/baseline.py`.
- 10+ unit tests covering happy path + 6+ failure paths.
- `run_baseline_trial` registered in `WorkerSettings.functions` (verify via `from backend.workers.main import WorkerSettings; assert run_baseline_trial in WorkerSettings.functions`).
- Worker self-stamp + commit lands the `studies.baseline_trial_id` on successful baseline completion (integration test seeds a fixture and asserts the UPDATE).
- Fault seam exercised by `test_baseline_late_completion_stamp.py`.
- AC-1, AC-3, AC-16 covered.

---

### Story 1.5 — Schema updates: `baseline_params` request, `baseline_trial_id` response, `is_baseline` trial row (FR-6, FR-8, AC-9, AC-14)

**Outcome:** `POST /api/v1/studies` accepts `config.baseline_params: dict[str, primitive] | None`; `GET /api/v1/studies/{id}` and `GET /api/v1/studies/{id}/trials` include the new fields.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/contract/test_baseline_schemas.py` | Contract tests for the new request/response fields. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `baseline_params: dict[str, str \| int \| float \| bool \| None] \| None = None` to `StudyConfigSpec` (line 557-595). Add `baseline_trial_id: str \| None` to `StudyDetail` (line 668-698). Add `is_baseline: bool` to `TrialDetail` (line 724-737). |
| `backend/app/api/v1/studies.py` | Update `_detail` (line 121) to include `baseline_trial_id=row.baseline_trial_id`. Update `_trial_detail` (locate via grep) to include `is_baseline=row.is_baseline`. |
| `ui/src/lib/types.ts` | Regenerate from FastAPI OpenAPI schema (the types file is generated; rerun the generator). |

**Endpoints**

| Method | Path | Request body change | Response body change | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` | `config.baseline_params: dict[str, primitive] \| null` (optional) | `baseline_trial_id: str \| null` added to response | `VALIDATION_ERROR` (422) for non-primitive values |
| `GET` | `/api/v1/studies/{id}` | — | `baseline_trial_id: str \| null` added | — |
| `GET` | `/api/v1/studies/{id}/trials` | — | each row gets `is_baseline: bool` | — |

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
    per_query_metrics: dict[str, Any] | None = None,
    duration_ms: int | None,
    status: str,
    error: str | None,
    started_at: datetime | None,
    ended_at: datetime | None,
    is_baseline: bool = False,  # NEW
) -> Trial: ...
```

**Pydantic schemas**

```python
class StudyConfigSpec(BaseModel):
    # ... existing fields ...
    baseline_params: dict[str, str | int | float | bool | None] | None = None
    """feat_study_baseline_trial FR-6: explicit baseline params (tier b
    of the resolver fallback). Stored in studies.config JSONB."""

class StudyDetail(BaseModel):
    # ... existing fields ...
    baseline_trial_id: str | None  # NEW

class TrialDetail(BaseModel):
    # ... existing fields ...
    is_baseline: bool  # NEW
```

**Tasks**

1. Add `baseline_params` field to `StudyConfigSpec`. Verify Pydantic rejects nested-dict values via a contract test.
2. Add `baseline_trial_id` to `StudyDetail`. Update `_detail` constructor in `studies.py:121`.
3. Add `is_baseline` to `TrialDetail`. Locate the trial-detail builder in `studies.py` (search for `TrialDetail(`) and add the field. (Repo signature already extended in Story 1.1.)
4. Write contract tests asserting:
   - `POST /api/v1/studies` accepts `config.baseline_params={"foo": 1, "bar": "x"}`.
   - `POST /api/v1/studies` rejects `config.baseline_params={"nested": {"dict": 1}}` with 422 `VALIDATION_ERROR`.
   - `GET /api/v1/studies/{id}` response contains `baseline_trial_id` key (null when unset).
   - `GET /api/v1/studies/{id}/trials` rows include `is_baseline` (false when unset).
5. Re-run `pnpm typecheck` in `ui/` after the OpenAPI types regenerate.

**Definition of Done**

- 6+ contract tests covering the new fields.
- TypeScript build (`pnpm build`) green with regenerated types.
- AC-9, AC-14 covered.

---

### Story 1.6 — Repo filter updates: `is_baseline=FALSE` on aggregate / list reads (FR-11, AC-17)

**Outcome:** Trials-aggregate read paths exclude baseline rows by default. Operators never see baseline mixed into Optuna trial counts, best-trial selection, or confidence inputs.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_trials_aggregate_excludes_baseline.py` | Asserts FR-11 filter behavior on real Postgres. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/trial.py` | Add `AND is_baseline = FALSE` to ONLY these helpers (plan-cycle-2 F1: narrow scope so the trials-listing API can still return baselines): `aggregate_trials_summary`, `list_complete_trials_for_confidence` (or whatever Q2 of the 4-query pattern is named; verify via grep), `list_top_trials` (the digest worker's top-10 helper), AND the auto-followup-input fetch (the repo helper that feeds `compute_first_decile_extremum`; verify via grep for callers of `compute_first_decile_max`). **DO NOT** add the filter to the helper backing `GET /api/v1/studies/{id}/trials` (likely named `list_trials_for_study` or similar — verify via grep). That endpoint MUST return baseline rows so the Story 3.1 UI toggle can reveal them. |
| `backend/workers/orchestrator.py` | Add `AND Trial.is_baseline == False` to `_last_n_all_failed` (line 320-337) and `_last_n_all_zero` (line 339-371) SELECT queries. Document the rationale inline (per spec FR-11 paragraph 2). |

**Endpoints:** N/A.

**Key interfaces**

```python
# backend/app/db/repo/trial.py
@dataclass
class TrialsSummary: ...  # unchanged

async def aggregate_trials_summary(db: AsyncSession, study_id: str) -> TrialsSummary:
    """Aggregate counts + best-trial selection for Optuna trials ONLY.

    FR-11: filters is_baseline=FALSE inline. Baseline trials are reported
    via the separate StudyDetail.baseline_trial_id surface.
    """
```

**Tasks**

1. Identify the in-scope helpers per the modified-files table above. **Explicitly do NOT** filter the trials-listing endpoint's repo helper (plan-cycle-2 F1). Add the filter inline to the in-scope helpers only.
2. Locate every direct SQL query in `backend/workers/` that reads `trials` (likely just the two orchestrator helpers). Add the filter + an inline comment citing FR-11.
3. Locate the digest worker's top-trials lookup (`backend/workers/digest.py` around the `_compute_top_trials` call). If it uses a repo function, the filter inherits; if direct SQL, add inline.
4. Update existing tests that assert `aggregate_trials_summary` results — they should still pass if no baseline row is seeded, but the test fixtures may need updating once Story 1.7 lands and integration tests seed baselines.
5. Write `test_trials_aggregate_excludes_baseline.py`: insert a study with 5 Optuna trials + 1 baseline trial (with the highest primary_metric); assert `summary.total == 5`, `summary.best_trial_id` is the best Optuna trial (NOT the baseline). Also assert the auto-followup fetch helper excludes baseline (the `first_decile_extremum` input list does not contain the baseline row).

**Definition of Done**

- AC-17 covered by integration test.
- Existing aggregate tests pass unchanged (no baseline rows seeded ⇒ no behavior difference).
- A new test asserts the trials-listing API helper (`list_trials_for_study` or equivalent) returns BOTH Optuna and baseline rows — the filter is NOT applied here (plan-cycle-2 F1 regression guard).

---

### Story 1.7 — Orchestrator integration: baseline phase before Optuna (FR-2, AC-1, AC-2, AC-3)

**Outcome:** `start_study` runs the baseline phase between search-space parse and Optuna polling. Synchronous wait with bounded timeout; calls FR-12 stamp helper on success; logs structured events for skip/fail/timeout. Resume path re-stamps existing complete baselines via the same helper.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_orchestrator_baseline_trial.py` | Real-backend end-to-end: study creation → baseline enqueue → wait → stamp → Optuna phase. |
| `backend/tests/integration/test_baseline_late_completion_stamp.py` | Worker self-stamp covers the timeout case. |
| `backend/tests/integration/test_baseline_resume.py` | resume_study handles all four baseline-row-state cases. |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/orchestrator.py` | Insert baseline-resolution + enqueue + wait + stamp phase between line 170 (search-space parse) and line 173 (polling loop start). Use the polling pattern from line 182-188 (fresh session per tick). Reuse `_REPLENISH_TICK_S = 1.0` constant. Add helpers `_resolve_and_enqueue_baseline`, `_wait_for_baseline_trial`. |

**Endpoints:** N/A.

**Key interfaces**

```python
# backend/workers/orchestrator.py
from typing import Literal
from dataclasses import dataclass

@dataclass(frozen=True)
class BaselineEnqueueResult:
    """Discriminated result from _resolve_and_enqueue_baseline.

    kind:
    - "skipped": params resolution returned None — no baseline runs; proceed to Optuna immediately.
    - "enqueued": fresh job accepted; wait by trial_id.
    - "deduped": Arq rejected as duplicate (an earlier orchestrator invocation already
      enqueued for this study); wait by study_id since the original trial_id is unknown.
    """
    kind: Literal["skipped", "enqueued", "deduped"]
    trial_id: str | None = None  # set when kind == "enqueued"

async def _resolve_and_enqueue_baseline(
    db: AsyncSession,
    arq_pool: ArqRedis,
    study: Study,
) -> BaselineEnqueueResult:
    """Resolve params via FR-3, enqueue baseline job with deterministic _job_id.

    (Plan-cycle-2 F2: the result type is a discriminated union, NOT a bare
    str | None, so the caller can distinguish 'no baseline' from 'deduped'.)
    """

async def _wait_for_baseline_trial_by_id(
    session_factory: async_sessionmaker,
    study_id: str,
    trial_id: str,
    wait_s: float,
) -> Trial | None:
    """Poll the trials table by trial_id until terminal.

    Used when BaselineEnqueueResult.kind == 'enqueued'.
    """

async def _wait_for_baseline_trial_by_study(
    session_factory: async_sessionmaker,
    study_id: str,
    wait_s: float,
) -> Trial | None:
    """Poll the trials table by study_id for any terminal is_baseline=TRUE row.

    Used when BaselineEnqueueResult.kind == 'deduped' — the trial_id from
    the original enqueue is unknown to this orchestrator invocation, so
    we observe any complete or failed baseline trial for the study.
    """
```

**Tasks**

1. Insert new section "B'. Baseline phase" between sections B and C of `start_study` (or equivalent positioning per the current orchestrator structure).
2. Call `_resolve_and_enqueue_baseline(db, arq_pool, study)`. The helper internally calls `resolve_baseline_params` (Story 1.2) and enqueues with `_job_id=f"baseline:{study.id}"`. Returns a `BaselineEnqueueResult`.
3. **Dispatch on `result.kind`** (plan-cycle-2 F2):
   - `"skipped"` (resolver returned None): log `event_type="baseline_skipped"` and proceed immediately to Optuna phase. Do NOT call wait helpers.
   - `"enqueued"`: call `_wait_for_baseline_trial_by_id(..., trial_id=result.trial_id, wait_s)`.
   - `"deduped"`: log `event_type="baseline_enqueue_deduped"` and call `_wait_for_baseline_trial_by_study(..., wait_s)`.
4. On terminal Trial row with `status='complete'` (from either wait helper): call `services.study_state.stamp_baseline_trial` (Story 1.3); then `await db.commit()` (plan F4); log `event_type="baseline_stamped"`.
5. On terminal Trial row with `status='failed'`: log `event_type="baseline_failed"` with the trial's `error` text; leave `baseline_trial_id IS NULL`; proceed.
6. On wait timeout: log `event_type="baseline_wait_timeout"`; leave NULL; proceed (worker will self-stamp later).
7. Resume path: in the orchestrator's existing entry logic, BEFORE the baseline phase, check whether a complete baseline row exists for the study. If yes + unstamped, call stamp helper + commit. If failed/pruned only, skip baseline. If none, run normally.
10. Write `test_orchestrator_baseline_trial.py` (real-backend, mock adapter at `search_batch`): creates a study → runs `start_study` → asserts baseline trial row written, baseline_trial_id stamped, Optuna trials enqueue afterwards. Covers AC-1, AC-2, AC-3 with 4 separate fixtures (each tier of the resolver hit).
11. Write `test_baseline_late_completion_stamp.py`: uses the Story 1.4 fault seam (`FEAT_STUDY_BASELINE_TRIAL_FAULT=delay_before_score` + `FEAT_STUDY_BASELINE_TRIAL_FAULT_DELAY_S=120`) to force the worker to outlast the orchestrator's wait; asserts orchestrator's wait times out, baseline_trial_id is NULL, then worker eventually completes and self-stamps.
12. Write `test_baseline_resume.py`: 4 scenarios (no baseline row → run from scratch; complete unstamped → re-stamp via helper; failed only → skip; complete already-stamped → idempotent).
13. Write `test_baseline_enqueue_deduped.py`: simulate the dedupe path by pre-enqueueing a `_job_id=f"baseline:{study_id}"` job, then invoking `start_study` and asserting:
    - `_resolve_and_enqueue_baseline` returns `BaselineEnqueueResult(kind="deduped", trial_id=None)`.
    - The orchestrator calls `_wait_for_baseline_trial_by_study`, NOT `_wait_for_baseline_trial_by_id`.
    - On the original job's eventual completion, the stamp helper lands the FK on the studies row.
14. Write a unit test for the `BaselineEnqueueResult` discriminated-union — asserts the 3 kinds are mutually exclusive and the trial_id is non-None only for `"enqueued"` (regression guard for plan-cycle-2 F2).

**Definition of Done**

- AC-1, AC-2, AC-3, AC-16 covered by integration tests.
- New structured-log events emitted: `baseline_skipped`, `baseline_failed`, `baseline_stamped`, `baseline_wait_timeout`, `baseline_enqueue_deduped`.
- `make test-integration` green.

---

### Phase Gate 1 — Foundation tests green + cross-model review

**Hard gate**: cannot start Epic 2 until all of the following pass:

1. `make test-unit` green.
2. `make test-integration` green.
3. `make test-contract` green.
4. `make typecheck` green.
5. `make lint` green.
6. Coverage on new files (`baseline_resolver.py`, `workers/baseline.py`, `stamp_baseline_trial` helper) ≥ 90%.
7. Migration round-trip clean.
8. GPT-5.5 phase-gate review pass with no High findings on the implementation diff.

---

## Epic 2 — Consumer activation: confidence + auto-followup + digest flip (FR-4, FR-5, FR-7)

The existing data-driven consumers flip from `runner_up` to `baseline` once the Epic 1 surfaces are populated. Each story is a tightly-scoped surgical change.

### Story 2.1 — `compute_study_confidence` baseline branch + PR body contract test (FR-4, AC-4, AC-5, AC-6, AC-12)

**Outcome:** When `study.baseline_trial_id` is set AND the baseline trial has `per_query_metrics`, the confidence orchestrator emits `comparison_against = "baseline"` (FR-4). Falls back to `"runner_up"` otherwise. The existing 5 tests asserting `runner_up` remain green (regression coverage). The PR body (rendered from `compute_study_confidence` output via `backend/workers/git_pr.py:513`) automatically emits "vs baseline" — covered by a new contract test fixture (plan F5).

**New files**: None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/confidence.py` | Add `baseline_trial: Any \| None = None` kwarg to `compute_study_confidence`. At line 624, replace literal `comparison_against="runner_up"` with the FR-4 conditional. Update docstring. |
| `backend/app/services/study_confidence.py` | The fetch glue runs an additional query: `Q-1a: baseline_trial` (load by `study.baseline_trial_id` if non-NULL). Pass into `compute_study_confidence`. |
| `backend/tests/unit/domain/study/test_confidence.py` | Add 3+ tests for the baseline branch + 2+ regression tests for the fallback path. |
| `backend/tests/integration/test_studies_api_confidence.py` | Add an integration test with baseline+winner both having `per_query_metrics`; assert API response shows `comparison_against="baseline"`. |
| `backend/tests/contract/test_pr_body_confidence_section.py` | **Add a new fixture (plan F5)** with `baseline_trial_id` set + both winner + baseline have `per_query_metrics` + 12 regressors; assert PR body contains `"12 regressed (vs baseline)"`. The existing 2 `runner_up` fixtures stay green. AC-12 coverage. |

**Endpoints:** N/A — response shape unchanged (`comparison_against` is already typed `Literal["runner_up", "baseline"]`).

**Key interfaces**

```python
# backend/app/domain/study/confidence.py
def compute_study_confidence(
    *,
    study_objective: dict[str, Any],
    study_best_metric: float | None,
    winner_trial: Any | None,
    runner_up_trial: Any | None,
    baseline_trial: Any | None = None,  # NEW
    complete_trials_summary: list[tuple[float, int]],
    query_text_by_id: dict[str, str] | None = None,
) -> ConfidenceShape | None:
    """... (FR-4: baseline branch when baseline_trial is non-None AND has per_query_metrics)"""
```

**Tasks**

1. Add `baseline_trial: Any | None = None` to the `compute_study_confidence` signature.
2. At line 608 (the `if runner_up_trial is not None and winner_per_query and runner_up_trial.per_query_metrics:` block), wrap in a new conditional: prefer the baseline branch first.
3. Baseline branch: if `baseline_trial is not None and baseline_trial.per_query_metrics and winner_per_query`: call `compute_outcome_summary` with `comparison_per_query=baseline_trial.per_query_metrics`; build `PerQueryOutcomesShape(comparison_against="baseline", ...)`.
4. Fallback (runner-up): keep the existing branch verbatim.
5. Update `backend/app/services/study_confidence.py:fetch_study_confidence` to add a 5th query (or join into existing): load baseline trial by `study.baseline_trial_id`. Pass into `compute_study_confidence`.
6. Write unit tests covering AC-4 (baseline branch hits), AC-5 (baseline_trial_id NULL → runner_up), AC-6 (baseline trial has no per_query_metrics → runner_up).
7. Write integration test covering the full happy path via the API.
8. Confirm the 5 existing tests asserting `runner_up` still pass (regression coverage).

**Definition of Done**

- AC-4, AC-5, AC-6, AC-12 covered.
- All existing tests asserting `runner_up` still pass.
- Coverage on the new branch ≥ 95%.

---

### Story 2.2 — `evaluate_chain_gate` direction-aware + lift-over-baseline (FR-5, AC-7, AC-8, AC-18)

**Outcome:** Auto-followup gate computes lift against the explicit baseline (`parent.baseline_metric`) when set, falls back to first-decile-extremum otherwise. Direction-aware: minimize objectives invert the sign so "better than baseline" is always positive. Renames `compute_first_decile_max` → `compute_first_decile_extremum` (forward-only).

**New files**: None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/auto_followup.py` | Rename `compute_first_decile_max` → `compute_first_decile_extremum`. Add `direction: Literal["maximize", "minimize"]` kwarg (default `"maximize"`). Modify `evaluate_chain_gate` to take `direction` (also default `"maximize"`), prefer `parent.baseline_metric` over first-decile when set, sign-flip lift for minimize. Rename `ChainGateOutcome.first_decile_max` → `first_decile_extremum`. Update module docstring (delete the "When feat_study_baseline_trial ships..." sentence). |
| `backend/workers/auto_followup.py` (or wherever `evaluate_chain_gate` is called from) | Pass `direction=parent.objective.get("direction", "maximize")` to the gate. |
| `backend/tests/unit/domain/study/test_auto_followup.py` | Update existing tests for the rename. Add tests covering baseline-branch (AC-7), fallback (AC-8), and minimize direction (AC-18). |

**Endpoints:** N/A.

**Key interfaces**

```python
# backend/app/domain/study/auto_followup.py
def compute_first_decile_extremum(
    complete_trials: Iterable[Any],
    direction: Literal["maximize", "minimize"] = "maximize",
) -> float | None: ...

def evaluate_chain_gate(
    parent: Any,
    complete_trials: Iterable[Any],
    *,
    direction: Literal["maximize", "minimize"] = "maximize",
    epsilon: float = 0.005,
) -> ChainGateOutcome: ...

@dataclass(frozen=True)
class ChainGateOutcome:
    decision: ChainGateDecision
    lift: float | None = None
    first_decile_extremum: float | None = None  # RENAMED
    epsilon: float = 0.005
```

**Tasks**

1. Rename the helper function + the dataclass field. Update all call sites and tests (only inside `auto_followup.py` + its tests + 1 worker entry point).
2. Add `direction` kwarg. For minimize: `compute_first_decile_extremum` returns `min` of the first decile (not `max`); `evaluate_chain_gate` computes lift as `baseline_metric - best_metric` instead of `best_metric - baseline_metric`.
3. The gate decision (`if lift > epsilon: ENQUEUE`) stays unchanged — the lift is direction-normalized.
4. Update the module docstring per FR-5 ("FR-2b activated: when `parent.baseline_metric IS NOT NULL`, lift is computed directly against the baseline. Direction-aware via the `direction` argument (added 2026-05-25).").
5. Update worker caller(s) to pass `direction=parent.objective.get("direction", "maximize")`.
6. Write/update unit tests covering AC-7 (baseline branch), AC-8 (fallback w/ rename), AC-18 (minimize direction).
7. Capture a 1-line entry in `docs/03_runbooks/auto-followup-debugging.md` noting the direction-awareness now in place.

**Definition of Done**

- AC-7, AC-8, AC-18 covered.
- All existing `feat_auto_followup_studies` tests still pass after rename.
- Runbook updated.

---

### Story 2.3 — Digest system prompt + ConfidencePanel glossary update (FR-7)

**Outcome:** The digest narrative LLM receives explicit baseline framing guidance. The ConfidencePanel tooltip glossary entry reflects both wire values.

**New files**: None.

**Modified files**

| File | Change |
|---|---|
| `prompts/digest_narrative.system.md` | Add 1-2 sentence guidance per spec FR-7: "When `<per_query_outcomes>` has `comparison_against = 'baseline'`, regressors should be described as 'regressed vs the operator's current production baseline' — not 'vs the runner-up trial'. Lead the narrative with this baseline framing when present." |
| `ui/src/lib/glossary.ts` | Update `confidence.comparison_against` entry (line 676) with bi-state text that explains both wire values. Add new entry `trials.is_baseline` per spec UX tooltip table. |
| `backend/tests/unit/workers/test_digest_prompt_render.py` | Add a snapshot test for the system prompt's baseline-mention sentence. Add a `baseline`-branch render test (the existing 2 `runner_up` tests stay green). |
| `ui/src/__tests__/lib/glossary.test.ts` (if exists; else new) | Assert the new glossary entries' shape. |

**Endpoints:** N/A.

**Tasks**

1. Edit `prompts/digest_narrative.system.md` near the existing line 36-37 (which already mentions both wire values). Add the FR-7 narrative-framing sentence.
2. Update `ui/src/lib/glossary.ts` `confidence.comparison_against` entry. Add `trials.is_baseline` entry.
3. Update any existing snapshot tests for the system prompt to include the new sentence.
4. Add a unit test for the digest user-prompt render when `comparison_against=baseline` is in the confidence payload.

**Definition of Done**

- AC-11, AC-12 covered.
- Existing digest prompt tests pass (with updated snapshot).
- Glossary entries renderable in UI (verify via the existing glossary test pattern).

---

### Phase Gate 2 — Activation tests green + cross-model review

**Hard gate**: cannot start Epic 3 until:

1. All of Epic 1's gate criteria still pass.
2. `make test-unit && make test-integration && make test-contract` green.
3. The 5 tests originally asserting `runner_up == "runner_up"` still pass (regression).
4. The new baseline-branch tests pass.
5. GPT-5.5 phase-gate review pass with no High findings.

---

## Epic 3 — Frontend: trials-table baseline filter + Baseline badge + ConfidencePanel data-driven flip (FR-9)

### Story 3.1 — trials-table baseline filter toggle + Baseline badge (FR-9, AC-10)

**Outcome:** The trials-table on the study-detail page filters out baseline rows by default. A "Show baseline trial" toggle reveals it at the top of the table with a "Baseline" badge. The ConfidencePanel label flip happens automatically via the data-driven branch in `confidence-panel.tsx` (already implemented — verify via the existing `confidence-panel.test.tsx:136` test).

**New files**: None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/trials-table.tsx` | Add a `showBaseline: boolean` state (default `false`). Add a `<Switch>` toggle labeled "Show baseline trial". Filter the trials data by `is_baseline === false` unless toggled. When toggled, prepend the baseline row at the top with a `<Badge>Baseline</Badge>` next to the trial-number cell. |
| `ui/src/components/studies/trials-table.column-config.tsx` | Conditional column rendering: if `row.is_baseline` true, render "Baseline" instead of `optuna_trial_number=-1`. |
| `ui/src/__tests__/components/studies/trials-table.test.tsx` (or new) | Assert default filter, toggle visibility, baseline badge rendering. |
| `ui/src/components/studies/confidence-panel.tsx` | No code change — the existing data-driven branch handles the flip (verify the existing test at line 136 still passes). Optionally update inline-help tooltips per spec §11. |

**UI element inventory**

| Element | Type | Label | Data source | Interaction |
|---|---|---|---|---|
| "Show baseline trial" toggle | `<Switch>` | "Show baseline trial" | local state `showBaseline` | `onCheckedChange` flips visibility |
| "Baseline" badge | `<Badge variant="secondary">` | "Baseline" | row.is_baseline | non-interactive |

**State dependency analysis**

State being added: `showBaseline: boolean` (local to `<TrialsTable>`).
Referenced by: only the filter computation + the toggle widget. No cross-component side effects.

**Tasks**

1. Locate the trials-table component (`ui/src/components/studies/trials-table.tsx`).
2. Add `showBaseline` useState.
3. Wrap the data filter: `const visibleTrials = showBaseline ? [baselineRow, ...optunaTrials] : optunaTrials` (where `baselineRow` is the trial with `is_baseline=true` if present).
4. Add the toggle component above the table.
5. Update the trial-number cell column-config to render "Baseline" for `is_baseline=true` rows.
6. Write a vitest unit test asserting the default-filter behavior and the toggle.
7. Run `pnpm typecheck` and `pnpm test`.

**Definition of Done**

- AC-10 covered.
- `pnpm typecheck && pnpm test` green.
- Existing tests (e.g., `study-action-bar-cascade.test.tsx`, `auto-followup-chain-panel.test.tsx`, `confidence-panel.test.tsx:136`) all pass.

---

### Story 3.2 — E2E test for baseline trial flow (FR-9 coverage, AC-10, AC-12)

**Outcome:** A real-backend Playwright test seeds a study via API with `config.baseline_params`, waits for completion, asserts ConfidencePanel renders "vs baseline" and the trials-table toggle reveals the Baseline badge.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/baseline-trial.spec.ts` | Playwright E2E: API-seeded study with `baseline_params` → wait → assert UI. |

**Modified files**: None.

**Tasks**

1. Use existing E2E test fixtures + helpers (cluster, query set, template, judgment list seeds).
2. POST a study via `page.request.post('/api/v1/studies', { data: { ..., config: { ..., baseline_params: { ... } } } })`.
3. Poll for study completion (existing helper).
4. Navigate to `/studies/{id}`.
5. Assert ConfidencePanel renders "vs baseline" (locator `text=/vs baseline/i`).
6. Click "Show baseline trial" toggle (locator `text=Show baseline trial`).
7. Assert "Baseline" badge appears (locator `text=Baseline >> first-row`).
8. Run `pnpm playwright test ui/tests/e2e/baseline-trial.spec.ts` against a real backend.

**Definition of Done**

- AC-10 covered by E2E.
- Test runs against real backend (no `page.route()` mocking per CLAUDE.md).
- E2E suite green.

---

### Phase Gate 3 — Frontend + E2E green

1. `pnpm typecheck && pnpm test && pnpm build` green.
2. `pnpm playwright test` (full suite) green.
3. Visual sanity check of the trials-table toggle on the dev stack.

---

## Epic 4 — Documentation + final cross-model + close-out

### Story 4.1 — Documentation updates (spec §15)

**Outcome:** Architecture / runbook / data-model docs reflect the new columns + workflow.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/data-model.md` | Update §"studies" with `baseline_trial_id` row. Update §"trials" with `is_baseline` row + the `uq_trials_study_baseline_complete` partial index. |
| `docs/01_architecture/optimization.md` (if exists; else add a section to `mvp1-overview.md`) | Add a 2-3 sentence section "Baseline trial" describing the non-Optuna baseline phase. |
| `docs/03_runbooks/study-lifecycle-debugging.md` | Document the 5 new log event types: `baseline_skipped`, `baseline_failed`, `baseline_stamped`, `baseline_wait_timeout`, `baseline_enqueue_deduped`. Add a section "Baseline trial troubleshooting". |
| `docs/03_runbooks/auto-followup-debugging.md` | Note the direction-awareness fix in `evaluate_chain_gate` (FR-5). |
| `state.md` | Update active priorities + Alembic head (`0019` → `0020`) once merged. (This happens AFTER the impl-execute Step 8 finalization, not during this story.) |
| `architecture.md` | No change (the topical doc updates above suffice). |
| `CLAUDE.md` | No change (no new absolute rules). |

**Tasks**

1. Update `data-model.md` (search for the existing `studies` + `trials` table sections; add new column rows in the existing tables).
2. Update `study-lifecycle-debugging.md` with the new log events.
3. Update `auto-followup-debugging.md` with the direction-awareness note.
4. Update `optimization.md` (or `mvp1-overview.md` if optimization.md doesn't exist).

**Definition of Done**

- All docs in spec §15 updated.
- No `<!-- TODO: -->` markers left behind.

---

### Story 4.2 — Final phase gate + GPT-5.5 review + close-out

**Outcome:** Implementation is fully verified end-to-end and ready for PR.

**Tasks**

1. Run the full test suite: `make test && cd ui && pnpm test && pnpm playwright test`.
2. Run the full lint + typecheck stack: `make lint && make typecheck && cd ui && pnpm typecheck && pnpm lint`.
3. Verify coverage gate: `pytest --cov` ≥ 80%. New files ≥ 90%.
4. Verify migration round-trip on a fresh DB.
5. GPT-5.5 final review on the diff (impl-execute Step 7).
6. Adjudicate any Gemini Code Assist comments after PR opens (impl-execute Step 6).
7. Update `state.md` post-merge (impl-execute Step 8.5).

**Definition of Done**

- All test suites green.
- Coverage gate passes.
- Migration round-trips.
- GPT-5.5 final review has zero open High findings.
- PR open with the full test evidence in the description.

---

## 3) Execution tracker

| Story | Status | Started | Completed | Tests passing | Notes |
|---|---|---|---|---|---|
| 1.1 — Migration 0020 + ORM + `repo.create_trial(is_baseline=…)` | pending | — | — | — | — |
| 1.2 — `resolve_baseline_params` | pending | — | — | — | — |
| 1.3 — `stamp_baseline_trial` helper | pending | — | — | — | reordered before worker (plan F1) |
| 1.4 — `run_baseline_trial` worker | pending | — | — | — | reordered after helper (plan F1) |
| 1.5 — Request/response schemas | pending | — | — | — | — |
| 1.6 — Repo filter updates | pending | — | — | — | — |
| 1.7 — Orchestrator integration | pending | — | — | — | — |
| **Phase Gate 1** | pending | — | — | — | — |
| 2.1 — Confidence baseline branch | pending | — | — | — | — |
| 2.2 — Auto-followup gate | pending | — | — | — | — |
| 2.3 — Digest prompt + glossary | pending | — | — | — | — |
| **Phase Gate 2** | pending | — | — | — | — |
| 3.1 — trials-table baseline filter | pending | — | — | — | — |
| 3.2 — E2E test | pending | — | — | — | — |
| **Phase Gate 3** | pending | — | — | — | — |
| 4.1 — Documentation | pending | — | — | — | — |
| 4.2 — Final close-out | pending | — | — | — | — |

## 4) Documentation update workstream (covered in Story 4.1)

See Story 4.1 for the explicit doc-update list. The standalone workstream tracker is the story's DoD.

## 5) Rollout

- No feature flags.
- Forward-only (no backfill).
- Migration is additive — safe to land mid-cycle.
- Operator-visible change after PR merge: PR bodies will start showing real `delta_pct` for new studies, ConfidencePanel will start showing "vs baseline" for new studies.

## 6) Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Resume-race double-baseline | High (data correctness) | 3-layer defense per spec D-16 (`_job_id` dedupe + partial unique index + idempotent UPDATE predicate) |
| Long baseline trial blocks Optuna start | Medium (UX latency) | Wait timeout formula (FR-2 step 5) caps at 600s; worker self-stamp covers late completions |
| Existing tests asserting `comparison_against == "runner_up"` start failing | Low (regression coverage erosion) | New fixtures don't set `baseline_trial_id`, so existing fixtures hit the FR-4 fallback branch unchanged |
| Auto-followup gate direction inversion latent bug uncovered | Low | This feature fixes the bug; no regression risk |
| OpenAPI types regeneration breaks frontend build | Low | Caught by Story 1.5 + `pnpm typecheck` in Phase Gate 1 |
