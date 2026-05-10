# Implementation Plan — feat_study_lifecycle (Phase 1 — Schema)

**Date:** 2026-05-10
**Status:** Approved (cross-model review converged 2026-05-10 — 3 cycles, 15 findings, all accepted + applied)
**Primary spec:** [feature_spec.md](feature_spec.md) (Phase 1 scope only)
**Deferred work:** [phase2_idea.md](phase2_idea.md) — Phase 2 (Orchestrator + API)
**Policy source(s):**
- [CLAUDE.md](../../../../CLAUDE.md) — Absolute Rules #1 (no commit to main), #5 (Alembic round-trip), #7 (Conventional Commits)
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — column-level shapes for all 7 tables
- [docs/02_product/planned_features/feat_study_lifecycle/feature_spec.md](feature_spec.md) §3 (In-scope), §9 (Data model), §11 (Edge flows)

---

## 0) Planning principles

- **Schema-first.** Phase 1 delivers the 7-table substrate that every downstream feature consumes (`infra_optuna_eval`'s `run_trial`, `feat_llm_judgments`'s `judgments`, `feat_digest_proposal`'s `digests`, etc.). No API, no orchestrator, no service layer.
- **Match infra_adapter_elastic's precedent.** That feature shipped its 2-table schema as Stories 1.2 (ORM) → 1.3 (Migration) → 1.4 (repos). Phase 1 here is the same structure scaled to 7 tables in one epic.
- **Repo footprint = "what downstream consumers need."** `infra_optuna_eval`'s `run_trial` reads `studies` / `query_templates` / `judgment_lists` / `queries` and writes `trials`. Phase 2's orchestrator + tests drive the rest. Phase 1 ships exactly enough to unblock both.
- **Cassette-replay first** — but this phase has zero engine I/O. All tests are DB-only.
- **Forward-only.** Migration `0003` builds on `0002_clusters_config_repos` (added by `infra_adapter_elastic`); the FKs to `clusters` resolve at upgrade time.

## 1) Scope traceability

Phase 1 has **zero direct FR trace** — all 7 FRs in the spec (FR-1 through FR-7) are Phase 2 deliverables. Phase 1 delivers the schema foundation each FR transitively requires.

| Phase 1 deliverable | Owning story | Notes |
|---|---|---|
| 7 ORM models registered with `Base.metadata` | Story 1.1 | required so Alembic `--autogenerate` sees them in Story 1.2 |
| Alembic migration `0003_study_lifecycle_schema` (forward + downgrade) | Story 1.2 | unblocks `infra_optuna_eval`'s `run_trial` (depends on `studies` + `trials` tables) |
| Minimal repository functions (~15 functions) | Story 1.3 | what `infra_optuna_eval` + Phase 2 + integration tests need |

**Phase 2 trace** (Phase 2 picks this up — listed for context):

| FR ID | Phase | Notes |
|---|---|---|
| FR-1 (Study CRUD endpoints) | Phase 2 | depends on Phase 1's `studies` + `query_*` + `judgment_lists` tables |
| FR-2 (Query-template CRUD) | Phase 2 | depends on Phase 1's `query_templates` |
| FR-3 (Query-set CRUD) | Phase 2 | depends on Phase 1's `query_sets`, `queries` |
| FR-4 (Orchestrator process) | Phase 2 | depends on Phase 1's `studies` + `infra_optuna_eval`'s `run_trial` |
| FR-5 (Resume-after-restart) | Phase 2 | depends on Phase 1's `studies.status` |
| FR-6 (Trials list endpoint) | Phase 2 | depends on Phase 1's `trials` + the `(study_id, primary_metric DESC NULLS LAST)` index |
| FR-7 (State-transition guard) | Phase 2 | depends on Phase 1's `studies.status` CHECK |

**Phase boundaries.** Per spec §3 (post-2026-05-10 patch), Phase 1 = Schema only; Phase 2 = Orchestrator + API. See [phase2_idea.md](phase2_idea.md) for the deferred FRs.

## 2) Delivery structure

**Single epic, three stories.** No phase gates within the epic — the 3 stories run sequentially with the standard backend verification gate after each.

### Conventions (project-specific)

- All ORM models use `Base` from [`backend/app/db/base.py`](../../../../backend/app/db/base.py); `id: Mapped[str] = mapped_column(String(36), primary_key=True)` (UUIDv7 hex). Timestamps `TIMESTAMPTZ` via `DateTime(timezone=True)`. snake_case columns. Mirror the [`backend/app/db/models/cluster.py`](../../../../backend/app/db/models/cluster.py) precedent.
- Repo functions take `db: AsyncSession` as the first arg, use `db.flush()` (caller commits), live in `backend/app/db/repo/<aggregate>.py`. Export via `backend/app/db/repo/__init__.py` `__all__`.
- JSONB via `from sqlalchemy.dialects.postgresql import JSONB`.
- CHECK constraints in `__table_args__`, named `<table>_<column>_check` (mirror [`migrations/versions/0002_clusters_config_repos.py`](../../../../migrations/versions/0002_clusters_config_repos.py)).
- The `migrations/env.py` side-effect import (`from backend.app.db import models  # noqa: F401`) already loads every model module via `__init__.py` re-exports. New model files only need to be added to `__init__.py`'s `__all__`.

### AI Agent Execution Protocol

0. Read [`architecture.md`](../../../../architecture.md) and [`state.md`](../../../../state.md) before Story 1.1.
1. Read scope: verify story outcome + new files + DoD against this plan.
2. Implement backend in dependency order: models → migration → repos.
3. Run touched test layers (`make test-unit`, `make test-integration -m integration`).
4. Update docs in same PR when behavior/contract changes (state.md Alembic head bump after Story 1.2).
5. Verify migration round-trip after Story 1.2 (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`).
6. Attach evidence in PR description: commands run, pass/fail counts, files changed.

---

## Epic 1 — Schema

### Story 1.1 — ORM models for the 7 tables

**Outcome:** `from backend.app.db.models import QueryTemplate, QuerySet, Query, Study, Trial, JudgmentList, Proposal` succeeds; `Base.metadata.tables` contains all 7 names so Alembic `--autogenerate` (Story 1.2) picks them up.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/models/query_template.py` | `QueryTemplate` ORM model — Jinja template body + declared params + version + parent_id self-FK |
| `backend/app/db/models/query_set.py` | `QuerySet` ORM model — name + cluster_id (FK to clusters) + description |
| `backend/app/db/models/query.py` | `Query` ORM model — query_set_id (FK CASCADE) + query_text + reference_answer + metadata. **Python attribute is `query_metadata`** (DB column `metadata`) — `metadata` is reserved on SQLAlchemy `DeclarativeBase` (it's the table registry); a `metadata` mapped column collides at class definition. See key-interface block below. |
| `backend/app/db/models/study.py` | `Study` ORM model — full MVP1 shape (5 enum values for status, baseline_metric, failed_reason, optuna_study_name UNIQUE, parent_study_id self-FK, denormalized best_metric + best_trial_id) |
| `backend/app/db/models/trial.py` | `Trial` ORM model — study_id (FK CASCADE) + optuna_trial_number + params + metrics JSONB + primary_metric REAL denormalized + status + duration_ms + error |
| `backend/app/db/models/judgment_list.py` | `JudgmentList` ORM model — full MVP1 shape (cluster_id, target, current_template_id, status, failed_reason, calibration JSONB) |
| `backend/app/db/models/proposal.py` | `Proposal` ORM model — full MVP1 shape (study_id nullable, study_trial_id nullable, cluster_id, template_id, config_diff, metric_delta, status, pr_url, pr_state, pr_merged_at, pr_open_error, rejected_reason) |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/__init__.py` | Re-export the 7 new classes; extend `__all__` to include them alongside existing `Cluster` + `ConfigRepo` |

**Key interface — Query (illustrates the SQLAlchemy `metadata` workaround)**

```python
# backend/app/db/models/query.py
from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    query_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_sets.id", ondelete="CASCADE"), nullable=False
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `metadata` is reserved on `DeclarativeBase` (it's the table registry).
    # Use a different Python attribute name with the explicit DB column name.
    query_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
```

**Key interface — Study (representative shape for the others)**

```python
# backend/app/db/models/study.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Study(Base):
    __tablename__ = "studies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'cancelled', 'failed')",
            name="studies_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Use Text for free-form fields documented as TEXT in data-model.md;
    # PG treats VARCHAR-without-length and TEXT identically, but Text matches
    # the documented schema and keeps intent obvious to future readers.
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cluster_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clusters.id"), nullable=False
    )
    target: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_templates.id"), nullable=False
    )
    query_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_sets.id"), nullable=False
    )
    judgment_list_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("judgment_lists.id"), nullable=False
    )
    search_space: Mapped[dict] = mapped_column(JSONB, nullable=False)
    objective: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    failed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    optuna_study_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    parent_study_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("studies.id"), nullable=True
    )
    baseline_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_trial_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

(`Float` is the SQLAlchemy 2.0 typed equivalent of the PG `REAL` column type used in
data-model.md for `baseline_metric`, `best_metric`, `primary_metric`.)

(The other 6 models follow the same pattern — see data-model.md §`query_templates / query_sets / queries`, §`judgment_lists`, §`studies, trials`, §`proposals` for column-level shapes. The plan does not duplicate the SQL DDL here; it's authoritatively in data-model.md.)

**Tasks**

1. Create the 7 model files per the column-level shapes in [data-model.md](../../../01_architecture/data-model.md).
2. Update `backend/app/db/models/__init__.py` to import + re-export each new class via `__all__`. The existing `Cluster` + `ConfigRepo` re-exports stay.
3. **Do not** modify `migrations/env.py` — it already imports `backend.app.db.models` as a side-effect, which now resolves to the larger registry.

**DoD**

- `from backend.app.db.models import QueryTemplate, QuerySet, Query, Study, Trial, JudgmentList, Proposal` succeeds without error.
- `Base.metadata.tables` after import contains: `clusters`, `config_repos` (from infra_adapter_elastic), plus all 7 new tables: `query_templates`, `query_sets`, `queries`, `studies`, `trials`, `judgment_lists`, `proposals`.
- `make lint typecheck` green.
- (No tests here — Story 1.2's migration round-trip exercises the schema; Story 1.3's repo tests exercise via the DB.)

---

### Story 1.2 — Alembic migration `0003_study_lifecycle_schema`

**Outcome:** `alembic upgrade head` against a `0002`-state DB creates all 7 tables in their full MVP1 shape per [data-model.md](../../../01_architecture/data-model.md). `alembic downgrade -1` cleanly removes them in reverse FK order. `alembic_version` advances `0002` → `0003`.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0003_study_lifecycle_schema.py` | Migration creating all 7 tables + CHECK constraints + the `trials_study_metric` index |
| `backend/tests/integration/test_study_lifecycle_migration.py` | Round-trip + schema-introspection assertions (column-level NOT NULLs, FK targets + ON DELETE CASCADE, UNIQUE constraints, indexes, all 5 CHECK constraints) |

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_migrations.py` | Bump head version assertion `0002` → `0003` (one-line change at the existing assertion site, mirrors the equivalent change made in `infra_adapter_elastic` Story 1.3 commit `1b80290`) |
| (no migrations/env.py change) | `migrations/env.py` already side-effect-imports `backend.app.db.models` — the new classes register automatically through Story 1.1's `__init__.py` update |

**Migration body — sequence**

1. `op.create_table("query_templates", ...)` — no FK out except self-FK (`parent_id`); UNIQUE on `(name, version)`.
2. `op.create_table("query_sets", ...)` — FK to `clusters`.
3. `op.create_table("queries", ...)` — FK CASCADE to `query_sets`.
4. `op.create_table("judgment_lists", ...)` — FKs to `query_sets`, `clusters`, `query_templates`; CHECK on `status`.
5. `op.create_table("studies", ...)` — FKs to `clusters`, `query_templates`, `query_sets`, `judgment_lists`, self-FK on `parent_study_id`; CHECK on `status` (5 values).
6. `op.create_table("trials", ...)` — FK CASCADE to `studies`; CHECK on `status` (3 values).
7. `op.create_index("trials_study_metric", "trials", ["study_id", sa.text("primary_metric DESC NULLS LAST")])` — for "top trials by metric" queries.
8. `op.create_table("proposals", ...)` — FKs to `studies`, `trials`, `clusters`, `query_templates`; CHECK on `status` (4 values: `pending`, `pr_opened`, `pr_merged`, `rejected`); CHECK on `pr_state` (nullable; values `open`, `closed`, `merged`).

`downgrade()` drops in reverse: `proposals` → `trials_study_metric` index → `trials` → `studies` → `judgment_lists` → `queries` → `query_sets` → `query_templates`.

**Tasks**

1. Run `make migrate-create name=study_lifecycle_schema` (which calls `alembic revision --autogenerate --rev-id 0003`) and replace the generated body with the deterministic `op.create_table(...)` calls above. Hand-write rather than relying on autogenerate — control over CHECK constraint names and FK ordering matters.
2. Verify round-trip locally: `make up` → `make migrate` → `docker compose exec -T api alembic downgrade -1 && docker compose exec -T api alembic upgrade head`. Assert no errors and `\dt` shows all 7 tables after upgrade, none of them after downgrade.
3. Add integration test `backend/tests/integration/test_study_lifecycle_migration.py` asserting (per cycle 1 GPT-5.5 F7 — schema-introspection coverage, not just CHECK constraints):
   - **Existence**: All 7 tables exist after `upgrade head`; all 7 are gone after `downgrade -1`.
   - **CHECK constraints** (5 total):
     - `studies.status` rejects `'foo'`; accepts each of the 5 documented values (`queued`, `running`, `completed`, `cancelled`, `failed`).
     - `trials.status` rejects `'archived'`; accepts each of `complete`, `failed`, `pruned`.
     - `judgment_lists.status` rejects `'cancelled'`; accepts each of `generating`, `complete`, `failed`.
     - `proposals.status` rejects `'archived'`; accepts each of `pending`, `pr_opened`, `pr_merged`, `rejected`.
     - `proposals.pr_state` accepts NULL; rejects `'archived'`; accepts each of `open`, `closed`, `merged`.
     (`judgments.rating` CHECK is NOT in scope — that's `feat_llm_judgments`'s migration to add.)
   - **NOT NULL coverage**: assert via `information_schema.columns` query that `studies.{name, cluster_id, target, template_id, query_set_id, judgment_list_id, search_space, objective, config, status, optuna_study_name, created_at}` are NOT NULL; same shape for the other 6 tables (per data-model.md). One assertion per nullable/non-nullable column boundary.
   - **FK targets and ON DELETE behavior**: query `information_schema.referential_constraints` to assert:
     - `queries.query_set_id → query_sets.id` with `ON DELETE CASCADE`.
     - `trials.study_id → studies.id` with `ON DELETE CASCADE`.
     - `studies.{cluster_id, template_id, query_set_id, judgment_list_id}` FK targets resolve; default `ON DELETE` is `NO ACTION`.
     - `judgment_lists.{cluster_id, query_set_id, current_template_id}` FK targets resolve.
     - Self-FK on `query_templates.parent_id → query_templates.id` resolves.
     - Self-FK on `studies.parent_study_id → studies.id` resolves.
     - `proposals.{study_id, study_trial_id, cluster_id, template_id}` FK targets resolve.
   - **UNIQUE constraints**: assert via `pg_constraint` query:
     - `query_templates(name, version)` composite UNIQUE.
     - `studies.optuna_study_name` UNIQUE.
     - `query_sets.name` UNIQUE.
     - `judgment_lists.name` UNIQUE.
   - **Indexes**: `pg_indexes` query asserts `trials_study_metric` index exists with columns `(study_id, primary_metric DESC NULLS LAST)`.
   - **Cascade behavior**: insert a `study` + 1 `trial`; delete the `study`; assert the `trial` row was cascade-deleted. Same for `query_set` → `queries`.

**DoD**

- `alembic upgrade head` from a `0002`-state DB results in `0003` `alembic_version` row + all 7 tables. (CLAUDE.md Rule #5)
- `alembic downgrade -1 && alembic upgrade head` round-trips cleanly.
- `backend/tests/integration/test_study_lifecycle_migration.py` passes (CI service-container Postgres).
- `make migrate` continues to work end-to-end via the existing Makefile target.
- `state.md` Alembic head reference updates `0002_clusters_config_repos` → `0003_study_lifecycle_schema` (deferred to the post-implementation Step 2 doc-update workstream — not in this story's diff).

---

### Story 1.3 — Minimal repo functions (~15 functions)

**Outcome:** Phase 1 ships the repo functions Phase 1 itself needs (round-trip seeding for the migration tests) plus the read/write set `infra_optuna_eval`'s `run_trial` consumes (load study/template/judgment_list/queries; INSERT one trial row per run). **Phase 2 extends this set** with cursor pagination, status filtering, `?since=` filtering, status-mutation helpers, denormalization of `best_metric` / `best_trial_id`, `trials_summary` aggregations, and the bulk CSV upload helper for `query-sets/{id}/queries`. The Phase 1 cut is intentionally narrower than "everything Phase 2 will need" — Phase 2 owns its own repo additions when its plan is generated.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/repo/query_template.py` | `create_query_template`, `get_query_template`, `get_query_template_by_name_version` |
| `backend/app/db/repo/query_set.py` | `create_query_set`, `get_query_set` |
| `backend/app/db/repo/query.py` | `create_query`, `list_queries_for_set` |
| `backend/app/db/repo/judgment_list.py` | `create_judgment_list`, `get_judgment_list` |
| `backend/app/db/repo/study.py` | `create_study`, `get_study` |
| `backend/app/db/repo/trial.py` | `create_trial`, `list_trials_for_study` |
| `backend/app/db/repo/proposal.py` | `create_proposal`, `get_proposal` |
| `backend/tests/integration/test_study_repos.py` | Integration tests covering each of the 15 repo functions: round-trip seed-and-fetch, FK behavior, list-for-parent ordering. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/__init__.py` | Re-export every new function via `__all__`; existing `cluster_*` + `config_repo_*` re-exports stay |

**Key interfaces** (representative — same shape across all 7 modules)

```python
# backend/app/db/repo/study.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Study


async def create_study(db: AsyncSession, **fields: object) -> Study:
    """Stage a new Study row. Caller commits."""
    study = Study(**fields)
    db.add(study)
    await db.flush()
    await db.refresh(study)
    return study


async def get_study(db: AsyncSession, study_id: str) -> Study | None:
    """Fetch a study by id. No soft-delete in MVP1."""
    stmt = select(Study).where(Study.id == study_id)
    return (await db.execute(stmt)).scalar_one_or_none()
```

The other 6 modules mirror this skeleton — minor variations:
- `query.py:list_queries_for_set` returns `Sequence[Query]` filtered on `query_set_id`.
- `trial.py:list_trials_for_study` returns trials filtered on `study_id`, ordered by `optuna_trial_number ASC`.
- `query_template.py:get_query_template_by_name_version` joins on the UNIQUE `(name, version)` index.
- No `list_clusters`-style cursor pagination — that's Phase 2. Phase 1's listing functions return all rows of an aggregate (volume is bounded by per-study size).

**Tasks**

1. Create the 7 repo modules per the signatures above.
2. Update `backend/app/db/repo/__init__.py`: import + re-export each new function via `__all__`.
3. Add integration test `backend/tests/integration/test_study_repos.py` covering each function: insert + flush + select round-trip. One test case per repo function (15 total). Use the `db_session` fixture from `backend/tests/conftest.py`.

**DoD**

- All 15 repo functions importable from `backend.app.db.repo`.
- `backend/tests/integration/test_study_repos.py` passes (CI service-container Postgres).
- `make lint typecheck` green.

---

### Epic 1 gate (final phase gate)

- [ ] Story 1.1 done — 7 ORM models registered with `Base.metadata`.
- [ ] Story 1.2 done — `0003` migration round-trips; all 5 CHECK constraints enforced (4 status enums (studies, trials, judgment_lists, proposals) + the proposals.pr_state enum).
- [ ] Story 1.3 done — 15 repo functions implemented + integration tests green.
- [ ] `make lint typecheck test-unit test-integration` green.
- [ ] No engine-specific code added outside `backend/app/adapters/` (CLAUDE.md Rule #4 — N/A for Phase 1, but verify nothing leaked).

---

## 3) Testing workstream (required)

### 3.1 Unit tests

- Location: `backend/tests/unit/db/`
- Scope: pure ORM-model registration sanity. No DB.
- Files:
  - [ ] (none) — Story 1.1's DoD relies on `python -c "from backend.app.db.models import ..."` smoke; the registration assertion is implicitly tested by every integration test that uses the models.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: DB-backed migration round-trip + repo CRUD.
- Files:
  - [ ] `test_study_lifecycle_migration.py` — Story 1.2 (round-trip + 5 CHECK constraints + `trials_study_metric` index)
  - [ ] `test_study_repos.py` — Story 1.3 (15 repo function round-trips)

### 3.3 Contract tests

N/A — no HTTP endpoints in Phase 1. Phase 2 adds the contract layer alongside the API endpoints.

### 3.4 E2E tests

N/A — no UI surface; Phase 2 doesn't add UI either (UI is `feat_studies_ui`).

### 3.5 Existing test impact audit

| Test file | Pattern | Action |
|---|---|---|
| `backend/tests/integration/test_migrations.py` | head revision assertion | Update — head moves from `0002` → `0003` (one-line change, in Story 1.2's diff) |

### 3.6 Migration verification

- [ ] `0003_study_lifecycle_schema` includes `downgrade()` (per Story 1.2 body).
- [ ] `alembic upgrade head` from `0002`-state DB succeeds.
- [ ] `alembic downgrade -1 && alembic upgrade head` round-trips.

### 3.7 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration` (CI service-container Postgres)
- [ ] `make lint typecheck`
- [ ] Coverage ≥80% gate (existing; new code volume is small enough that the gate is unaffected)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

**`state.md`** — update on completion (post-merge finalization runs these; unchecked until they actually land):
- [ ] Alembic head — `0002_clusters_config_repos` → `0003_study_lifecycle_schema`
- [ ] Recent changes — add `feat_study_lifecycle Phase 1 (Schema) PR #<N> merged` entry
- [ ] Queued — `feat_study_lifecycle` Phase 1 → archived; `infra_optuna_eval` becomes the next-up (now unblocked by the schema)

**`architecture.md`** — update on completion:
- [ ] "Where the code lives" tree — extend `models/` line: `Cluster, ConfigRepo` → `Cluster, ConfigRepo, QueryTemplate, QuerySet, Query, Study, Trial, JudgmentList, Proposal`
- [ ] Same for `repo/` line

**`CLAUDE.md`** — update on completion:
- [ ] Feature Status table — `feat_study_lifecycle` row → "**Phase 1 (Schema) Complete (PR #<N>, merged YYYY-MM-DD); Phase 2 (Orchestrator + API) deferred**"

### 4.1 Architecture docs

- [ ] `docs/01_architecture/data-model.md` — no change expected; this phase implements the documented shapes.

### 4.2 Product docs

- [ ] `docs/02_product/mvp1-user-stories.md` — no change in Phase 1 (the user stories US-9..12 trace to FR-1..6 which are all Phase 2). Mark them as covered when Phase 2 ships.

### 4.3 Runbooks

N/A — no operator-facing surface in Phase 1.

### 4.4 Security docs

N/A — no new secrets, no new auth surface, no new threats. Existing infra_foundation patterns apply.

### 4.5 Quality docs

N/A — existing test-layer convention applies.

### 4.6 Phase 2 deferred-work tracking

- [x] [`phase2_idea.md`](phase2_idea.md) — written alongside this plan per Step 10 of the impl-plan-gen workflow. Documents the deferred FRs (FR-1..7), the dependency on `infra_optuna_eval`'s `run_trial` shipping, and the future scope so Phase 2 planning can resume cleanly.

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals

- This phase is **purely additive**. No existing modules require refactoring.
- Files modified by Phase 1: `backend/app/db/models/__init__.py` (extend `__all__`), `backend/app/db/repo/__init__.py` (extend `__all__`), `backend/tests/integration/test_migrations.py` (head version assertion). All extensions, not rewrites.

### 5.2 Planned refactor tasks

- [x] (none — purely additive)

### 5.3 Refactor guardrails

- [ ] Lint/typecheck remain green.
- [ ] No expansion of product scope: Phase 2 work stays out of this PR (the impl-execute Step 1 deferred-work mechanism + `phase2_idea.md` enforce this).

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_foundation` shipped | All stories | **Done — PR #4 merged 2026-05-09** | Cannot start (Postgres + Alembic + workers all from foundation) |
| `infra_adapter_elastic` shipped | Story 1.2 (migration) | **Done — PR #16 merged 2026-05-10** | Migration FK targets `clusters.id` — if not shipped, the migration would fail |
| ORM-model precedent (Cluster + ConfigRepo) | Story 1.1 | **Done** | Without precedent, the SQLAlchemy 2.0 typed pattern would need to be re-derived |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FK ordering in `op.create_table()` calls is wrong → migration fails | L | M | Hand-write migration per the documented sequence above (query_templates → query_sets → queries → judgment_lists → studies → trials → proposals); test `upgrade head` from a clean DB before merging |
| `studies.optuna_study_name UNIQUE` collision with future fork features (MVP2) | L | L | Spec §3 docs the convention `optuna_study_name = str(studies.id)`; UUIDv7 collisions are astronomically unlikely |
| `trials_study_metric` index breaks downgrade → can't re-run | L | M | Test `downgrade -1` explicitly drops the index before dropping the `trials` table |
| Self-FK on `query_templates.parent_id` (for forks) creates a circular dependency at `op.create_table` time | L | L | SQLAlchemy / Alembic handle self-FK via post-table-creation `op.create_foreign_key` if needed; or specify `use_alter=True` on the FK |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Migration fails mid-upgrade | DB connection lost during `op.create_table` | Alembic rolls back the transaction; `alembic_version` stays at `0002` | Operator runs `make migrate` again; idempotent |
| Application code imports a model that hasn't been registered | Story 1.1 commit lands but `__init__.py` not updated | `ImportError` at `backend.app.db.models import Foo` | Pre-commit ruff catches the missing export; CI fails fast |
| Repo function called against a non-existent FK target | E.g. `create_trial(study_id="missing")` | DB raises `IntegrityError` (FK violation) | Caller (orchestrator in Phase 2 or test fixture) handles; Phase 1 tests cover this implicitly |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** — Models. Must be first so `Base.metadata` populates.
2. **Story 1.2** — Migration. Must follow models (autogenerate uses metadata as the source of truth, even though we hand-write the body).
3. **Story 1.3** — Repos. Depends on models (imports them).

### Parallelization opportunities

- **None within Phase 1.** The 3 stories are strictly sequential. Within Story 1.1, the 7 model files can be authored in parallel by 7 contributors, but for solo execution they're trivially fast (each file is ~30-60 LOC).

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single-shot. PR contains all 3 stories.
- **Feature flag strategy:** None.
- **Migration/cutover:** Adds 7 tables on top of `0002`. Existing dev installs run `make migrate` to advance `0002 → 0003`. The 7 new tables start empty; Phase 2 (orchestrator + API) and `infra_optuna_eval` (run_trial) populate them.
- **Reconciliation:** N/A — no external systems written to.

## 9) Execution tracker (copy/paste section)

### Current sprint (Phase 1)

- [ ] Story 1.1 — ORM models for the 7 tables
- [ ] Story 1.2 — Alembic migration `0003_study_lifecycle_schema` (round-trip verified)
- [ ] Story 1.3 — Minimal repo functions (~15 functions across 7 files)
- [ ] Epic 1 gate

### Blocked items

- None at draft time.

### Done this sprint

- (track here as stories land)

### Deferred to Phase 2

See [`phase2_idea.md`](phase2_idea.md). FR-1 through FR-7 all live there.

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Files created/modified match story scope.
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added/updated for all touched layers.
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset, with explanation)
  - [ ] `make test-contract` — N/A (no contract surface in Phase 1)
  - [ ] `cd ui && pnpm test` — N/A (no UI in Phase 1)
- [ ] Migration round-trip evidence (Story 1.2 only).
- [ ] Related docs/checklists updated in same PR when behavior/contract changes.

## 11) Plan consistency review (required before execution)

### Review log

GPT-5.5 cross-model review reached convergence in 3 cycles (2026-05-10).
15 total findings raised; 15 accepted + applied. Zero rejections.

#### Cycle 1 — 9 findings (all accepted)

| # | Sev | Pass | Issue → Fix |
|---|---|---|---|
| F1 | M | A | phase2_idea.md AC count was 9, spec has 10; AC-5 misstated. Fix: corrected count + rewrote AC-5 to spec ("after 5 consecutive failures, study transitions to failed"). |
| F2 | L | A | phase2_idea.md said "~10 endpoints"; spec lists 12. Fix: replaced with exact count + enumerated all 12. |
| F3 | M | A | Story 1.2 / 1.3 New/Modified file tables omitted test files. Fix: added `test_study_lifecycle_migration.py` to Story 1.2 New files; added `test_migrations.py` to Story 1.2 Modified files (head bump); added `test_study_repos.py` to Story 1.3 New files. |
| F4 | L | A | Phase 1 didn't inventory deferred test files. Fix: phase2_idea.md gained a "Test files: Phase 1 vs Phase 2 trace" section. |
| F5 | **H** | B | `metadata` is reserved on SQLAlchemy `DeclarativeBase` — a `metadata` mapped column collides at class definition. Fix: `Query` model uses Python attribute `query_metadata` with explicit DB column name `"metadata"`; documented in a Key Interface block. |
| F6 | M | B | Story 1.3 claim "exactly enough for both" was overbroad. Fix: narrowed to "what Phase 1 needs + what `run_trial` consumes; Phase 2 extends". |
| F7 | M | B | Migration test only checked CHECK constraints + table existence. Fix: extended to NOT NULL coverage, FK target + ON DELETE CASCADE introspection, UNIQUE constraints (incl. composite `(name, version)`), index assertions, and live cascade-delete behavior tests. |
| F8 | L | B | §11 ledger cited spec §8.4 for table-status enums but those live in data-model.md. Fix: §11 item 8 split into "studies.status from spec §8.4" vs "trials/judgment_lists/proposals.status + pr_state from data-model.md". |
| F9 | L | B | Example Study snippet used `String` for TEXT columns + `Real` for the typed-class equivalent of PG REAL. Fix: switched to `Text` for all documented-as-TEXT fields; `Float` for REAL. |

#### Cycle 2 — 5 findings (all accepted)

| # | Sev | Pass | Issue → Fix |
|---|---|---|---|
| C2-F1 | M | A | phase2_idea.md only attached `?since=` + `X-Total-Count` to `GET /studies`; spec requires them on all 4 list endpoints. Fix: documented the cross-cutting contract on all 4 list endpoints + flagged 12 contract-test combinations for Phase 2. |
| C2-F2 | M | A | AC-7 still misstated as "StrictUndefined missing-param check"; spec AC-7 is the Jinja2 sandbox security check (`{{ os.system(...) }}` → 400). Fix: AC-7 rewritten verbatim from spec; declared_params↔body cross-check noted as FR-2 unit-test territory. |
| C2-F3 | L | B | Plan said "14 repo functions" but enumeration totals 15 (3+2+2+2+2+2+2). Fix: corrected globally. |
| C2-F4 | L | B | Some summaries said "4 CHECK constraints" while detailed list had 5. Fix: corrected globally; named the 5 explicitly (4 status enums + `proposals.pr_state`). |
| C2-F5 | L | B | §4.0 documentation tasks marked `[x]` but they're future-execution work. Fix: unchecked them; finalization commit will check off as it lands. |

#### Cycle 3 — 1 finding (clean architectural pass; mechanical leftover)

| # | Sev | Pass | Issue → Fix |
|---|---|---|---|
| C3-F1 | minor | B | Cycle-2 `14 → 15` correction missed two stragglers (Story 1.3 task line + phase2_idea.md test trace). Fix: applied directly. |

#### Convergence note

Cycle 3 raised one mechanical typo finding (no architectural drift). The plan-content changes proposed across the 15 findings have all landed; no contested adjudications, no escalations to user. Plan is execution-ready.

### Verification ledger (claims-vs-reality, sampled)

| Claim | Verified by | Status |
|---|---|---|
| Migration dir is `migrations/versions/` | `ls migrations/versions/` | ✓ Verified |
| Current Alembic head is `0002_clusters_config_repos` | Read `migrations/versions/0002_clusters_config_repos.py:25` | ✓ Verified |
| `Base` lives at `backend/app/db/base.py` | Read file | ✓ Verified |
| ORM model precedent uses `Mapped[type]` + `mapped_column(...)` typed style | Read `backend/app/db/models/cluster.py` | ✓ Verified |
| Repo precedent uses `db: AsyncSession` + `db.flush()` (caller commits) | Read `backend/app/db/repo/cluster.py` | ✓ Verified |
| `migrations/env.py` side-effect imports `backend.app.db.models` | Read `migrations/env.py:24` | ✓ Verified — `from backend.app.db import models  # noqa: F401` |
| Existing `__init__.py` exports `Cluster`, `ConfigRepo` via `__all__` | Read `backend/app/db/models/__init__.py` | ✓ Verified |
| `clusters.id` FK target exists | Read `migrations/versions/0002_clusters_config_repos.py:53` | ✓ Verified |
| Spec §3 In-scope lists 7 tables + Phase 2 work | Read `docs/02_product/planned_features/feat_study_lifecycle/feature_spec.md:39-65` | ✓ Verified |
| Spec §3 Phase boundaries declares Phase 1 = Schema, Phase 2 = Orchestrator + API | Read `docs/02_product/planned_features/feat_study_lifecycle/feature_spec.md:85-104` (post-2026-05-10 patch) | ✓ Verified |

### Cross-reference checks

1. **Spec ↔ plan FR coverage.** Phase 1 covers ZERO FRs directly; all 7 FRs are Phase 2. The plan's §1 documents this and points at `phase2_idea.md` for trace continuity.
2. **Spec ↔ plan endpoint count.** N/A — no endpoints in Phase 1.
3. **Spec ↔ plan error code coverage.** N/A — no API in Phase 1.
4. **Test file count** — 2 test files (`test_study_lifecycle_migration.py`, `test_study_repos.py`); both assigned to specific stories' DoD.
5. **Gate arithmetic** — Epic 1 covers 3 stories. Tracker matches.
6. **Open questions resolved** — Spec §19 has zero open questions. ✓
7. **Frontend UI Guidance section** — N/A; this phase has no UI.
8. **Enumerated value contract verification** — Source of truth split (per cycle 1 GPT-5.5 F8 fix):
   - `studies.status` — spec §8.4 (mislabeled `### 7.4` due to a known template drift) lists the 5 values; backend source `backend/app/db/models/study.py` (`StudyStatus` `Literal`).
   - `trials.status`, `judgment_lists.status`, `proposals.status`, `proposals.pr_state` — NOT in spec §8.4. Source of truth is [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) (the SQL `CHECK` constraints in the table DDL). Phase 1 mirrors these into the migration's `CheckConstraint`s; Phase 2's API surface will lift them into `Literal[...]`-typed Pydantic models.
   Phase 1 has no frontend, so cross-product UI verification is deferred to Phase 2's plan.
9. **Audit-event coverage** — N/A in MVP1 per spec §6 ("`audit_log` lands at MVP2"). When MVP2 ships, the table-creation events would be implicit (DDL not user-driven); the per-row mutation events fall under Phase 2's orchestrator.
10. **Admin/ceiling audit** — N/A in MVP1 (no admin model).

---

## 12) Definition of plan done

- [x] Every Phase 1 deliverable mapped to a story.
- [x] Every story includes New files, Modified files, Tasks, and DoD.
- [x] Test layers (unit/integration; contract + e2e N/A) explicitly scoped.
- [x] Documentation updates planned and owned (post-implementation Step 2).
- [x] Lean refactor scope is bounded (purely additive).
- [x] Phase/epic gate is measurable.
- [x] Story-by-Story Verification Gate included.
- [ ] Cross-model review (GPT-5.5) — pending; runs after this draft, before user approval.
- [x] Phase 2 deferred-work tracker (`phase2_idea.md`) authored alongside this plan.
