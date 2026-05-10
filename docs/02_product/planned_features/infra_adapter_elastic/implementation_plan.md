# Implementation Plan — infra_adapter_elastic

**Date:** 2026-05-09
**Status:** Implementation Complete (PR pending — branch `feature/infra-adapter-elastic`, 2026-05-09)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):**
- [CLAUDE.md](../../../../CLAUDE.md) — Absolute Rules #2 (mounted secrets), #4 (engine adapter Protocol), #5 (Alembic round-trip), #6 (`/healthz` unauth), #11 (200ms probe timeout)
- [docs/01_architecture/adapters.md](../../../01_architecture/adapters.md) — `SearchAdapter` Protocol shape + cross-engine vocabulary
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `clusters` and `config_repos` MVP1 shapes
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — error envelope, cursor pagination + `X-Total-Count` + `?since=`
- [docs/01_architecture/deployment.md](../../../01_architecture/deployment.md) — mounted-secrets pattern

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Phase gates are hard stops. (Single-phase plan; one epic-gate at the end of each epic.)
- Fail-loud tests: assert explicit status/shape/error_code values from spec §7.5.
- Match existing project layout. Adapter code lives at `backend/app/adapters/` per [CLAUDE.md "Repository Structure"](../../../../CLAUDE.md) (NOT `backend/adapters/` as the spec body and `adapters.md` text currently say — those docs are corrected by Story 4.2 of this plan).
- Hot-path = `search_batch` only. Other adapter methods can be straightforward request/response.
- Cassette-replay first per [`tech-stack.md` §"Backend"](../../../01_architecture/tech-stack.md). Every ES/OpenSearch interaction has a `pytest-recording` cassette; integration tests run hermetically.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (SearchAdapter Protocol + Pydantic types) | Epic 1 / Story 1.1 | Protocol module + 8 Pydantic types defined |
| FR-2 (ElasticAdapter handles ES + OpenSearch + auth_kinds) | Epic 2 / Stories 2.1, 2.2, 2.7 | Class skeleton + auth resolution + `opensearch_sigv4` reservation |
| FR-3 (search_batch via _msearch) | Epic 2 / Story 2.5 | Hot path; preserves query_id mapping; propagates `X-Opaque-Id` |
| FR-4 (get_schema returns field types + analyzers) | Epic 2 / Story 2.3 | `_mapping` + `_field_caps` |
| FR-5 (Cluster CRUD API) | Epic 1 / Story 1.3 (migration) + Epic 3 / Stories 3.1, 3.2 | Tables + repo + service + router |
| FR-6 (run_query endpoint for debugging) | Epic 3 / Story 3.4 | top_k≤1000, time-budget timeout, returns hits |
| FR-7 (Seed command for local convenience) | Epic 4 / Story 4.1 | `make seed-clusters` → `python -m backend.app.scripts.seed_clusters` (idempotent) |

**Spec §2 incidental requirement** (no FR backing it): `/healthz` gains `subsystems.elasticsearch_clusters` aggregate field. Tracked as Story 3.5 with explicit spec-source citation; flagged in §11 review log as a spec gap (no FR — should either get FR-8 added to the spec or be dropped from §2). Plan implements per §2 text and lets the cross-model review or user resolve the gap.

**Phase boundaries.** Single-phase per spec §3 ("ES + OpenSearch ship together"). No deferred phase tracking artifacts needed.

## 2) Delivery structure

**Epic → Story → Tasks → DoD.** Five epics:

1. **Epic 1 — Protocol + schema + repo** (define the boundary; create the tables; expose CRUD plumbing without behavior).
2. **Epic 2 — ElasticAdapter implementation** (the actual engine adapter; cassette-backed).
3. **Epic 3 — API surface** (routers, services, `/healthz` extension).
4. **Epic 4 — Seed command + docs** (operator convenience + documentation).
5. **Epic 5 — Test coverage audit + finalization** (verify all spec test files exist + assigned, doc patches landed).

### Story-level detail requirements

Each story includes Outcome, New files, Modified files, Endpoints (when API-facing), Key interfaces, Pydantic schemas (when API-facing), Tasks, and DoD with test-layer references.

### Conventions (project-specific)

- All ORM models use `Base` from [`backend/app/db/base.py`](../../../../backend/app/db/base.py); `id` is `Mapped[str]` (UUIDv7 hex). Timestamps `TIMESTAMPTZ` via `DateTime(timezone=True)`. snake_case columns.
- Repo functions take `db: AsyncSession` as the first arg, use `db.flush()` (caller commits), and live in `backend/app/db/repo/<aggregate>.py`. Export every new function via `backend/app/db/repo/__init__.py` `__all__`.
- Services are async, accept `db: AsyncSession` + typed args, live in `backend/app/services/<feature>.py`. Compose repos + domain + adapter calls.
- Domain logic (pure: parameter validation, render, error-mapping helpers) lives in `backend/app/domain/<topic>/`.
- Adapters live in `backend/app/adapters/` (NOT `backend/adapters/` — see §0 principle and Story 4.2 doc patch).
- Routers return typed Pydantic response models. Errors use `HTTPException(status_code=…, detail={"error_code": …, "message": …, "retryable": …})` so [`backend/app/api/errors.py`](../../../../backend/app/api/errors.py) `http_exception_handler` passes the structured detail through.
- Settings via `get_settings()` (cached); secrets via `*_FILE` env vars resolved by `@cached_property` accessors. The `cluster_credentials_file` accessor is already defined at [`backend/app/core/settings.py:95`](../../../../backend/app/core/settings.py).
- LLM/OpenAI: not touched by this feature.
- Cursor pagination + `X-Total-Count` + `?since=` mandatory for `GET /api/v1/clusters` per [`api-conventions.md` §"Pagination"](../../../01_architecture/api-conventions.md).

### AI Agent Execution Protocol

0. Read [`architecture.md`](../../../../architecture.md) and [`state.md`](../../../../state.md) before starting Story 1.1.
1. Read scope: verify story outcome + endpoints + interfaces + DoD against the spec.
2. Implement backend in dependency order: protocol → models → migration → repo → domain → adapter → service → router.
3. Run touched test layers (`make test-unit`, `make test-integration -m integration`, `make test-contract`).
4. Update docs in same PR when behavior/contract changes.
5. Verify migration round-trip after Story 1.3 (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`).
6. Attach evidence in PR description: commands run, pass/fail counts, files changed.
7. After the final story, update `state.md` (Alembic head moves from `0001` to `0002`; recent changes; queued items shift) and `architecture.md` (new `backend/app/adapters/` layer).

---

## Epic 1 — Protocol + schema + repo

### Story 1.1 — `SearchAdapter` Protocol module + Pydantic types

**Outcome:** `from backend.app.adapters.protocol import SearchAdapter, HealthStatus, TargetInfo, Schema, FieldSpec, NativeQuery, ScoredHit, ExplainTree, QueryTemplate, ParamValue` works. Future adapter classes implement `SearchAdapter`; `isinstance(adapter, SearchAdapter)` returns True at runtime via `@runtime_checkable`.

**New files**

| File | Purpose |
|---|---|
| `backend/app/adapters/__init__.py` | Empty package marker |
| `backend/app/adapters/protocol.py` | `SearchAdapter` Protocol + 8 Pydantic types per FR-1 + spec §7.4 |

**Modified files**

| File | Change |
|---|---|
| (none) | Story 1.1 is purely additive |

**Key interfaces**

```python
# backend/app/adapters/protocol.py
from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

EngineType = Literal["elasticsearch", "opensearch"]
# Wire values for cluster registration. Source-of-truth — DB CHECK in 0002 migration.

ParamValue = bool | int | float | str | list[str]


class FieldSpec(BaseModel):
    """One field returned by `get_schema`."""
    name: str
    type: str           # "text", "keyword", "float", "boolean", "date", ...
    analyzer: str | None = None
    doc_count: int | None = None


class Schema(BaseModel):
    name: str           # target index/collection name
    fields: list[FieldSpec]


class HealthStatus(BaseModel):
    status: Literal["green", "yellow", "red", "unreachable"]
    version: str | None = None       # engine version string, populated for reachable clusters
    checked_at: str                  # ISO-8601 UTC timestamp
    error: str | None = None         # human-readable detail when status == "unreachable"


class TargetInfo(BaseModel):
    name: str
    doc_count: int | None = None


class NativeQuery(BaseModel):
    """Engine-native query body. For ES/OpenSearch this is the Query DSL JSON."""
    query_id: str       # caller-supplied id; preserved through search_batch response mapping
    body: dict          # the engine-native request body (e.g. {"query": {"match": {…}}, "size": …})


class ScoredHit(BaseModel):
    doc_id: str
    score: float
    source: dict | None = None


class ExplainTree(BaseModel):
    doc_id: str
    matched: bool
    value: float
    description: str
    details: list["ExplainTree"] = Field(default_factory=list)


class QueryTemplate(BaseModel):
    """Type only — body + declared_params. Templates are rendered by ElasticAdapter.render.
    The query_templates DB table is owned by feat_study_lifecycle (per data-model.md);
    this Pydantic model lets the adapter receive a template at call time without
    coupling to that table.
    """
    name: str
    engine_type: EngineType
    body: str                                # Jinja2 source
    declared_params: dict[str, str]          # {param_name: "type/range hint"}


@runtime_checkable
class SearchAdapter(Protocol):
    """Engine adapter Protocol.

    All I/O methods are async — the only implementation in MVP1 (`ElasticAdapter`)
    talks to the engine over HTTP via httpx async; future Fusion + Solr adapters
    will likewise use async clients. Pure-CPU methods (`render`, `list_query_parsers`)
    remain synchronous.

    NOTE: `docs/01_architecture/adapters.md` currently shows synchronous signatures
    — that was an aspirational sketch. Story 4.2 patches `adapters.md` to match
    this async contract.
    """

    engine_type: EngineType

    async def health_check(self, *, request_id: str | None = None) -> HealthStatus: ...
    async def list_targets(self, *, request_id: str | None = None) -> list[TargetInfo]: ...
    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema: ...
    def list_query_parsers(self) -> list[str]: ...

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery: ...

    async def search_batch(
        self,
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        *,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]: ...
    # When `strict_errors=True`, item-level engine errors (e.g. parsing_exception)
    # raise `InvalidQueryDSLError` instead of yielding empty hits. The hot path
    # (Optuna trial runner, future) uses the default `False` for graceful
    # degradation; the run_query API endpoint passes `True` for explicit errors.
    # `timeout` overrides the adapter's default httpx client timeout; the
    # run_query endpoint passes the operator-supplied budget (5s default,
    # 30s max per spec FR-6) so it actually fires.

    async def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> ExplainTree: ...
```

**Tasks**
1. Create `backend/app/adapters/__init__.py` and `backend/app/adapters/protocol.py` with the types and Protocol shown above.
2. Wire the package — no `main.py` change needed (Protocol is imported on demand by Stories 2.1+).
3. Add unit test `backend/tests/unit/adapters/test_protocol.py` that uses an async stub class to assert: (a) `isinstance(stub, SearchAdapter)` returns True via `@runtime_checkable`; (b) `inspect.iscoroutinefunction(stub.health_check)` for each async method (locks in the async contract); (c) every Pydantic model in the module instantiates with valid sample data and rejects invalid data (e.g., `HealthStatus(status="purple")` raises `ValidationError`).

**Definition of Done (DoD)**
- `backend/app/adapters/protocol.py` exports `SearchAdapter`, `HealthStatus`, `TargetInfo`, `Schema`, `FieldSpec`, `NativeQuery`, `ScoredHit`, `ExplainTree`, `QueryTemplate`, `ParamValue`, `EngineType`. (FR-1)
- `backend/tests/unit/adapters/test_protocol.py` passes — `isinstance(stub, SearchAdapter)` verified; async methods asserted via `inspect.iscoroutinefunction`; every Pydantic model has at least one valid + one invalid case.
- `make lint typecheck test-unit` green.

---

### Story 1.2 — ORM models for `clusters` and `config_repos`

**Outcome:** SQLAlchemy 2.0 typed models registered against `Base.metadata` so Alembic `--autogenerate` (Story 1.3) can pick them up. No DB writes yet.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/models/__init__.py` | Re-export `Cluster`, `ConfigRepo` via `__all__` |
| `backend/app/db/models/cluster.py` | `Cluster` ORM model — full MVP1 shape per [`data-model.md` §"`clusters`"](../../../01_architecture/data-model.md) |
| `backend/app/db/models/config_repo.py` | `ConfigRepo` ORM model — full MVP1 shape per [`data-model.md` §"`config_repos`"](../../../01_architecture/data-model.md) |

**Modified files**

| File | Change |
|---|---|
| (none) | `backend/app/db/models/` directory does not yet exist (per [`backend/app/db/base.py`](../../../../backend/app/db/base.py) docstring). This story creates it. |

**Key interfaces**

```python
# backend/app/db/models/cluster.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Cluster(Base):
    __tablename__ = "clusters"
    __table_args__ = (
        CheckConstraint(
            "engine_type IN ('elasticsearch', 'opensearch')",
            name="clusters_engine_type_check",
        ),
        CheckConstraint(
            "environment IN ('prod', 'staging', 'dev')",
            name="clusters_environment_check",
        ),
        CheckConstraint(
            "auth_kind IN ('es_apikey', 'es_basic', 'opensearch_basic', 'opensearch_sigv4')",
            name="clusters_auth_kind_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUIDv7 hex
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    engine_type: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    auth_kind: Mapped[str] = mapped_column(String, nullable=False)
    credentials_ref: Mapped[str] = mapped_column(String, nullable=False)
    config_repo_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("config_repos.id"), nullable=True
    )
    config_path: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

```python
# backend/app/db/models/config_repo.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class ConfigRepo(Base):
    __tablename__ = "config_repos"
    __table_args__ = (
        CheckConstraint("provider IN ('github')", name="config_repos_provider_check"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    repo_url: Mapped[str] = mapped_column(String, nullable=False)
    default_branch: Mapped[str] = mapped_column(String, nullable=False, server_default="main")
    pr_base_branch: Mapped[str] = mapped_column(String, nullable=False, server_default="main")
    auth_ref: Mapped[str] = mapped_column(String, nullable=False)
    webhook_secret_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    webhook_registration_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

**Tasks**
1. Create `backend/app/db/models/` directory with `__init__.py` exporting `Cluster` and `ConfigRepo` via `__all__`.
2. Create `cluster.py` and `config_repo.py` per the signatures above.
3. Update [`migrations/env.py`](../../../../migrations/env.py) is **NOT** required — the file already imports `Base` and uses `Base.metadata` (line 19–31). The new models simply need to be importable so they register with `Base.metadata` before `--autogenerate` runs. Story 1.3 imports them via `from backend.app.db import models  # noqa: F401`.

**DoD**
- `from backend.app.db.models import Cluster, ConfigRepo` succeeds.
- `Base.metadata.tables` contains `clusters` and `config_repos` after import.
- `make lint typecheck` green. (No tests for the model module itself — Story 1.3's migration round-trip exercises the schema; Story 1.4's repo tests exercise the model via the DB.)

---

### Story 1.3 — Alembic migration `0002_clusters_config_repos`

**Outcome:** Running `alembic upgrade head` against a fresh DB creates the `clusters` and `config_repos` tables in their full MVP1 shape per [`data-model.md`](../../../01_architecture/data-model.md). `alembic downgrade -1` cleanly removes both. `alembic_version` advances from `0001` to `0002`.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0002_clusters_config_repos.py` | Migration creating both tables with all CHECK constraints, FKs, indexes |

The migrations directory is `migrations/versions/` (verified — see [`migrations/versions/0001_baseline.py`](../../../../migrations/versions/0001_baseline.py)). Current head is `0001`; new revision id `0002`.

**Modified files**

| File | Change |
|---|---|
| `migrations/env.py` | Add `from backend.app.db import models  # noqa: F401` so model registry loads before autogenerate. (Existing line 20 imports `Base`; the new line forces side-effect imports of the model modules.) |

**Migration body — exact sequence**

```python
"""clusters_config_repos

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-09 …
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_repos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("repo_url", sa.String(), nullable=False),
        sa.Column("default_branch", sa.String(), nullable=False, server_default="main"),
        sa.Column("pr_base_branch", sa.String(), nullable=False, server_default="main"),
        sa.Column("auth_ref", sa.String(), nullable=False),
        sa.Column("webhook_secret_ref", sa.String(), nullable=True),
        sa.Column("webhook_registration_error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("provider IN ('github')", name="config_repos_provider_check"),
    )
    op.create_table(
        "clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("engine_type", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("auth_kind", sa.String(), nullable=False),
        sa.Column("credentials_ref", sa.String(), nullable=False),
        sa.Column(
            "config_repo_id",
            sa.String(36),
            sa.ForeignKey("config_repos.id"),
            nullable=True,
        ),
        sa.Column("config_path", sa.String(), nullable=True),
        sa.Column("engine_config", JSONB(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "engine_type IN ('elasticsearch', 'opensearch')",
            name="clusters_engine_type_check",
        ),
        sa.CheckConstraint(
            "environment IN ('prod', 'staging', 'dev')",
            name="clusters_environment_check",
        ),
        sa.CheckConstraint(
            "auth_kind IN ('es_apikey', 'es_basic', 'opensearch_basic', 'opensearch_sigv4')",
            name="clusters_auth_kind_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("clusters")
    op.drop_table("config_repos")
```

**Tasks**
1. Add `from backend.app.db import models  # noqa: F401` to `migrations/env.py` after the `Base` import.
2. Run `make migrate-create name=clusters_config_repos` (which calls `alembic revision --autogenerate --rev-id 0002`) and replace the generated body with the deterministic upgrade/downgrade above. (Autogenerate is a starting point; we hand-write to control constraint order and naming.)
3. Verify round-trip locally: `make up` → `make migrate` → `docker compose exec -T api alembic downgrade -1 && docker compose exec -T api alembic upgrade head`. Assert no errors and `\dt` shows both tables.
4. Add integration test `backend/tests/integration/test_clusters_migration.py` that asserts: tables exist after upgrade; tables removed after downgrade; CHECK constraints reject `auth_kind='solr_basic'` (foreign value) but accept all four allowed values.

**DoD**
- `alembic upgrade head` from a clean DB results in a `0002` `alembic_version` row + both tables. (FR-5 prereq)
- `alembic downgrade -1 && alembic upgrade head` round-trips cleanly. (CLAUDE.md Absolute Rule #5)
- `backend/tests/integration/test_clusters_migration.py` passes. (test-integration layer)
- `make migrate` continues to work end-to-end via the existing Makefile target.

---

### Story 1.4 — Repo functions for `clusters` + `config_repos`

**Outcome:** Service code (Story 3.1) can create / list / fetch / soft-delete clusters and create / fetch config_repos via async SQLAlchemy. `db.flush()` only — caller commits.

**New files**

| File | Purpose |
|---|---|
| `backend/app/db/repo/__init__.py` | `__all__` exports for the repo functions |
| `backend/app/db/repo/cluster.py` | `create_cluster`, `list_clusters`, `get_cluster`, `get_active_cluster_by_name`, `get_any_cluster_by_name`, `revive_cluster`, `soft_delete_cluster`, `count_clusters` |
| `backend/app/db/repo/config_repo.py` | `create_config_repo`, `get_config_repo`, `get_config_repo_by_name` |

**Modified files**

| File | Change |
|---|---|
| (none) | `backend/app/db/repo/` does not exist yet (per [`backend/app/db/base.py`](../../../../backend/app/db/base.py) module docstring). This story creates it. |

**Key interfaces**

```python
# backend/app/db/repo/cluster.py
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Cluster


async def create_cluster(db: AsyncSession, **fields: object) -> Cluster:
    """Stage a new Cluster row. Caller commits."""
    cluster = Cluster(**fields)
    db.add(cluster)
    await db.flush()
    await db.refresh(cluster)
    return cluster


async def list_clusters(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
) -> Sequence[Cluster]:
    """Cursor-paginated list per api-conventions §"Pagination". Excludes soft-deleted.

    Cursor predicate uses an explicit `(a < b) OR (a == b AND id < cursor_id)`
    decomposition rather than `(col, col) < (val, val)` because SQLAlchemy 2.0
    treats Python tuple comparison on Column expressions as a row-value compare
    only when wrapped in `tuple_(...)`. Hand-rolling the predicate is also
    portable across PostgreSQL/SQLite (test) and clearer in EXPLAIN output.
    """
    stmt = select(Cluster).where(Cluster.deleted_at.is_(None))
    if since is not None:
        stmt = stmt.where(Cluster.created_at >= since)
    if cursor is not None:
        cursor_at, cursor_id = cursor
        stmt = stmt.where(
            or_(
                Cluster.created_at < cursor_at,
                and_(Cluster.created_at == cursor_at, Cluster.id < cursor_id),
            )
        )
    stmt = stmt.order_by(Cluster.created_at.desc(), Cluster.id.desc()).limit(min(limit, 200))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_clusters(db: AsyncSession, *, since: datetime | None = None) -> int:
    """Count for X-Total-Count header. Excludes soft-deleted."""
    stmt = select(func.count(Cluster.id)).where(Cluster.deleted_at.is_(None))
    if since is not None:
        stmt = stmt.where(Cluster.created_at >= since)
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def get_cluster(db: AsyncSession, cluster_id: str) -> Cluster | None:
    """Fetch a non-soft-deleted cluster by id; returns None for not-found OR soft-deleted."""
    stmt = select(Cluster).where(Cluster.id == cluster_id, Cluster.deleted_at.is_(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_active_cluster_by_name(db: AsyncSession, name: str) -> Cluster | None:
    """Fetch the active (non-deleted) cluster by unique name."""
    stmt = select(Cluster).where(Cluster.name == name, Cluster.deleted_at.is_(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_any_cluster_by_name(db: AsyncSession, name: str) -> Cluster | None:
    """Fetch a cluster by name regardless of `deleted_at`.

    Used by the registration service to detect a soft-deleted same-named row
    that should be revived rather than re-inserted (the underlying
    `clusters.name UNIQUE` constraint applies to all rows; INSERT would
    otherwise hit a unique-violation).
    """
    stmt = select(Cluster).where(Cluster.name == name)
    return (await db.execute(stmt)).scalar_one_or_none()


async def revive_cluster(db: AsyncSession, cluster: Cluster, **updates: object) -> Cluster:
    """Clear `deleted_at` and apply field updates to a soft-deleted row.

    Used by `register_cluster` when an operator re-registers a previously
    soft-deleted name (per spec §10 Data retention).
    """
    cluster.deleted_at = None
    for key, value in updates.items():
        setattr(cluster, key, value)
    await db.flush()
    await db.refresh(cluster)
    return cluster


async def soft_delete_cluster(db: AsyncSession, cluster_id: str) -> Cluster | None:
    """Set deleted_at on a cluster; return the row or None if not found / already deleted."""
    cluster = await get_cluster(db, cluster_id)
    if cluster is None:
        return None
    cluster.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    return cluster
```

```python
# backend/app/db/repo/config_repo.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import ConfigRepo


async def create_config_repo(db: AsyncSession, **fields: object) -> ConfigRepo:
    repo = ConfigRepo(**fields)
    db.add(repo)
    await db.flush()
    await db.refresh(repo)
    return repo


async def get_config_repo(db: AsyncSession, repo_id: str) -> ConfigRepo | None:
    return (
        await db.execute(select(ConfigRepo).where(ConfigRepo.id == repo_id))
    ).scalar_one_or_none()


async def get_config_repo_by_name(db: AsyncSession, name: str) -> ConfigRepo | None:
    return (
        await db.execute(select(ConfigRepo).where(ConfigRepo.name == name))
    ).scalar_one_or_none()
```

**Tasks**
1. Create the repo modules per the signatures above.
2. Export each function via `backend/app/db/repo/__init__.py` `__all__`.
3. Add integration test `backend/tests/integration/test_cluster_repo.py` covering: insert + flush + select roundtrip; cursor pagination ordering (page 2 excludes page 1 rows); soft-delete excludes from list and `get_cluster`; `get_active_cluster_by_name` returns None for a soft-deleted row; `get_any_cluster_by_name` returns the soft-deleted row; `revive_cluster` clears `deleted_at` + updates fields and the row appears again in `list_clusters`.

**DoD**
- All repo functions importable from `backend.app.db.repo`.
- `backend/tests/integration/test_cluster_repo.py` passes — tested with the CI service-container Postgres.
- Soft-delete semantics match spec §12 AC-8.
- `make lint typecheck` green.

---

### Epic 1 gate (hard stop before Epic 2)

- [ ] Story 1.1 done — Protocol module + 8 Pydantic types + isinstance test passes.
- [ ] Story 1.2 done — ORM models import cleanly; `Base.metadata` knows about `clusters` and `config_repos`.
- [ ] Story 1.3 done — `0002` migration round-trips; CHECK constraints enforce the four `auth_kind` values.
- [ ] Story 1.4 done — repo functions implemented + integration tests green.
- [ ] `make lint typecheck test-unit test-integration` green.

---

## Epic 2 — ElasticAdapter implementation

### Story 2.1 — `ElasticAdapter` class skeleton + version detection

**Outcome:** `ElasticAdapter(cluster, credentials)` constructs a usable adapter instance, performs version detection on first call, raises `NotImplementedError` for `opensearch_sigv4`, and exposes a single shared `httpx.AsyncClient` per adapter instance.

**New files**

| File | Purpose |
|---|---|
| `backend/app/adapters/elastic.py` | `ElasticAdapter` class; constructor, `_request`, version detection. Stub bodies for the six Protocol methods (filled by Stories 2.2–2.6). |
| `backend/app/adapters/credentials.py` | `resolve_credentials(auth_kind, credentials_ref) -> dict` — reads from the YAML body resolved by `Settings.cluster_credentials_yaml`. Raises `CredentialsMissing` (custom exception) if the ref is absent. |
| `backend/app/adapters/errors.py` | Domain exceptions: `ClusterUnreachableError` defined here so `_request` can import it. Story 2.3 extends with `TargetNotFoundError`; Story 2.5 extends with `InvalidQueryDSLError` + `QueryTimeoutError`. Single import path for the adapter, services, and routers. |

**Key interfaces**

```python
# backend/app/adapters/elastic.py
from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

import httpx
import yaml

from backend.app.adapters.credentials import resolve_credentials
from backend.app.adapters.protocol import (
    EngineType,
    ExplainTree,
    HealthStatus,
    NativeQuery,
    ParamValue,
    QueryTemplate,
    Schema,
    ScoredHit,
    TargetInfo,
)


SUPPORTED_ENGINE_TYPES: frozenset[str] = frozenset({"elasticsearch", "opensearch"})
SUPPORTED_ENVIRONMENTS: frozenset[str] = frozenset({"prod", "staging", "dev"})
SUPPORTED_AUTH_KINDS: frozenset[str] = frozenset(
    {"es_apikey", "es_basic", "opensearch_basic"}
)
RESERVED_AUTH_KINDS: frozenset[str] = frozenset({"opensearch_sigv4"})


class ElasticAdapter:
    """Single adapter for ES (8.11+/9.x) and OpenSearch (2.x). engine_type pivots."""

    engine_type: EngineType

    def __init__(
        self,
        *,
        cluster_id: str,
        engine_type: EngineType,
        base_url: str,
        auth_kind: str,
        credentials_ref: str,
        engine_config: dict | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if auth_kind in RESERVED_AUTH_KINDS:
            raise NotImplementedError(
                f"{auth_kind} is reserved but not implemented in MVP1"
            )
        if auth_kind not in SUPPORTED_AUTH_KINDS:
            raise ValueError(f"unknown auth_kind: {auth_kind}")
        self.cluster_id = cluster_id
        self.engine_type = engine_type
        self.base_url = base_url.rstrip("/")
        self.auth_kind = auth_kind
        self.credentials_ref = credentials_ref
        self.engine_config = engine_config or {}
        self._auth_headers = self._build_auth_headers()
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0))
        self._version: str | None = None  # populated on first health_check / request

    def _build_auth_headers(self) -> dict[str, str]:
        creds = resolve_credentials(self.auth_kind, self.credentials_ref)
        if self.auth_kind == "es_apikey":
            return {"Authorization": f"ApiKey {creds['api_key']}"}
        if self.auth_kind in ("es_basic", "opensearch_basic"):
            token = base64.b64encode(
                f"{creds['username']}:{creds['password']}".encode()
            ).decode()
            return {"Authorization": f"Basic {token}"}
        raise AssertionError("unreachable: auth_kind validated in __init__")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        content: bytes | str | None = None,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
        translate_errors: bool = True,
    ) -> httpx.Response:
        """Issue a request with one retry on connection-class failures.

        Spec §13 Reliability: "Adapter handles cluster restart cleanly —
        connection pool drops dead connections and retries once on
        ConnectionError. After a single retry, errors propagate."

        When `translate_errors=True` (default), connection-class failures after
        the retry surface as `ClusterUnreachableError` and 401/403/5xx HTTP
        responses surface as `ClusterUnreachableError`. Set `translate_errors=False`
        in `health_check` so that callsite can keep its own status-code-aware
        mapping (it returns `HealthStatus(status="unreachable", ...)` rather
        than raising).
        """
        from backend.app.adapters.errors import ClusterUnreachableError

        headers = dict(self._auth_headers)
        if extra_headers:
            headers.update(extra_headers)
        if request_id:
            headers["X-Opaque-Id"] = request_id

        kwargs: dict[str, Any] = dict(
            method=method,
            url=f"{self.base_url}{path}",
            headers=headers,
            params=params,
        )
        if json is not None:
            kwargs["json"] = json
        if content is not None:
            kwargs["content"] = content
        if timeout is not None:
            kwargs["timeout"] = timeout

        connection_excs = (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
        )

        for attempt in (1, 2):
            try:
                resp = await self._client.request(**kwargs)
                break
            except connection_excs as exc:
                if attempt == 2:
                    if translate_errors:
                        raise ClusterUnreachableError(str(exc)) from exc
                    raise
                # First attempt: retry once per spec §13.
                continue

        if translate_errors and resp.status_code in (401, 403):
            raise ClusterUnreachableError(
                f"Authentication failed (HTTP {resp.status_code}) for {method} {path}"
            )
        if translate_errors and resp.status_code >= 500:
            raise ClusterUnreachableError(
                f"HTTP {resp.status_code} from {method} {path}"
            )
        return resp

    async def aclose(self) -> None:
        await self._client.aclose()
```

```python
# backend/app/adapters/credentials.py
from __future__ import annotations

import yaml

from backend.app.core.settings import get_settings


class CredentialsMissing(LookupError):
    """No credentials YAML mounted, or `credentials_ref` not present in mounted YAML."""


def resolve_credentials(auth_kind: str, credentials_ref: str) -> dict:
    """Resolve a `credentials_ref` to its credential dict.

    The mounted YAML is a top-level mapping {ref: {…}}; the `ref` is the key.
    Per `infra_foundation` Settings.cluster_credentials_yaml.
    """
    body = get_settings().cluster_credentials_yaml
    if body is None:
        raise CredentialsMissing(
            f"cluster_credentials_yaml is not mounted; {credentials_ref!r} cannot be resolved"
        )
    parsed = yaml.safe_load(body) or {}
    if credentials_ref not in parsed:
        raise CredentialsMissing(
            f"credentials_ref {credentials_ref!r} not found in mounted YAML"
        )
    return parsed[credentials_ref]
```

**Modified files**

| File | Change |
|---|---|
| `pyproject.toml` | Add `pyyaml>=6.0` to runtime dependencies (used by `credentials.py`). |

**Tasks**
1. Implement `ElasticAdapter.__init__` + `_build_auth_headers` + `_request` + `aclose`.
2. Implement `resolve_credentials` and `CredentialsMissing`.
3. Add unit test `backend/tests/unit/adapters/test_auth_kinds.py` covering: `opensearch_sigv4` raises `NotImplementedError` (FR-2 + AC-7); each supported `auth_kind` constructs successfully with a stubbed `cluster_credentials_yaml`; unknown `auth_kind` raises `ValueError`. (Spec §14 unit test.)
4. Add unit test `backend/tests/unit/adapters/test_credentials.py` covering: missing YAML body raises `CredentialsMissing`; missing ref raises `CredentialsMissing`; valid YAML returns the right dict.
5. Add unit test `backend/tests/unit/adapters/test_request_retry.py` (cycle 2 F4) using `httpx.MockTransport` covering: first attempt raises `httpx.ConnectError` then second succeeds → `_request` returns the success response (one retry per spec §13); two consecutive `ConnectError`s → `ClusterUnreachableError` raised when `translate_errors=True`, raw `httpx.ConnectError` re-raised when `translate_errors=False`; 5xx response with `translate_errors=True` → `ClusterUnreachableError`; 401 with `translate_errors=True` → `ClusterUnreachableError`; 200 path emits exactly one HTTP call (no spurious retry on success).
6. Stub the six Protocol methods to `raise NotImplementedError("Story 2.X")` so the type-checker is happy until later stories fill them.

**DoD**
- `from backend.app.adapters.elastic import ElasticAdapter` succeeds. `isinstance(stub_adapter, SearchAdapter)` returns True (verified via `test_protocol.py` runtime check, extended to also instantiate `ElasticAdapter` once Stories 2.2–2.6 land).
- `pyproject.toml` adds `pyyaml`.
- `make test-unit` green; new tests cover both `auth_kinds` and `credentials`.

---

### Story 2.2 — `health_check()` + 30s Redis-backed cache

**Outcome:** `await adapter.health_check()` returns a `HealthStatus`. Result cached in Redis at `cluster:health:{cluster_id}` with 30s TTL per spec Decision Log 2026-05-09.

**New files**

| File | Purpose |
|---|---|
| `backend/app/adapters/health_cache.py` | `read_cached_health(redis, cluster_id) -> HealthStatus \| None`; `write_cached_health(redis, cluster_id, status)` (TTL 30s) |

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/elastic.py` | Implement `health_check`. Calls `GET /_cluster/health` (works on both ES + OpenSearch); on success stores `version.number` from `GET /` (cluster info root). Maps to `HealthStatus`. |

**Key interfaces**

```python
# backend/app/adapters/elastic.py (continued)
async def health_check(self, *, request_id: str | None = None) -> HealthStatus:
    """Probe the cluster. Engine version cached on the adapter instance.

    All connection / version-mismatch failures are converted to
    `HealthStatus(status='unreachable', error=...)` — never raised. The service
    layer relies on this to translate to `CLUSTER_UNREACHABLE` (FR-5 / AC-6).
    """
    now = datetime.now(timezone.utc).isoformat()
    try:
        # translate_errors=False: this method owns its own status mapping
        # (returns HealthStatus rather than raising), and the spec §13 retry
        # is still applied inside _request before the call returns.
        resp = await self._request(
            "GET", "/_cluster/health", request_id=request_id, translate_errors=False
        )
        if resp.status_code >= 500:
            return HealthStatus(
                status="unreachable",
                checked_at=now,
                error=f"HTTP {resp.status_code} from /_cluster/health",
            )
        if resp.status_code in (401, 403):
            return HealthStatus(
                status="unreachable",
                checked_at=now,
                error=f"Authentication failed (HTTP {resp.status_code})",
            )
        # 2xx — parse cluster status
        body = resp.json()
        cluster_status = body.get("status", "red")  # green | yellow | red
        if self._version is None:
            info = await self._request("GET", "/", request_id=request_id, translate_errors=False)
            self._version = info.json().get("version", {}).get("number")
            self._enforce_min_version()  # may raise ValueError — caught below
        return HealthStatus(
            status=cluster_status,
            version=self._version,
            checked_at=now,
        )
    except ValueError as exc:
        # Engine version below minimum — surfaced as unreachable per spec §11.
        return HealthStatus(
            status="unreachable",
            version=self._version,
            checked_at=now,
            error=str(exc),
        )
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectTimeout) as exc:
        return HealthStatus(status="unreachable", checked_at=now, error=str(exc))


def _enforce_min_version(self) -> None:
    """Fail-loud if engine version < minimum supported (§11 edge flow).
    ES 8.11 minimum; OpenSearch 2.0 minimum. Raises ValueError caught by health_check.
    """
    if self._version is None:
        return
    parts = [int(p) for p in self._version.split(".")[:2] if p.isdigit()]
    if self.engine_type == "elasticsearch" and parts < [8, 11]:
        raise ValueError(
            f"engine version {self._version} is below minimum 8.11"
        )
    if self.engine_type == "opensearch" and parts < [2, 0]:
        raise ValueError(
            f"engine version {self._version} is below minimum 2.0"
        )
```

```python
# backend/app/adapters/health_cache.py
from __future__ import annotations

import json

from redis.asyncio import Redis

from backend.app.adapters.protocol import HealthStatus

_TTL_SECONDS = 30


def _key(cluster_id: str) -> str:
    return f"cluster:health:{cluster_id}"


async def read_cached_health(redis: Redis, cluster_id: str) -> HealthStatus | None:
    raw = await redis.get(_key(cluster_id))
    if raw is None:
        return None
    try:
        return HealthStatus.model_validate_json(raw)
    except Exception:  # noqa: BLE001 — corrupt cache treated as miss
        return None


async def write_cached_health(redis: Redis, cluster_id: str, status: HealthStatus) -> None:
    await redis.set(_key(cluster_id), status.model_dump_json(), ex=_TTL_SECONDS)
```

**Tasks**
1. Implement `health_check()` and `_enforce_min_version` per the signatures above. Critically, `health_check()` MUST swallow `ValueError` from `_enforce_min_version` and return `HealthStatus(status="unreachable", error=…)` — never let it escape (cycle 1 F3 fix).
2. Implement `health_cache.py`.
3. Add unit test `backend/tests/unit/adapters/test_health_cache.py` (no Redis; uses `fakeredis`-style stub or `pytest-asyncio` `monkeypatch`) covering: cache miss returns None; write-then-read roundtrip succeeds; corrupted JSON returns None.
4. Add integration test `backend/tests/integration/test_elastic_health.py` (cassette-replayed `_cluster/health` + `/`) covering: green ES 9.4 cluster → `HealthStatus(status="green", version="9.4.0", …)`; OpenSearch 2.18 → similar; ES 8.10 (recorded synthetic cassette) → `unreachable` with version-too-low message AND no exception escapes (asserts via `pytest.raises` is NOT used — assertion is on the returned status).

**DoD**
- `await adapter.health_check()` returns valid `HealthStatus` against ES 9 and OpenSearch 2.18 cassettes.
- 30s TTL caching helper exercised by unit test (no integration test needed for the cache itself — it's pure Redis + JSON).
- `make test-unit test-integration` green; new test files committed under `backend/tests/{unit,integration}/adapters/`.

---

### Story 2.3 — `list_targets()`, `get_schema()`, `list_query_parsers()`

**Outcome:** `await adapter.get_schema(target)` returns a `Schema` with field types + analyzers per FR-4. `list_targets()` enumerates indices via `_cat/indices?format=json` (or `_aliases`); `list_query_parsers()` returns the static `["match", "multi_match", "function_score", "bool", "match_phrase"]` set MVP1 templates use.

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/elastic.py` | Implement `list_targets`, `get_schema`, `list_query_parsers`. |

**Key interfaces**

```python
async def list_targets(self, *, request_id: str | None = None) -> list[TargetInfo]:
    resp = await self._request(
        "GET", "/_cat/indices",
        params={"format": "json", "h": "index,docs.count"},
        request_id=request_id,
    )
    resp.raise_for_status()
    return [
        TargetInfo(name=row["index"], doc_count=int(row["docs.count"]) if row.get("docs.count") else None)
        for row in resp.json()
        if not row["index"].startswith(".")  # hide system indices
    ]


async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
    """Build a Schema from `_mapping` + index settings (for default analyzer).

    Error normalization:
    - 404 → `TargetNotFoundError`
    - Connection / 401/403/5xx → `ClusterUnreachableError` (handled inside
      `_request` via `translate_errors=True`, the default).
    - Spec §13 one-retry-on-ConnectionError applies via `_request`.

    Analyzer derivation (no `_field_caps`; that endpoint does not return analyzer
    info on either ES or OpenSearch — cycle 1 F6):
    - Explicit `analyzer` in the field's mapping → use it verbatim.
    - `text` field with no explicit analyzer → use the index's default analyzer
      from `_settings` (`index.analysis.analyzer.default.type` or "standard").
    - Non-`text` fields (`keyword`, `float`, etc.) → `analyzer = None`.

    Raises:
        TargetNotFoundError: when the cluster returns 404 for the target.
        ClusterUnreachableError: connection or auth failure (raised inside `_request`).
    """
    from backend.app.adapters.errors import TargetNotFoundError

    mapping_resp = await self._request("GET", f"/{target}/_mapping", request_id=request_id)
    if mapping_resp.status_code == 404:
        raise TargetNotFoundError(target)
    if mapping_resp.status_code >= 400:
        # Other 4xx — treat as unreachable; spec §8.5 has no separate error code
        # for "mapping fetch failed".
        from backend.app.adapters.errors import ClusterUnreachableError
        raise ClusterUnreachableError(
            f"HTTP {mapping_resp.status_code} from /{target}/_mapping"
        )
    mapping = mapping_resp.json()
    if not mapping:
        return Schema(name=target, fields=[])
    inner = next(iter(mapping.values()))
    props = inner.get("mappings", {}).get("properties", {})

    default_analyzer = await self._resolve_default_analyzer(target, request_id=request_id)

    fields: list[FieldSpec] = []
    for name, defn in props.items():
        ftype = defn.get("type", "object")
        analyzer = defn.get("analyzer")
        if analyzer is None and ftype == "text":
            analyzer = default_analyzer
        fields.append(FieldSpec(name=name, type=ftype, analyzer=analyzer))
    return Schema(name=target, fields=fields)


async def _resolve_default_analyzer(
    self, target: str, *, request_id: str | None = None
) -> str:
    """Fetch the index's default analyzer; falls back to 'standard'.

    Errors here degrade to "standard" rather than propagating — the analyzer
    fallback is a UX nicety, not a load-bearing contract. The caller already
    succeeded in fetching `_mapping` so cluster connectivity is established.
    """
    try:
        resp = await self._request(
            "GET", f"/{target}/_settings", request_id=request_id
        )
    except Exception:  # noqa: BLE001 — defensive: degrade to default
        return "standard"
    if resp.status_code != 200:
        return "standard"
    body = resp.json()
    if not body:
        return "standard"
    inner = next(iter(body.values()))
    analysis = inner.get("settings", {}).get("index", {}).get("analysis", {})
    default = analysis.get("analyzer", {}).get("default", {})
    return default.get("type", "standard")


def list_query_parsers(self) -> list[str]:
    return ["match", "multi_match", "match_phrase", "bool", "function_score"]
```

```python
# backend/app/adapters/errors.py
from __future__ import annotations


class ClusterUnreachableError(Exception):
    """Cluster connection / auth / 5xx failure. Maps to 503 CLUSTER_UNREACHABLE."""


class TargetNotFoundError(LookupError):
    """Target index/collection not found on the cluster. Maps to 404 TARGET_NOT_FOUND."""

    def __init__(self, target: str) -> None:
        super().__init__(target)
        self.target = target


# Story 2.5 extends this module with InvalidQueryDSLError + QueryTimeoutError.
```

**Modified files** (Story 2.3 extends the `errors.py` module created in Story 2.1)

| File | Change |
|---|---|
| `backend/app/adapters/errors.py` | Add `TargetNotFoundError(LookupError)` (raised by `get_schema` on 404). Story 2.5 will extend with `InvalidQueryDSLError` + `QueryTimeoutError`. |

**Tasks**
1. Create `backend/app/adapters/errors.py` with `ClusterUnreachableError` and `TargetNotFoundError`. (Story 2.5 extends with `InvalidQueryDSLError` + `QueryTimeoutError`.)
2. Implement `list_targets`, `get_schema`, `list_query_parsers`, and `_resolve_default_analyzer`.
3. Add integration test `backend/tests/integration/test_elastic_schema.py` with a `pytest-recording` cassette of `_mapping` + `_settings` against the local ES 9 and OpenSearch 2.18 containers (covers AC-2 and FR-4). Asserts:
   - `Schema.fields` is non-empty and contains expected types.
   - For a `text` field with no explicit `analyzer`, the resolved analyzer is `"standard"` (cycle 1 F6 fix — verifies the synthesis path, not `_field_caps`).
   - For a `text` field with an explicit custom analyzer in the mapping, the explicit value is preserved.
   - `_field_caps` is NOT called by `get_schema` (cassette assertion — count of cassette interactions matches `_mapping` + `_settings` only).
   - 404 mapping → `TargetNotFoundError`; auth/5xx mapping → `ClusterUnreachableError`.

**DoD**
- AC-2 passes (schema for a `products` index returns 4 `FieldSpec` entries with correct types and `analyzer="standard"` for default text fields).
- `pytest-recording` cassettes for `_mapping` and `_settings` (NOT `_field_caps` — see cycle 1 F6 + cycle 2 F5) committed under `backend/tests/integration/cassettes/`.
- `make test-integration` green.

---

### Story 2.4 — `render(template, params, query_text)`

**Outcome:** `adapter.render(template, params, query_text)` produces an ES/OpenSearch Query DSL `NativeQuery` per FR-2. Handles the `multi_match + function_score + field_boosts` canonical templates per spec §14.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/query/render.py` | Pure rendering helper: takes `QueryTemplate.body` (Jinja2 source) + params; returns the rendered dict. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/elastic.py` | Implement `render(template, params, query_text)` — delegates to `domain.query.render` and wraps the result as `NativeQuery`. Validates required params from `template.declared_params`. |
| `pyproject.toml` | Add `jinja2>=3.1` to runtime dependencies (already pulled in transitively via FastAPI but make explicit). |

**Key interfaces**

```python
# backend/app/domain/query/render.py
from __future__ import annotations

import json
from typing import Any

from jinja2 import StrictUndefined, Template


def render_template(template_body: str, context: dict[str, Any]) -> dict:
    """Render a Jinja2 template to a JSON object.

    StrictUndefined raises on missing params (caller catches and translates to a clear error).
    """
    rendered = Template(template_body, undefined=StrictUndefined).render(**context)
    return json.loads(rendered)
```

```python
# backend/app/adapters/elastic.py (continued)
def render(
    self,
    template: QueryTemplate,
    params: dict[str, ParamValue],
    query_text: str,
) -> NativeQuery:
    from backend.app.domain.query.render import render_template

    # Verify declared params are satisfied (declared_params is {param_name: hint}).
    missing = set(template.declared_params) - set(params.keys())
    if missing:
        raise ValueError(f"render: missing required template params: {sorted(missing)}")

    context = {**params, "query_text": query_text}
    body = render_template(template.body, context)
    # query_id is generated for the caller; search_batch lets callers pass their own.
    return NativeQuery(query_id=template.name, body=body)
```

**Tasks**
1. Implement `render_template` and `render`.
2. Add unit test `backend/tests/unit/adapters/test_elastic_render.py` (per spec §14) covering: canonical multi_match template renders to expected ES DSL JSON; missing required param raises `ValueError`; field_boosts → `fields: ["title^2", …]` mapping; function_score template wraps base query.
3. Add unit test `backend/tests/unit/domain/test_render.py` covering pure Jinja path (no adapter dep).

**DoD**
- `test_elastic_render.py` passes for the three canonical template shapes named in spec §14.
- `make test-unit` green.

---

### Story 2.5 — `search_batch(target, queries, top_k, request_id?)` via `_msearch`

**Outcome:** `await adapter.search_batch(target, queries, top_k, request_id=…)` makes exactly **one** HTTP request to `_msearch` and returns `{query_id: [ScoredHit, …]}` per FR-3 + AC-4. Propagates `request_id` as `X-Opaque-Id`.

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/errors.py` | Extend with `InvalidQueryDSLError` and `QueryTimeoutError` (Story 2.3 created the module with `ClusterUnreachableError` + `TargetNotFoundError`). All four classes are imported by routers in Stories 3.3 / 3.4 to map to spec §8.5 error codes. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/elastic.py` | Implement `search_batch`. Body is the NDJSON `{"index": target}\n{query_body, "size": top_k}\n…` format. Parse responses preserving query_id order. |

**Key interfaces**

```python
async def search_batch(
    self,
    target: str,
    queries: list[NativeQuery],
    top_k: int,
    *,
    request_id: str | None = None,
    strict_errors: bool = False,
    timeout: float | None = None,
) -> dict[str, list[ScoredHit]]:
    """One `_msearch` call. Preserves query_id mapping.

    `strict_errors` controls per-query error handling:
    - False (default, hot-path / Optuna trial runner): per-query engine errors
      yield empty `[]` for that `query_id`; the caller records a trial failure.
    - True (run_query API path): per-query parsing errors raise
      `InvalidQueryDSLError`; per-query non-parse errors raise
      `ClusterUnreachableError`.

    `timeout` overrides the adapter's default httpx client timeout for this
    request. The run_query endpoint passes the operator-supplied budget so the
    spec's 5s default / 30s max actually fires (otherwise the adapter's 10s
    default would always pre-empt a 30s budget).
    """
    from backend.app.adapters.errors import (
        ClusterUnreachableError,
        InvalidQueryDSLError,
        QueryTimeoutError,
    )

    if not queries:
        return {}
    lines: list[str] = []
    for q in queries:
        lines.append(json.dumps({"index": target}))
        body = dict(q.body)
        body.setdefault("size", top_k)
        lines.append(json.dumps(body))
    ndjson_body = "\n".join(lines) + "\n"

    # Use the centralized `_request` so we get the spec §13 one-retry-on-
    # ConnectionError plus 401/403/5xx → ClusterUnreachableError translation.
    # `translate_errors=False` keeps top-level 4xx visible here so we can
    # distinguish a top-level parsing 400 (→ InvalidQueryDSLError when strict)
    # from a 401/403 (→ ClusterUnreachableError, even when strict).
    try:
        resp = await self._request(
            "POST",
            "/_msearch",
            content=ndjson_body,
            extra_headers={"Content-Type": "application/x-ndjson"},
            request_id=request_id,
            timeout=timeout,
            translate_errors=False,
        )
    except httpx.ReadTimeout as exc:
        # Read timeout that the retry path didn't recover — strict_errors
        # callers (run_query) get QueryTimeoutError; hot-path gets
        # ClusterUnreachableError so trial runners can degrade gracefully.
        if strict_errors:
            raise QueryTimeoutError(str(exc)) from exc
        raise ClusterUnreachableError(str(exc)) from exc
    except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ConnectTimeout) as exc:
        raise ClusterUnreachableError(str(exc)) from exc

    if resp.status_code in (401, 403):
        raise ClusterUnreachableError(
            f"Authentication failed (HTTP {resp.status_code}) for _msearch"
        )
    if resp.status_code >= 500:
        raise ClusterUnreachableError(f"HTTP {resp.status_code} from _msearch")
    if resp.status_code == 400:
        # Top-level 400 = the entire batch was rejected (e.g. malformed NDJSON
        # body). Strict callers want this as InvalidQueryDSLError; hot-path
        # callers get ClusterUnreachableError so trials degrade.
        body_txt = resp.text[:500]
        if strict_errors:
            raise InvalidQueryDSLError(f"_msearch rejected the request: {body_txt}")
        raise ClusterUnreachableError(f"HTTP 400 from _msearch: {body_txt}")
    resp.raise_for_status()
    payload = resp.json()
    out: dict[str, list[ScoredHit]] = {}
    for q, item in zip(queries, payload["responses"], strict=True):
        if "error" in item:
            err = item["error"]
            err_type = err.get("type") if isinstance(err, dict) else None
            if strict_errors:
                if err_type in ("parsing_exception", "x_content_parse_exception", "json_parse_exception"):
                    raise InvalidQueryDSLError(
                        f"query {q.query_id}: {err.get('reason') if isinstance(err, dict) else err}"
                    )
                raise ClusterUnreachableError(
                    f"query {q.query_id} failed: {err.get('reason') if isinstance(err, dict) else err}"
                )
            out[q.query_id] = []
            continue
        hits = item.get("hits", {}).get("hits", [])
        out[q.query_id] = [
            ScoredHit(doc_id=h["_id"], score=float(h.get("_score") or 0.0), source=h.get("_source"))
            for h in hits
        ]
    return out
```

**Tasks**
1. Implement `search_batch` per the signature above (with `strict_errors` + `timeout` kwargs).
2. Extend `errors.py` (created in Story 2.3) with `InvalidQueryDSLError` and `QueryTimeoutError`.
3. Add integration test `backend/tests/integration/test_elastic_msearch.py` (per spec §14) covering: 5-query batch → exactly one `_msearch` HTTP call observed in the cassette (AC-4); query_id mapping preserved; per-query error with `strict_errors=False` → empty list for that query_id; per-query `parsing_exception` with `strict_errors=True` → `InvalidQueryDSLError` (the run_query path's contract — reuses the same cassette via fixture parametrization); cluster connection error raises `ClusterUnreachableError`; explicit `timeout=0.001` raises `ClusterUnreachableError` (or `QueryTimeoutError` when `strict_errors=True`).

**DoD**
- AC-4 verified: cassette assertion proves single `_msearch` call.
- `test_elastic_msearch.py` green.
- `make test-integration` green.

---

### Story 2.6 — `explain(target, query, doc_id)`

**Outcome:** `await adapter.explain(target, query, doc_id)` returns a populated `ExplainTree` (recursive). The MVP1 UI surface is post-MVP2 but the adapter-level method is part of the Protocol (FR-1) and ships now.

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/elastic.py` | Implement `explain` — `POST /<target>/_explain/<doc_id>` with the query body. |

**Key interfaces**

```python
async def explain(
    self,
    target: str,
    query: NativeQuery,
    doc_id: str,
    *,
    request_id: str | None = None,
) -> ExplainTree:
    resp = await self._request(
        "POST",
        f"/{target}/_explain/{doc_id}",
        json=query.body,
        request_id=request_id,
    )
    if resp.status_code == 404:
        raise TargetNotFoundError(target)
    resp.raise_for_status()
    payload = resp.json()
    return _build_explain_tree(payload.get("explanation", {}), doc_id, payload.get("matched", False))


def _build_explain_tree(node: dict, doc_id: str, matched: bool) -> ExplainTree:
    return ExplainTree(
        doc_id=doc_id,
        matched=matched,
        value=float(node.get("value", 0.0)),
        description=node.get("description", ""),
        details=[
            _build_explain_tree(child, doc_id, matched)
            for child in node.get("details", [])
        ],
    )
```

**Tasks**
1. Implement `explain` + `_build_explain_tree`.
2. Add integration test `backend/tests/integration/test_elastic_explain.py` (cassette-replayed) covering: matched doc → non-empty `details`; unmatched doc → `matched=False`, `value=0.0`; missing target → `TargetNotFoundError`.

**DoD**
- `explain` returns valid `ExplainTree` for matched + unmatched cases.
- `make test-integration` green.

---

### Story 2.7 — Engine-branch + supported-auth completeness test

**Outcome:** A focused test confirms the small set of engine_type-aware branches behaves correctly (per spec §14 `test_elastic_engine_branch.py`).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/adapters/test_elastic_engine_branch.py` | Verifies engine_type pivots: `_enforce_min_version` thresholds (8.11 ES vs 2.0 OpenSearch); version-detection endpoint shape (both use `GET /` but differ in `version.distribution` for OpenSearch). |

**Tasks**
1. Write tests using mocked `httpx.AsyncClient.request` (via `pytest-mock`'s `respx` or hand-rolled `httpx.MockTransport`). Cover both engines.

**DoD**
- `test_elastic_engine_branch.py` exercises both `engine_type="elasticsearch"` and `engine_type="opensearch"` paths.
- `make test-unit` green.

---

### Epic 2 gate (hard stop)

- [ ] All six Protocol methods implemented in `ElasticAdapter`.
- [ ] `pytest-recording` cassettes committed for `_cluster/health`, `_mapping`+`_settings`, `_msearch`, `_explain` against ES 9.4 and OpenSearch 2.18 containers (cycle 2 F5: `_field_caps` was removed from `get_schema`; cassette inventory excludes it).
- [ ] AC-2, AC-4, AC-5, AC-7 demonstrably pass at the adapter layer (still need the API layer for AC-1, AC-3, AC-6, AC-8).
- [ ] `make lint typecheck test-unit test-integration` green.
- [ ] No engine-specific code outside `backend/app/adapters/` (CLAUDE.md Absolute Rule #4 — grep `_msearch`, `_cluster/health`, `_field_caps`, `_explain` and confirm matches only inside `backend/app/adapters/`).

---

## Epic 3 — API surface

### Story 3.1 — Cluster service + adapter dispatch

**Outcome:** `cluster_service` orchestrates: registration probe (FR-5 / AC-1, AC-6, AC-7), adapter resolution by `cluster_id`, soft-delete enforcement. The router (Story 3.2) calls service functions; service composes repo + adapter + Redis.

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/cluster.py` | `register_cluster`, `get_cluster_for_request`, `delete_cluster`, `dispatch_run_query`, `dispatch_get_schema` (latter two delegate to adapter). |
| `backend/app/services/__init__.py` | Empty (or re-exports if needed) |

**Modified files**

| File | Change |
|---|---|
| (none — service layer is new) | |

**Key interfaces**

```python
# backend/app/services/cluster.py
from __future__ import annotations

from typing import Any

import uuid_utils
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.credentials import CredentialsMissing
from backend.app.adapters.elastic import (
    ElasticAdapter,
    SUPPORTED_ENGINE_TYPES,
    SUPPORTED_ENVIRONMENTS,
    SUPPORTED_AUTH_KINDS,
    RESERVED_AUTH_KINDS,
)
from backend.app.adapters.errors import ClusterUnreachableError
from backend.app.adapters.health_cache import read_cached_health, write_cached_health
from backend.app.adapters.protocol import HealthStatus
from backend.app.db import repo
from backend.app.db.models import Cluster


class ClusterUnreachable(Exception):
    """Surfaces 503 CLUSTER_UNREACHABLE at the router."""


class ClusterNameTaken(Exception):
    """Surfaces 409 CLUSTER_NAME_TAKEN at the router."""


class EngineTypeNotSupported(Exception):
    """Surfaces 400 ENGINE_NOT_SUPPORTED at the router."""


class AuthKindNotSupported(Exception):
    """Surfaces 400 AUTH_KIND_NOT_SUPPORTED at the router.

    Used both for unknown values AND reserved-but-unimplemented values
    (e.g. `opensearch_sigv4`).
    """


async def register_cluster(
    db: AsyncSession,
    redis: Redis,
    *,
    name: str,
    engine_type: str,
    environment: str,
    base_url: str,
    auth_kind: str,
    credentials_ref: str,
    engine_config: dict | None,
    notes: str | None,
) -> tuple[Cluster, HealthStatus]:
    """FR-5: validate enums → probe → insert (or revive). Reject if unreachable.

    Resurrection path (per spec §10 Data retention): if a row with the same name
    exists but is soft-deleted, it is revived (`deleted_at = NULL`) with the new
    field values rather than INSERTed (which would violate the unique constraint).
    """
    # Enum validation — done in service so the right error code surfaces (FR-5).
    # `environment` is validated by Pydantic Literal at the request layer and
    # surfaces as 422 VALIDATION_ERROR (no spec domain code for it); only the
    # fields with spec-defined domain codes get service-level checks here.
    if engine_type not in SUPPORTED_ENGINE_TYPES:
        raise EngineTypeNotSupported(
            f"engine_type must be one of: {sorted(SUPPORTED_ENGINE_TYPES)} (got: {engine_type!r})"
        )
    if auth_kind in RESERVED_AUTH_KINDS:
        raise AuthKindNotSupported(
            f"{auth_kind} is reserved but not implemented in MVP1"
        )
    if auth_kind not in SUPPORTED_AUTH_KINDS:
        raise AuthKindNotSupported(
            f"auth_kind must be one of: {sorted(SUPPORTED_AUTH_KINDS | RESERVED_AUTH_KINDS)}"
        )

    # Name conflict / revival detection (spec §10 — operator may resurrect).
    existing = await repo.get_any_cluster_by_name(db, name)
    if existing is not None and existing.deleted_at is None:
        raise ClusterNameTaken(name)

    cluster_id_for_probe = existing.id if existing is not None else str(uuid_utils.uuid7())

    # Build adapter; catch CredentialsMissing here so it surfaces as
    # CLUSTER_UNREACHABLE rather than escaping as a generic 500 (F8 fix).
    try:
        adapter = ElasticAdapter(
            cluster_id=cluster_id_for_probe,
            engine_type=engine_type,
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=engine_config,
        )
    except CredentialsMissing as exc:
        raise ClusterUnreachable(f"credentials resolution failed: {exc}") from exc

    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()

    if health.status == "unreachable":
        raise ClusterUnreachable(health.error or "cluster did not respond within timeout")

    # Auto-fill engine_config.api_version from health.version (Decision Log 2026-05-09)
    cfg = dict(engine_config or {})
    if "api_version" not in cfg and health.version:
        cfg["api_version"] = health.version.split(".")[0]

    if existing is not None:
        # Revive the soft-deleted row.
        cluster = await repo.revive_cluster(
            db, existing,
            engine_type=engine_type,
            environment=environment,
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=cfg or None,
            notes=notes,
        )
    else:
        cluster = await repo.create_cluster(
            db,
            id=cluster_id_for_probe,
            name=name,
            engine_type=engine_type,
            environment=environment,
            base_url=base_url,
            auth_kind=auth_kind,
            credentials_ref=credentials_ref,
            engine_config=cfg or None,
            notes=notes,
        )
    await db.commit()
    await write_cached_health(redis, cluster.id, health)
    return cluster, health


async def get_or_probe_health(
    redis: Redis, cluster: Cluster
) -> HealthStatus:
    """Return cached HealthStatus or freshly probe (30s TTL)."""
    cached = await read_cached_health(redis, cluster.id)
    if cached is not None:
        return cached
    try:
        adapter = _build_adapter(cluster)
    except CredentialsMissing as exc:
        from datetime import datetime, timezone
        return HealthStatus(
            status="unreachable",
            checked_at=datetime.now(timezone.utc).isoformat(),
            error=f"credentials resolution failed: {exc}",
        )
    try:
        health = await adapter.health_check()
    finally:
        await adapter.aclose()
    await write_cached_health(redis, cluster.id, health)
    return health


def _build_adapter(cluster: Cluster) -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id=cluster.id,
        engine_type=cluster.engine_type,
        base_url=cluster.base_url,
        auth_kind=cluster.auth_kind,
        credentials_ref=cluster.credentials_ref,
        engine_config=cluster.engine_config,
    )
```

**Tasks**
1. Implement service functions per the signatures above (including `EngineTypeNotSupported`, `AuthKindNotSupported`, revival path through `repo.get_any_cluster_by_name` / `repo.revive_cluster`).
2. Implement `_build_adapter` helper used by Stories 3.3, 3.4 (schema endpoint, run_query endpoint).
3. Add integration test `backend/tests/integration/test_cluster_service.py` covering:
   - `register_cluster` happy path against test ES container.
   - `register_cluster` with bad host raises `ClusterUnreachable` and **does not insert** (AC-6).
   - `register_cluster` with `opensearch_sigv4` raises `AuthKindNotSupported`; with unknown `auth_kind` also raises `AuthKindNotSupported`.
   - `register_cluster` with unknown `engine_type` raises `EngineTypeNotSupported`.
   - Duplicate active name raises `ClusterNameTaken`.
   - **Resurrection path:** soft-delete a cluster, then re-register with the same name + new fields → `revive_cluster` is called; the row's `deleted_at` is cleared; new fields applied.
   - Missing credentials YAML during `register_cluster` raises `ClusterUnreachable` (not generic 500) — covers F8 fix.
   - `get_or_probe_health` returns cache on second call within 30s (no second HTTP request observed).

**DoD**
- AC-6 (unreachable → no DB insert) verified by integration test.
- `register_cluster` exception classes map cleanly to spec §7.5 error codes (router translates).
- `make test-integration` green.

---

### Story 3.2 — Cluster CRUD router (`POST` / `GET` list / `GET` detail / `DELETE`)

**Outcome:** Four endpoints from spec §7.1 wired up:

| Method | Path | Errors |
|---|---|---|
| `POST` | `/api/v1/clusters` | `VALIDATION_ERROR` (422), `ENGINE_NOT_SUPPORTED` (400), `AUTH_KIND_NOT_SUPPORTED` (400), `CLUSTER_NAME_TAKEN` (409), `CLUSTER_UNREACHABLE` (503) |
| `GET` | `/api/v1/clusters` | `VALIDATION_ERROR` (422 — bad cursor) |
| `GET` | `/api/v1/clusters/{cluster_id}` | `CLUSTER_NOT_FOUND` (404) |
| `DELETE` | `/api/v1/clusters/{cluster_id}` | `CLUSTER_NOT_FOUND` (404) |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/clusters` | `CreateClusterRequest` | 201 `ClusterDetail` | `ENGINE_NOT_SUPPORTED`, `AUTH_KIND_NOT_SUPPORTED`, `CLUSTER_NAME_TAKEN`, `CLUSTER_UNREACHABLE`, `VALIDATION_ERROR` |
| `GET` | `/api/v1/clusters?cursor=&limit=&since=` | — | 200 `ClusterListResponse`; header `X-Total-Count: <n>` | — |
| `GET` | `/api/v1/clusters/{cluster_id}` | — | 200 `ClusterDetail` | `CLUSTER_NOT_FOUND` |
| `DELETE` | `/api/v1/clusters/{cluster_id}` | — | 204 (no body) | `CLUSTER_NOT_FOUND` |

Auth dependencies: none (single-tenant MVP1, no auth surface). Endpoints are open per [`api-conventions.md`](../../../01_architecture/api-conventions.md) and CLAUDE.md "Activates at MVP4".

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/v1/__init__.py` | Empty |
| `backend/app/api/v1/clusters.py` | The four endpoints above + the schema/run_query endpoints (Stories 3.3, 3.4) |
| `backend/app/api/v1/schemas.py` | Pydantic request/response models for cluster endpoints |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | `app.include_router(clusters.router, prefix="/api/v1", tags=["clusters"])` after the existing `app.include_router(health.router)` line. |
| `backend/app/core/settings.py` | Add `relyloop_allow_private_clusters: bool = Field(default=True, …)` per spec §10 Threat 3. Default `True` for MVP1 (operator convenience on laptop); flips to `False` at MVP3 hardening. |

**Pydantic schemas**

The request schema deliberately accepts `engine_type` and `auth_kind` as `str`
(not `Literal[...]`) so unknown values reach the service layer and surface as the
spec's domain-specific 400 codes (`ENGINE_NOT_SUPPORTED`, `AUTH_KIND_NOT_SUPPORTED`).
A `Literal` would short-circuit at Pydantic validation and produce a generic 422
`VALIDATION_ERROR`, which contradicts spec FR-5. Response models DO use `Literal`
because the values returned to the client are guaranteed by service-layer checks.

```python
# backend/app/api/v1/schemas.py
from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from backend.app.core.settings import get_settings

EngineType = Literal["elasticsearch", "opensearch"]
Environment = Literal["prod", "staging", "dev"]
AuthKind = Literal["es_apikey", "es_basic", "opensearch_basic", "opensearch_sigv4"]
HealthStatusValue = Literal["green", "yellow", "red", "unreachable"]


class HealthCheckResult(BaseModel):
    status: HealthStatusValue
    version: str | None = None
    checked_at: str
    error: str | None = None


class CreateClusterRequest(BaseModel):
    """Request body for POST /api/v1/clusters.

    `engine_type`, `environment`, and `auth_kind` accept arbitrary strings at the
    Pydantic layer; the service-layer validates them against the SUPPORTED sets
    and raises domain exceptions that the router translates to spec §8.5 error
    codes (`ENGINE_NOT_SUPPORTED`, `AUTH_KIND_NOT_SUPPORTED`). Pydantic `Literal`
    here would produce a generic 422 `VALIDATION_ERROR`, breaking spec FR-5.
    """

    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    engine_type: str = Field(min_length=1, max_length=64)
    # `environment` is `Literal` here because spec §8.5 defines no
    # ENVIRONMENT_NOT_SUPPORTED error code — invalid values surface as the
    # standard 422 VALIDATION_ERROR via the existing Pydantic handler. This is
    # the right behavior per api-conventions; only fields that have a spec-
    # defined domain code (engine_type → ENGINE_NOT_SUPPORTED, auth_kind →
    # AUTH_KIND_NOT_SUPPORTED) accept str + service-level validation.
    environment: Environment
    base_url: str = Field(min_length=1, max_length=512)
    auth_kind: str = Field(min_length=1, max_length=64)
    credentials_ref: str = Field(min_length=1, max_length=128)
    engine_config: dict | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Validate scheme + host per spec §10 Threat 3.

        - Scheme must be http or https (other schemes → 422 VALIDATION_ERROR).
        - Host must not be a private-range IP unless `RELYLOOP_ALLOW_PRIVATE_CLUSTERS`
          is true. Default is true in MVP1 (laptop convenience); flips to false at
          MVP3 hardening per spec §10.
        - Hostnames (non-IP) always pass — DNS resolution to private IPs is not
          checked at validation time (would require DNS I/O on every POST).
        """
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must use http or https scheme")
        if not parsed.hostname:
            raise ValueError("base_url must include a host")
        try:
            ip = ip_address(parsed.hostname)
        except ValueError:
            return v  # hostname, not an IP — accept
        if ip.is_private or ip.is_loopback:
            if not get_settings().relyloop_allow_private_clusters:
                raise ValueError(
                    f"base_url host {parsed.hostname} is a private-range IP "
                    f"and RELYLOOP_ALLOW_PRIVATE_CLUSTERS is false"
                )
        return v


class ClusterDetail(BaseModel):
    id: str
    name: str
    engine_type: EngineType
    environment: Environment
    base_url: str
    auth_kind: AuthKind
    engine_config: dict | None = None
    notes: str | None = None
    created_at: datetime
    health_check: HealthCheckResult


class ClusterSummary(BaseModel):
    """List view — drops engine_config + notes for brevity."""
    id: str
    name: str
    engine_type: EngineType
    environment: Environment
    base_url: str
    auth_kind: AuthKind
    created_at: datetime
    health_check: HealthCheckResult


class ClusterListResponse(BaseModel):
    data: list[ClusterSummary]
    next_cursor: str | None
    has_more: bool


class RunQueryRequest(BaseModel):
    target: str = Field(min_length=1, max_length=256)
    query_dsl: dict
    top_k: int = Field(default=10, ge=1, le=1000)  # Decision Log 2026-05-09: cap at 1000


class RunQueryHit(BaseModel):
    doc_id: str
    score: float
    source: dict | None = None


class RunQueryResponse(BaseModel):
    hits: list[RunQueryHit]
```

**Key interfaces** (router skeleton)

```python
# backend/app/api/v1/clusters.py
from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.health import get_redis_client
from backend.app.api.v1.schemas import (
    ClusterDetail,
    ClusterListResponse,
    CreateClusterRequest,
    HealthCheckResult,
)
from backend.app.db import repo
from backend.app.db.session import get_db
from backend.app.services import cluster as cluster_svc
from backend.app.services.cluster import (
    AuthKindNotSupported,
    ClusterNameTaken,
    ClusterUnreachable,
)

router = APIRouter()


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


@router.post("/clusters", response_model=ClusterDetail, status_code=201)
async def create_cluster(
    body: CreateClusterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> ClusterDetail: ...

# … get list, get detail, delete, schema, run_query (Stories 3.3, 3.4)
```

**Tasks**
1. Implement Pydantic schemas in `backend/app/api/v1/schemas.py`. Note the deliberate split:
   - `engine_type` and `auth_kind` are typed as `str` (not `Literal`) so unknown values reach the service and surface as the spec's domain-specific 400 codes (`ENGINE_NOT_SUPPORTED` / `AUTH_KIND_NOT_SUPPORTED`); a `Literal` would short-circuit at Pydantic validation and produce a generic 422 (cycle 1 F2 fix).
   - `environment` IS `Literal["prod", "staging", "dev"]` because spec §8.5 defines no `ENVIRONMENT_NOT_SUPPORTED` code — invalid values legitimately surface as 422 `VALIDATION_ERROR` (cycle 2 F1 / cycle 3 F3 fix). Do NOT change this back to `str`.
2. Add `relyloop_allow_private_clusters: bool = Field(default=True, …)` to `backend/app/core/settings.py`.
3. Implement the four endpoints in `backend/app/api/v1/clusters.py`. Translate service exceptions:
   - `EngineTypeNotSupported` → 400 `ENGINE_NOT_SUPPORTED`
   - `AuthKindNotSupported` → 400 `AUTH_KIND_NOT_SUPPORTED`
   - `ClusterNameTaken` → 409 `CLUSTER_NAME_TAKEN`
   - `ClusterUnreachable` → 503 `CLUSTER_UNREACHABLE`
4. Wire cursor decoder/encoder helpers — base64-encoded `(created_at_iso, id)` JSON; reject malformed cursors with 422 `VALIDATION_ERROR`.
5. Set `X-Total-Count` header on the list response using `repo.count_clusters`.
6. Register the router in `backend/app/main.py`.
7. Add integration test `backend/tests/integration/test_clusters_api.py` covering the full flow against the test ES container:
   - POST happy path → 201 + cluster row + cached health (AC-1 partial).
   - POST with `auth_kind=opensearch_sigv4` → 400 `AUTH_KIND_NOT_SUPPORTED` (AC-7).
   - POST with `auth_kind="bogus"` → 400 `AUTH_KIND_NOT_SUPPORTED`.
   - POST with `engine_type="solr"` → 400 `ENGINE_NOT_SUPPORTED`.
   - POST with `base_url="ftp://x"` → 422 `VALIDATION_ERROR`.
   - POST with bad URL → 503 `CLUSTER_UNREACHABLE`, no DB row (AC-6).
   - POST with `base_url="http://10.0.0.1:9200"` and `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=false` → 422 `VALIDATION_ERROR`; same with default-true → reaches probe (then 503 because nothing's listening).
   - GET list returns inserted row + `X-Total-Count` header.
   - GET detail returns `health_check`.
   - DELETE → 204; subsequent GET detail → 404 `CLUSTER_NOT_FOUND` (AC-8).
   - Re-POST with the soft-deleted name → 201 with the row revived (cycle 1 F5 fix verified end-to-end).

**DoD**
- AC-1 (registration), AC-6 (unreachable rejected), AC-7 (sigv4 rejected), AC-8 (soft-delete) pass via `test_clusters_api.py`.
- All three routes return `ClusterDetail` shape per spec §7.3.
- `X-Total-Count` header populated on list endpoint.
- `make test-integration test-contract` green.

---

### Story 3.3 — Schema introspection endpoint (`GET /api/v1/clusters/{cluster_id}/schema`)

**Outcome:** `GET /api/v1/clusters/{cluster_id}/schema?target=<index>` returns the `Schema` per FR-4 + AC-2.

**Endpoints**

| Method | Path | Request | Success | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/schema` | `?target=<str>` query | 200 `Schema` (FieldSpec list) | `CLUSTER_NOT_FOUND` (404), `TARGET_NOT_FOUND` (404), `CLUSTER_UNREACHABLE` (503), `VALIDATION_ERROR` (422 — missing `target` param) |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/clusters.py` | Add `GET /clusters/{cluster_id}/schema` handler. |

**Tasks**
1. Implement the handler — calls `cluster_svc._build_adapter(cluster).get_schema(target)`; translate `TargetNotFoundError` → 404 `TARGET_NOT_FOUND`; `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE`.
2. Add integration test in `backend/tests/integration/test_clusters_api.py` (extend the file from Story 3.2): seed an index on the ES test container with the four fields from AC-2; assert `Schema.fields` length 4 with correct types.

**DoD**
- AC-2 passes end-to-end (HTTP request → 200 with full Schema).
- `make test-integration` green.

---

### Story 3.4 — Run-query endpoint (`POST /api/v1/clusters/{cluster_id}/run_query`)

**Outcome:** `POST /api/v1/clusters/{cluster_id}/run_query` executes one query DSL fragment and returns hits per FR-6 + AC-3. `top_k` capped at 1000 (Pydantic). 5s default timeout, configurable via `?timeout_s=` (max 30s).

**Endpoints**

| Method | Path | Request body | Success | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/clusters/{cluster_id}/run_query` | `RunQueryRequest` (`{target, query_dsl, top_k=10}`); `?timeout_s=5` (1–30) | 200 `RunQueryResponse` | `CLUSTER_NOT_FOUND` (404), `INVALID_QUERY_DSL` (400), `QUERY_TIMEOUT` (504), `CLUSTER_UNREACHABLE` (503), `VALIDATION_ERROR` (422 — top_k > 1000) |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/clusters.py` | Add `POST /clusters/{cluster_id}/run_query` handler. |
| `backend/app/services/cluster.py` | Add `dispatch_run_query(adapter, target, query_dsl, top_k, timeout_s)` — wraps the adapter call in `asyncio.wait_for(timeout_s)`; translates DSL parse errors to `InvalidQueryDSLError`. |

**Key interfaces**

```python
async def dispatch_run_query(
    adapter: ElasticAdapter,
    *,
    target: str,
    query_dsl: dict,
    top_k: int,
    timeout_s: float,
) -> list[ScoredHit]:
    """Execute one query as a 1-element search_batch and unpack.

    `timeout_s` is threaded into the adapter via httpx (so a 30s operator budget
    actually fires; the adapter's default 10s client timeout would otherwise
    pre-empt). `asyncio.wait_for` is the outer guard — it catches a hung event
    loop case where httpx itself doesn't honor the deadline.
    """
    import asyncio

    query = NativeQuery(query_id="run_query", body={"query": query_dsl, "size": top_k})
    try:
        result = await asyncio.wait_for(
            adapter.search_batch(
                target=target,
                queries=[query],
                top_k=top_k,
                strict_errors=True,    # run_query path wants explicit errors
                timeout=timeout_s,     # threaded into httpx
            ),
            timeout=timeout_s + 1.0,   # outer wall-clock guard, slack for cleanup
        )
    except TimeoutError as exc:
        raise QueryTimeoutError(f"query exceeded {timeout_s}s budget") from exc
    return result.get("run_query", [])
```

**Tasks**
1. Implement the handler — translate `InvalidQueryDSLError` → 400 `INVALID_QUERY_DSL`, `QueryTimeoutError` → 504 `QUERY_TIMEOUT`, `ClusterUnreachableError` → 503 `CLUSTER_UNREACHABLE`.
2. Implement `dispatch_run_query` per the signature above. The strict_errors / timeout-passthrough contract was finalized in Story 2.5, so this story consumes it without modifying the adapter.
3. Extend `backend/tests/integration/test_clusters_api.py` with `run_query` happy path against ES test container (AC-3) and the four error paths (404 unknown cluster, 400 INVALID_QUERY_DSL via malformed DSL, 504 QUERY_TIMEOUT via tiny timeout against a slow-by-design cassette, 422 VALIDATION_ERROR for top_k=1001).
4. Add unit test `backend/tests/unit/services/test_dispatch_run_query.py` covering: timeout path raises `QueryTimeoutError`; happy path returns hits; cluster error propagates as `ClusterUnreachableError`; bad DSL raises `InvalidQueryDSLError`.

**DoD**
- AC-3 passes (5 hits or fewer, descending by score).
- 1001 in `top_k` → 422 `VALIDATION_ERROR` (Pydantic).
- `make test-integration test-contract` green.

---

### Story 3.5 — Extend `/healthz` with `subsystems.elasticsearch_clusters`

**Outcome:** `/healthz` reports an aggregate field describing cluster-registration health for user-registered clusters per spec §2 ("the existing `elasticsearch` subsystem probes only the local Compose container; the new field probes user-registered clusters").

**Caveat (review-log finding):** Spec §7 has no FR for this. Plan implements per spec §2 text but flags this gap for resolution at the cross-model review or by the user.

**Aggregate field shape:**

```json
{
  "subsystems": {
    …existing fields…,
    "elasticsearch_clusters": {
      "registered": <int>,            // total non-deleted
      "healthy": <int>,                // status in {green, yellow}
      "unreachable": <int>             // status in {red, unreachable}
    }
  }
}
```

When `registered == 0`, the field is still present with all zeros — never omitted. Per CLAUDE.md Absolute Rule #11, the probe must respect the 200ms timeout — the implementation reads cached `cluster:health:{cluster_id}` keys only; no live cluster probes inside `/healthz`. If the cache is missing for a cluster, the cluster is counted as `unreachable` (consistent with "stale or unprobed = degraded").

`status: "degraded"` is **not** triggered by `unreachable > 0` clusters — registered user clusters going down does not page the operator (they may be intentionally offline). The field is informational.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/health.py` | Add a fifth await to `asyncio.gather()` that queries Redis for all `cluster:health:*` keys (or pulls cluster IDs from DB) and aggregates. Add `clusters: ClusterAggregateHealth` field to the `Subsystems` model. |
| `backend/app/api/probes.py` | Add `probe_registered_clusters(db: AsyncSession, redis: Redis) -> ClusterAggregateHealth`. |

**Key interfaces**

```python
# backend/app/api/probes.py
class ClusterAggregateHealth(BaseModel):
    registered: int
    healthy: int
    unreachable: int


async def probe_registered_clusters(
    db: AsyncSession, redis: Redis
) -> ClusterAggregateHealth:
    """Read all non-deleted clusters; for each, read cached HealthStatus from Redis."""
    clusters = await repo.list_clusters(db, limit=1000)  # MVP1: well under 1000 in practice
    healthy = 0
    unreachable = 0
    for c in clusters:
        status = await read_cached_health(redis, c.id)
        if status is None or status.status in ("red", "unreachable"):
            unreachable += 1
        else:
            healthy += 1
    return ClusterAggregateHealth(
        registered=len(clusters), healthy=healthy, unreachable=unreachable
    )
```

**Tasks**
1. Add `ClusterAggregateHealth` model + `probe_registered_clusters` to `probes.py`.
2. Wire it into the `asyncio.gather` in `healthz()`. Wrap in `asyncio.wait_for(timeout=PROBE_TIMEOUT_SECONDS)`. On timeout return `ClusterAggregateHealth(registered=0, healthy=0, unreachable=0)`.
3. Update the existing health-check tests `backend/tests/unit/test_health.py`, `backend/tests/contract/test_health_contract.py`, `backend/tests/integration/test_health_integration.py` to assert the new field is present and has the documented shape.

**DoD**
- `/healthz` JSON includes `subsystems.elasticsearch_clusters` with the documented shape.
- `/healthz` p99 stays under 500ms (existing assertion in `test_health_contract.py` still holds).
- `make test-unit test-contract test-integration` green.

---

### Epic 3 gate (hard stop)

- [ ] All 6 endpoints from spec §7.1 implemented and contract-tested.
- [ ] AC-1 (register), AC-2 (schema), AC-3 (run_query), AC-6 (unreachable), AC-7 (sigv4), AC-8 (soft-delete) demonstrably pass via `test_clusters_api.py`.
- [ ] AC-4 (single _msearch HTTP call) verified at adapter layer (Story 2.5) — also exercised by run_query.
- [ ] `/healthz` extension lands or is explicitly removed (depending on review-log resolution).
- [ ] `make lint typecheck test-unit test-integration test-contract` green.

---

## Epic 4 — Seed command + docs

### Story 4.1 — `make seed-clusters` command (idempotent)

**Outcome:** Running `make seed-clusters` registers `local-es` and `local-opensearch` cluster rows pointing at the local Compose containers per FR-7 + AC-1. Re-running does not duplicate or fail.

**New files**

| File | Purpose |
|---|---|
| `backend/app/scripts/__init__.py` | Empty |
| `backend/app/scripts/seed_clusters.py` | `python -m backend.app.scripts.seed_clusters` — entrypoint that opens an async session, calls `register_cluster` for both clusters, swallowing `ClusterNameTaken` for idempotency. |
| `backend/tests/integration/test_seed_clusters_idempotent.py` | Run twice; assert exactly two rows total (per spec §14). |

**Modified files**

| File | Change |
|---|---|
| `Makefile` | Add `seed-clusters` target: `docker compose exec -T api python -m backend.app.scripts.seed_clusters`. |

**Note on path:** spec §14/§7 say `python -m backend.scripts.seed_clusters`, but the project layout puts all importable code under `backend/app/` (see [`migrations/env.py`](../../../../migrations/env.py) `from backend.app.…`). Plan uses `backend.app.scripts.seed_clusters` for consistency. Story 4.2 patches the spec text.

**Key interfaces**

```python
# backend/app/scripts/seed_clusters.py
"""Idempotent seed of local-es and local-opensearch cluster rows.

Usage:
    python -m backend.app.scripts.seed_clusters

Re-running is safe — ClusterNameTaken is treated as success.
"""
from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db.session import get_session_factory
from backend.app.services.cluster import ClusterNameTaken, register_cluster

LOCAL_ES = dict(
    name="local-es",
    engine_type="elasticsearch",
    environment="dev",
    base_url="http://elasticsearch:9200",
    auth_kind="es_basic",
    credentials_ref="local-es",
    engine_config=None,
    notes="Local Elasticsearch container from infra_foundation Compose stack.",
)
LOCAL_OS = dict(
    name="local-opensearch",
    engine_type="opensearch",
    environment="dev",
    base_url="http://opensearch:9200",
    auth_kind="opensearch_basic",
    credentials_ref="local-opensearch",
    engine_config=None,
    notes="Local OpenSearch container from infra_foundation Compose stack.",
)


async def main() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    factory = get_session_factory()
    async with factory() as db:
        for spec in (LOCAL_ES, LOCAL_OS):
            try:
                await register_cluster(db, redis, **spec)
                print(f"Registered {spec['name']}")
            except ClusterNameTaken:
                print(f"{spec['name']} already registered (idempotent skip)")
    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

**Tasks**
1. Implement `seed_clusters.py` per the signature above.
2. Add `seed-clusters` Make target.
3. Add the seed-clusters credentials to the operator handoff: install.sh writes a default `secrets/cluster_credentials.yaml` with `local-es: {username: elastic, password: changeme}` and `local-opensearch: {username: admin, password: admin}` (matching the Compose container defaults from `infra_foundation`). **Verify the existing `infra_foundation` `install.sh` handles this** — if not, this story extends `scripts/install.sh` to add the cluster_credentials seed step (idempotent: skip if file exists).
4. Add integration test `backend/tests/integration/test_seed_clusters_idempotent.py` per spec §14 (run twice, assert exactly two rows).

**DoD**
- AC-1 passes — `make seed-clusters` produces two registered clusters with `health_check.status == "green"`.
- Re-running `make seed-clusters` is no-op (idempotent test green).
- `make test-integration` green.

---

### Story 4.2 — Documentation: cluster-registration runbook + spec/adapters.md path patches

**Outcome:** Operators can find a runbook for cluster registration; existing arch docs use the correct adapter path (`backend/app/adapters/`).

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/cluster-registration.md` | How to register a cluster (curl example), troubleshoot reachability, rotate credentials, OpenSearch 3.x known limitation. |

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/adapters.md` | s/`backend/adapters/`/`backend/app/adapters/`/g (lines 56, 70). Confirm spec text is updated to match. |
| `docs/02_product/planned_features/infra_adapter_elastic/feature_spec.md` | Section 3, 7, 8: replace `backend/adapters/` with `backend/app/adapters/`; replace `backend.scripts.seed_clusters` with `backend.app.scripts.seed_clusters`. Section 8 numbering — header is "8) API and data contract baseline" but subsections are 7.1–7.5. Renumber 7.x → 8.x. |
| `README.md` | Add `make seed-clusters` to the Quickstart block after `make migrate`. |
| `docs/02_product/mvp1-user-stories.md` | Mark US-4 / US-5 / US-6 as covered by `infra_adapter_elastic` (do NOT mark "implemented" until merge). |

**Tasks**
1. Author `cluster-registration.md` with: prerequisites, env-var checklist, `curl` example for `POST /api/v1/clusters`, troubleshooting (reachability, credentials, version skew), OpenSearch 3.x known limitation (Decision Log 2026-05-09).
2. Patch `adapters.md` and `feature_spec.md` paths.
3. Renumber spec §7.1–7.5 → §8.1–8.5.
4. Update README Quickstart.
5. Update `mvp1-user-stories.md` cross-references.

**DoD**
- `cluster-registration.md` exists and lints clean (markdownlint or eyeball).
- `grep -r "backend/adapters/" docs/` returns no results (only the corrected path remains).
- README Quickstart references `make seed-clusters`.
- US-4/5/6 cross-reference updated.

---

### Epic 4 gate

- [ ] `make seed-clusters` works on a fresh `make up` (spec §16 readiness gate).
- [ ] All docs patches landed.
- [ ] `make lint test-unit test-integration test-contract` green.

---

## Epic 5 — Test coverage audit + finalization

### Story 5.1 — Test coverage audit

**Outcome:** Every test file mentioned in spec §14 exists in the repo and is wired into the appropriate `pytest` collection. Backend coverage on `backend/app/adapters/elastic.py` and `backend/app/api/v1/clusters.py` is ≥80% (spec §18 + global gate).

**Tasks**
1. Verify against spec §14:
   - `backend/tests/unit/adapters/test_protocol.py` ✓ (Story 1.1)
   - `backend/tests/unit/adapters/test_elastic_render.py` ✓ (Story 2.4)
   - `backend/tests/unit/adapters/test_elastic_engine_branch.py` ✓ (Story 2.7)
   - `backend/tests/unit/adapters/test_auth_kinds.py` ✓ (Story 2.1)
   - `backend/tests/integration/test_elastic_msearch.py` ✓ (Story 2.5)
   - `backend/tests/integration/test_elastic_schema.py` ✓ (Story 2.3)
   - `backend/tests/integration/test_clusters_api.py` ✓ (Stories 3.2/3.3/3.4)
   - `backend/tests/integration/test_seed_clusters_idempotent.py` ✓ (Story 4.1)
   - `backend/tests/contract/test_clusters_api_contract.py` — **add now if missing** (per spec §14)
   - `backend/tests/contract/test_error_codes.py` — **add now if missing** (per spec §14, asserts every spec §7.5 error code produces the documented HTTP status + envelope shape)
2. Run `make test-unit test-integration test-contract` and confirm coverage report shows ≥80% for `backend/app/adapters/` and `backend/app/api/v1/`.
3. If a test file is missing, write it before merging.

**New files** (if missing after Stories 1–4)

| File | Purpose |
|---|---|
| `backend/tests/contract/test_clusters_api_contract.py` | Asserts request/response shapes match the FastAPI OpenAPI schema for the six cluster endpoints |
| `backend/tests/contract/test_error_codes.py` | One test per error code in spec §7.5 — verifies the envelope shape |

**DoD**
- All 10 test files in spec §14 exist and pass.
- Coverage report ≥80% on adapter + API modules.
- `make test` green end-to-end.

---

### Story 5.2 — Finalization (state.md / architecture.md / pipeline_status.md)

**Outcome:** Project context files reflect the merged feature.

**Modified files**

| File | Change |
|---|---|
| `state.md` | Move `infra_adapter_elastic` from "Queued" to "Most recent meaningful changes." Update Alembic head from `0001_baseline` to `0002_clusters_config_repos`. Update "Queued" priority list (next: `infra_optuna_eval`). |
| `architecture.md` | Add a row for `backend/app/adapters/` to the "Where the code lives" tree. |
| `CLAUDE.md` | Mark `infra_adapter_elastic` complete in the Feature Status table. |
| `docs/02_product/planned_features/infra_adapter_elastic/pipeline_status.md` | Update Implement section to "Complete (PR #<N>)". |

**Tasks**
1. Update state.md with the new Alembic head, recent change entry, and queue shift.
2. Update architecture.md "Where the code lives" tree to include `adapters/    engine adapters`.
3. Update CLAUDE.md feature status row.
4. Move feature folder per `/impl-execute` finalize convention (handled by impl-execute Step 7, not this plan).

**DoD**
- `state.md` shows `0002` head, `infra_adapter_elastic` in recent changes.
- `architecture.md` lists adapter layer.
- `CLAUDE.md` feature table updated.

---

### Epic 5 gate (final)

- [ ] All 10 test files from spec §14 present and green.
- [ ] Coverage gate (≥80%) passes on touched modules.
- [ ] All four phase gates above passed in order.
- [ ] No engine-specific code outside `backend/app/adapters/` (CLAUDE.md Absolute Rule #4).
- [ ] All documentation updates landed.

---

## 3) Testing workstream (required)

### 3.1 Unit tests

- Location: `backend/tests/unit/adapters/` + `backend/tests/unit/domain/` + `backend/tests/unit/services/`
- Scope: pure logic — Protocol shape, Pydantic types, render, auth-header building, credentials resolution, engine_type branches, dispatch_run_query timeout
- Files:
  - [ ] `test_protocol.py` — Story 1.1
  - [ ] `test_auth_kinds.py` — Story 2.1
  - [ ] `test_credentials.py` — Story 2.1 (new; not in spec §14 but supports FR-2 auth flow)
  - [ ] `test_health_cache.py` — Story 2.2 (new; supports 30s TTL Decision Log entry)
  - [ ] `test_elastic_render.py` — Story 2.4
  - [ ] `test_elastic_engine_branch.py` — Story 2.7
  - [ ] `test_render.py` (domain) — Story 2.4
  - [ ] `test_dispatch_run_query.py` — Story 3.4
- DoD: critical branches covered; all deterministic (no DB, no network).

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: DB-backed workflows + cassette-replayed adapter calls + ES/OpenSearch container interactions in CI
- Files:
  - [ ] `test_clusters_migration.py` — Story 1.3 (round-trip + CHECK constraints)
  - [ ] `test_cluster_repo.py` — Story 1.4
  - [ ] `test_elastic_health.py` — Story 2.2 (new; cassette-backed)
  - [ ] `test_elastic_schema.py` — Story 2.3
  - [ ] `test_elastic_msearch.py` — Story 2.5
  - [ ] `test_elastic_explain.py` — Story 2.6 (new; supports FR-1 protocol completeness)
  - [ ] `test_cluster_service.py` — Story 3.1
  - [ ] `test_clusters_api.py` — Stories 3.2/3.3/3.4
  - [ ] `test_seed_clusters_idempotent.py` — Story 4.1
- DoD: happy path + critical failure paths covered; cassettes committed.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: response shape vs OpenAPI; every error code produces documented HTTP status + envelope shape
- Files:
  - [ ] `test_clusters_api_contract.py` — Story 5.1 (per spec §14)
  - [ ] `test_error_codes.py` — Story 5.1 (per spec §14)
- DoD: every spec §7.5 code (`ENGINE_NOT_SUPPORTED`, `AUTH_KIND_NOT_SUPPORTED`, `CLUSTER_NAME_TAKEN`, `CLUSTER_NOT_FOUND`, `TARGET_NOT_FOUND`, `CLUSTER_UNREACHABLE`, `INVALID_QUERY_DSL`, `QUERY_TIMEOUT`) has at least one contract test.

### 3.4 E2E tests

- Location: `web/tests/e2e/`
- **N/A** — this feature has no UI surface (spec §11). UI lands later via `feat_studies_ui` and `feat_chat_agent`.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/test_health.py` | `Subsystems` model | 8 | Update — Story 3.5 adds `elasticsearch_clusters` field; existing assertions need to reflect new key |
| `backend/tests/contract/test_health_contract.py` | response body shape | 5 | Update — Story 3.5 |
| `backend/tests/integration/test_health_integration.py` | full body assertion | 3 | Update — Story 3.5 |
| `backend/tests/unit/test_probes.py` | per-probe coverage | 17 | Update — Story 3.5 adds `probe_registered_clusters` |
| `backend/tests/integration/test_migrations.py` | head revision | 1 | Update — head moves from `0001` → `0002` |

If Story 3.5 is dropped (post-review-log resolution), the four health/probe rows above are no-ops.

### 3.6 Migration verification

- [ ] `0002_clusters_config_repos` includes `downgrade()` (per Story 1.3 body).
- [ ] `alembic upgrade head` from clean DB succeeds.
- [ ] `alembic downgrade -1 && alembic upgrade head` round-trips.
- [ ] DB revision guard at API startup is **MVP2+ only**, not added now (CLAUDE.md "Migrations" §).

### 3.7 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration` (CI service-container Postgres + ES + OpenSearch)
- [ ] `make test-contract`
- [ ] `make lint typecheck`
- [ ] Coverage ≥80% gate (existing, no change)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files

**`state.md`** — update on completion (Story 5.2):
- [x] Active branch — moves to `main` on merge
- [x] Recent changes — add `infra_adapter_elastic PR #<N> merged` entry
- [x] Alembic head — `0002_clusters_config_repos`
- [x] Queued — remove `infra_adapter_elastic`; promote `infra_optuna_eval` to "next up"

**`architecture.md`** — update on completion (Story 5.2):
- [x] "Where the code lives" tree — add `adapters/    engine adapters (ElasticAdapter)`
- [x] Critical flows — add a "Cluster registration → adapter probe" entry pointing at `backend/app/services/cluster.py`

**`CLAUDE.md`** — update on completion (Story 5.2):
- [x] Feature Status table — `infra_adapter_elastic` row → "Complete (PR #<N>, merged YYYY-MM-DD)"

### 4.1 Architecture docs

- [x] `docs/01_architecture/adapters.md` — path patch (Story 4.2). Update `Status` line if the implementation surfaced new decisions worth recording.
- [x] `docs/01_architecture/data-model.md` — no change expected; the `clusters` and `config_repos` MVP1 shapes are already documented; this feature implements them.

### 4.2 Product docs

- [x] `docs/02_product/mvp1-user-stories.md` — mark US-4/5/6 as covered (Story 4.2).
- [x] `docs/02_product/planned_features/infra_adapter_elastic/feature_spec.md` — path + section-numbering patch (Story 4.2).

### 4.3 Runbooks

- [x] `docs/03_runbooks/cluster-registration.md` — created (Story 4.2).

### 4.4 Security docs

- [ ] No new entries — the feature follows the existing mounted-secrets pattern from `infra_foundation`. Spec §10 documents the threat model already.

### 4.5 Quality docs

- [ ] No change to `docs/05_quality/testing.md` — existing test-layer convention applies.

**Documentation DoD**
- [ ] `state.md`, `architecture.md`, `CLAUDE.md` consistent with merged behavior.
- [ ] `cluster-registration.md` dry-run validated against the seed flow.

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals

- This feature is purely additive — no existing modules require refactoring.
- The `/healthz` extension (Story 3.5) is the one in-place modification; minimal-surface approach.

### 5.2 Planned refactor tasks

- [x] Story 1.2 creates the `backend/app/db/models/` directory pattern (the first feature to need it). Future schema-owning features (`feat_study_lifecycle`) follow this pattern.
- [x] Story 1.4 creates `backend/app/db/repo/` directory pattern; same.
- [x] Story 3.1 creates `backend/app/services/` directory pattern; same.
- [x] Story 4.2 patches `backend/adapters/` → `backend/app/adapters/` in arch docs and the spec body to align with project layout.

### 5.3 Refactor guardrails

- [ ] Behavioral parity: the existing `/healthz` shape is preserved (Story 3.5 only adds a new field).
- [ ] Lint/typecheck remain green.
- [ ] No expansion of product scope: nothing beyond spec §3.
- [ ] Track discovered debt:
  - **Spec §2 vs §7 gap on `/healthz` extension** — flagged in §11 review log; resolution required before merge.
  - **`backend/adapters/` doc inconsistency** — patched by Story 4.2.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `infra_foundation` shipped (Postgres, Redis, Alembic, FastAPI skeleton, mounted secrets) | All stories | **Done — PR #4 merged 2026-05-09** | Cannot start (this feature builds on it) |
| `pyyaml>=6.0` (pip dep) | Story 2.1 (credentials YAML) | New — Story 2.1 adds | Adapter can't resolve credentials |
| `pytest-recording>=0.13` | Stories 2.2, 2.3, 2.5, 2.6 | **Done — already in `pyproject.toml` dev deps** | Cassette-replay impossible |
| ES 9.4 + OpenSearch 2.18 containers running locally | Cassette recording (Stories 2.2–2.6) + integration tests | **Done — `infra_foundation` Compose** | Tests can't run |
| Mounted `cluster_credentials.yaml` | Story 2.1 + Story 4.1 | **`Settings.cluster_credentials_yaml` accessor exists; `install.sh` updated by Story 4.1** | Seed script fails |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cassette drift between recording and live cluster on minor version bumps | M | M | Cassettes use `_msearch` + `_cluster/health` shapes that have been stable across ES 8→9 / OpenSearch 2.x; if drift surfaces, re-record in CI's integration-test job and commit. |
| `httpx` connection pool leaking across requests | L | M | Each `ElasticAdapter` instance owns one client and is `aclose()`'d in service code (`try/finally`). Service unit tests assert close is called. |
| OpenSearch security plugin enabled with `auth_kind=opensearch_basic` failing at first request | M | L | Spec §11 already covers — adapter returns `ClusterUnreachableError` with the underlying 401 in the message. |
| `subsystems.elasticsearch_clusters` aggregation slow on many clusters | L (MVP1: ~2 clusters) | L | Read-from-Redis-only path; 200ms timeout wraps the gather; on miss we count as `unreachable`. |
| Spec §2 vs §7 `/healthz` gap blocks merge | M | L | Flag at cross-model review (§11 below); user resolves by either adding FR-8 or removing the §2 sentence. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Cluster TCP connect fails (port closed, host unreachable) | `register_cluster` POST against bad URL | `ClusterUnreachable` raised → 503 `CLUSTER_UNREACHABLE`; no DB row inserted (AC-6) | Operator fixes URL and retries POST |
| Cluster auth fails (wrong password) | `register_cluster` against a working cluster with wrong creds | `health_check` returns `unreachable` with HTTP 401 in `error`; same 503 path | Operator fixes mounted YAML credential entry |
| Cluster engine version below minimum | Register an ES 8.10 cluster | `health_check` returns `unreachable` with version-too-low message; row NOT inserted | Operator upgrades cluster to ≥ 8.11 |
| `_msearch` returns per-query error | Bad query DSL inside a multi-query batch | Per-query `ScoredHit` list is empty for that `query_id`; batch otherwise succeeds | Caller (Optuna trial runner, future) records the trial as failed |
| Run-query exceeds time budget | Slow / unindexed ES aggregation | `QueryTimeoutError` → 504 `QUERY_TIMEOUT` | Operator narrows query or raises `?timeout_s=` (max 30s) |
| Cluster credentials YAML missing | Feature installed without operator providing credentials | `register_cluster` raises `CredentialsMissing` → translated as 503 `CLUSTER_UNREACHABLE` with message "credentials_ref X not found in mounted YAML" | Operator populates YAML, restarts API |
| Redis cache loss mid-request | `read_cached_health` connection error | Treated as cache miss → fresh probe; on probe failure → unreachable | None needed — graceful degradation |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (Protocol → Models → Migration → Repo) — foundation. Must be sequential within itself: Story 1.1 → 1.2 → 1.3 → 1.4.
2. **Epic 2** (ElasticAdapter) — depends on Epic 1.1 (Protocol). Stories 2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.6 → 2.7.
3. **Epic 3** (API surface) — depends on Epic 2 fully. 3.1 → 3.2 → 3.3 → 3.4 → 3.5.
4. **Epic 4** (seed + docs) — depends on Epic 3.
5. **Epic 5** (audit + finalize) — last.

### Parallelization opportunities

- **Story 1.1 ↕ Story 1.2** — Protocol module is independent of ORM models; can be drafted in parallel by two contributors. Tests in 1.1 don't need 1.2; tests in 1.2 don't need 1.1.
- **Story 2.6 ↕ Story 2.7** — `explain` and the engine_branch test are both leaf nodes; can run in parallel.
- **Stories 3.3 ↕ 3.4** — schema and run_query endpoints are independent surface area on top of completed Epic 2.

For solo execution, sequential is fine — the parallelization notes are for multi-engineer teams.

## 8) Rollout and cutover plan

- **Rollout stages:** Single-shot. PR contains all 5 epics. Local-first MVP1 has no remote staging (per [`state.md`](../../../../state.md) "No remote staging in MVP1"); merge to `main` triggers no remote deploy.
- **Feature flag strategy:** None.
- **Migration/cutover:** First migration with business tables. New install → `make up` → `make migrate` → `make seed-clusters`. Existing dev installs (any contributor who pulled `main` after `infra_foundation`) → `make migrate` to advance from `0001` → `0002`.
- **Reconciliation:** N/A — no external systems written to during rollout (spec §16).

## 9) Execution tracker (copy/paste section)

### Current sprint
- [x] Story 1.1 — `SearchAdapter` Protocol + types (commit `6bf565b`, 2026-05-09)
- [x] Story 1.2 — ORM models for `clusters` + `config_repos` (commit `264b8d0`, 2026-05-09)
- [x] Story 1.3 — Alembic migration `0002` (commit `1b80290`, 2026-05-09)
- [x] Story 1.4 — Repo functions (commit `3d5f789`, 2026-05-09)
- [x] Epic 1 gate (passed 2026-05-09)
- [x] Story 2.1 — `ElasticAdapter` skeleton + version detection (commit `451d725`, 2026-05-09)
- [x] Story 2.2 — `health_check()` + 30s Redis cache (commit `ecb2895`, 2026-05-09)
- [x] Story 2.3 — `list_targets`, `get_schema`, `list_query_parsers` (commit `9251281`, 2026-05-09)
- [x] Story 2.4 — `render(template, params, query_text)` (commit `1cc17a4`, 2026-05-09)
- [x] Story 2.5 — `search_batch()` via `_msearch` (commit `abff542`, 2026-05-09)
- [x] Story 2.6 — `explain()` (commit `bfd6328`, 2026-05-09)
- [x] Story 2.7 — Engine-branch test (commit `bfd6328`, 2026-05-09)
- [x] Epic 2 gate (passed 2026-05-09)
- [x] Story 3.1 — Cluster service (commit `37ed558`, 2026-05-09)
- [x] Story 3.2 — Cluster CRUD router (commit `37ed558`, 2026-05-09)
- [x] Story 3.3 — Schema endpoint (commit `37ed558`, 2026-05-09)
- [x] Story 3.4 — Run-query endpoint (commit `37ed558`, 2026-05-09)
- [x] Story 3.5 — `/healthz` extension (commit `4c13b52`, 2026-05-09)
- [x] Epic 3 gate (passed 2026-05-09)
- [x] Story 4.1 — Seed command (commit `b157386`, 2026-05-09)
- [x] Story 4.2 — Docs + path patches (commit `31d8bae`, 2026-05-09)
- [x] Epic 4 gate (passed 2026-05-09)
- [x] Story 5.1 — Test coverage audit (commit `64e11aa`, 2026-05-09)
- [x] Story 5.2 — Finalization (this commit)
- [x] Epic 5 gate (passed 2026-05-09)

### Blocked items

- None at draft time.

### Done this sprint

- (track here as stories land)

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables).
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code).
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added/updated for all touching layers.
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration` (or targeted subset, with explanation)
    - [ ] `make test-contract`
    - [ ] N/A `cd web && npm run test:e2e:stable` (no UI in this feature)
- [ ] Migration round-trip evidence (Story 1.3 only).
- [ ] Related docs/checklists updated in same PR when behavior/contract changes.

## 11) Plan consistency review (required before execution)

### Review log

Findings raised during plan authorship + cross-model review — adjudicated against spec, codebase, and architecture docs.

#### Opus internal findings (raised during initial draft)

| # | Finding | Severity | Source | Disposition |
|---|---|---|---|---|
| O1 | Adapter directory: spec body + adapters.md say `backend/adapters/`; CLAUDE.md + project layout say `backend/app/adapters/`. | Medium | Opus internal | **Plan uses `backend/app/adapters/`** (matches CLAUDE.md + every other module under `backend/app/`). Story 4.2 patches `adapters.md` and the spec body. |
| O2 | Seed-script path: spec says `python -m backend.scripts.seed_clusters`; project uses `backend.app.<module>` everywhere (verified via `migrations/env.py`, Makefile `optuna_schema` target). | Low | Opus internal | **Plan uses `backend.app.scripts.seed_clusters`**. Story 4.2 patches the spec body. |
| O3 | Spec section numbering: §8 is titled "API and data contract baseline" but subsections are labeled 7.1–7.5. | Low | Opus internal | Story 4.2 renumbers 7.x → 8.x in the spec. |
| O4 | Spec §2 references a `/healthz` extension (`subsystems.elasticsearch_clusters`) but no FR backs it. | **Medium** | Opus internal | Plan implements per spec §2 text (Story 3.5) but **flags for cross-model review or user resolution**. Two options: (a) add FR-8 to the spec, (b) remove the §2 sentence and drop Story 3.5. |
| O5 | The spec's `health_check` 30s TTL Decision Log entry doesn't specify the cache backend. | Low | Opus internal | Plan uses Redis (already provisioned + already used by capability check). Documented in Story 2.2. |
| O6 | Spec §3 mentions `make seed-clusters` but the existing `Makefile` has no such target yet. | Low | Opus internal | Story 4.1 adds it. Tracked. |
| O7 | Spec §11 "edge flow: ES 8.10 below minimum" — registration says cluster IS registered "so the operator can see the row". This conflicts with FR-5 / AC-6 which says registration probe failure rejects with `CLUSTER_UNREACHABLE` and does NOT insert the row. | **Medium** | Opus internal | Plan follows FR-5 / AC-6 (reject on `unreachable` health, don't insert). Story 2.2's `_enforce_min_version` raises and `health_check` catches → returns `HealthStatus(status="unreachable", error="engine version 8.10 below minimum 8.11")`, the registration service sees `unreachable` and refuses to insert. **Recommend spec §11 be patched** to align (Story 4.2 candidate addition). |
| O8 | Spec FR-5 lists `DELETE /api/v1/clusters/{id}` as MAY (optional) but AC-8 requires the soft-delete behavior. | Low | Opus internal | Plan implements DELETE (Story 3.2) per AC-8. |

#### GPT-5.5 cross-model review — Cycle 1 findings (all accepted)

| # | Finding | Severity | Pass | Disposition |
|---|---|---|---|---|
| F1 | `SearchAdapter` Protocol declared sync but adapter / service code is async — type checking would fail. | High | B | **Accepted.** Protocol changed to `async def` for I/O methods (`health_check`, `list_targets`, `get_schema`, `search_batch`, `explain`); pure methods (`render`, `list_query_parsers`) stay sync. Test asserts `inspect.iscoroutinefunction`. Story 4.2 patches `adapters.md` to match. |
| F2 | Pydantic `Literal[...]` on `engine_type` / `auth_kind` produces 422 `VALIDATION_ERROR` instead of the spec-required 400 `ENGINE_NOT_SUPPORTED` / `AUTH_KIND_NOT_SUPPORTED`. | High | A | **Accepted.** `CreateClusterRequest` accepts `str` for these three fields; service-layer validates against `SUPPORTED_*` frozensets and raises domain exceptions translated to the spec's error codes. |
| F3 | `_enforce_min_version` raises `ValueError`; `health_check`'s `except` clause only catches httpx exceptions — version mismatch escapes as 500 instead of mapping to `CLUSTER_UNREACHABLE`. | High | B | **Accepted.** `health_check` now catches `ValueError` and returns `HealthStatus(status="unreachable", error=...)`. Test verifies no exception escapes for ES 8.10. |
| F4 | `(Cluster.created_at, Cluster.id) < (cursor_at, cursor_id)` is Python tuple comparison, not SQL — won't generate the right predicate. | High | B | **Accepted.** Replaced with explicit `or_(Cluster.created_at < cursor_at, and_(Cluster.created_at == cursor_at, Cluster.id < cursor_id))` — portable across PG/SQLite, clearer in EXPLAIN, no risk of SQLAlchemy version coupling. |
| F5 | DB `name UNIQUE` constraint conflicts with spec §10's "operator can DELETE and resurrect by re-registering" — re-registration would hit unique-violation. | High | A | **Accepted.** Repo gains `get_any_cluster_by_name` + `revive_cluster`; service detects soft-deleted same-named row and revives instead of inserting. Integration test added. |
| F6 | `_field_caps` does not return analyzer info on either ES or OpenSearch; AC-2 expecting `analyzer: "standard"` would fail. | High | B | **Accepted.** Removed `_field_caps` analyzer derivation. New `_resolve_default_analyzer` reads index settings; for `text` fields with no explicit analyzer, defaults to the index's default analyzer (or `"standard"`). Test asserts `_field_caps` is NOT called by `get_schema`. |
| F7 | `dispatch_run_query` wraps `search_batch` in `asyncio.wait_for` but `search_batch` doesn't pass `timeout` to httpx — adapter's default 10s pre-empts a 30s operator budget. | High | B | **Accepted.** `search_batch` gains a `timeout: float \| None` kwarg threaded into `httpx.Timeout(timeout)`; `dispatch_run_query` passes `timeout_s` and uses `asyncio.wait_for` only as outer wall-clock guard with +1s slack. |
| F8 | `ElasticAdapter.__init__` resolves credentials eagerly; `CredentialsMissing` escapes before `register_cluster`'s try/finally — surfaces as 500 not the documented `CLUSTER_UNREACHABLE`. | High | B | **Accepted.** `register_cluster` wraps adapter construction in `try/except CredentialsMissing` and translates to `ClusterUnreachable`. `get_or_probe_health` does the same. Integration test covers the missing-YAML path. |
| F9 | Stories 2.5 + 3.4 disagree on `_msearch` per-query error handling — empty list vs raise `InvalidQueryDSLError`. | Medium | A | **Accepted.** `search_batch` gains `strict_errors: bool = False` kwarg. Default (False) yields empty list per query (hot-path / Optuna trial runner); `True` (run_query API) raises `InvalidQueryDSLError` on parse errors and `ClusterUnreachableError` on others. Both behaviors covered by Story 2.5 tests. |
| F10 | `validate_url_scheme` only checks scheme; spec §10 Threat 3 also requires private-IP rejection unless `RELYLOOP_ALLOW_PRIVATE_CLUSTERS=true`. | Medium | A | **Accepted.** Renamed `validate_base_url`; parses URL, checks scheme + host; rejects private/loopback IPs when the new `relyloop_allow_private_clusters` setting is False. Setting added to `Settings` (default True for MVP1 per spec). Integration tests cover both paths. |

#### GPT-5.5 cross-model review — Cycle 2 findings (all accepted)

| # | Finding | Severity | Pass | Disposition |
|---|---|---|---|---|
| C2-F1 | Bare `ValueError` raised by service for invalid `environment` is not translated by router → 500 instead of a documented client error. | High | A | **Accepted.** `environment` switched to `Literal["prod", "staging", "dev"]` in `CreateClusterRequest` so Pydantic produces 422 `VALIDATION_ERROR` (consistent with spec §8.5, which has no `ENVIRONMENT_NOT_SUPPORTED` code). Service-side `ValueError` removed; `engine_type` and `auth_kind` retain the `str` + service-level path because they DO have spec-defined domain codes. |
| C2-F2 | `SearchAdapter` Protocol missing the `timeout` kwarg added by cycle 1 F7. | High | B | **Accepted.** `timeout: float \| None = None` added to Protocol `search_batch`; Story 4.2 `adapters.md` patch will include it. |
| C2-F3 | `get_schema` and other adapter methods don't normalize raw httpx errors / non-404 4xx → could surface as generic 500 in the router. | High | B | **Accepted.** Centralized error normalization in `_request`: connection-class failures and 401/403/5xx now raise `ClusterUnreachableError` automatically. `get_schema` adds 404 → `TargetNotFoundError` and other 4xx → `ClusterUnreachableError`. `health_check` opts out of translation (`translate_errors=False`) since it owns its own status mapping. |
| C2-F4 | Spec §13 reliability requirement (one retry on `ConnectionError`) was missing entirely. | High | B | **Accepted.** `_request` implements exactly-one retry on `ConnectError`, `RemoteProtocolError`, `ConnectTimeout`, `ReadTimeout`. New unit test `test_request_retry.py` uses `httpx.MockTransport` to verify: success-after-one-fail returns OK; two failures propagate; success path makes one HTTP call. |
| C2-F5 | Stale `_field_caps` references in Story 2.3 DoD and Epic 2 gate after cycle 1 F6 fix. | Medium | B | **Accepted.** All `_field_caps` mentions scrubbed; cassette inventory now lists `_mapping` + `_settings`. The Story 2.3 test explicitly asserts `_field_caps` is NOT called. |
| C2-F6 | `TargetNotFoundError` defined inline in Story 2.3 code block AND moved to `errors.py` in Story 2.5 — ambiguous import path. | Medium | B | **Accepted.** `errors.py` creation moved to Story 2.3 (where `TargetNotFoundError` first appears) with `ClusterUnreachableError`; Story 2.5 only extends with `InvalidQueryDSLError` + `QueryTimeoutError`. Single import path for routers and the adapter. |

#### GPT-5.5 cross-model review — Cycle 3 findings (3 regressions from incomplete cycle 2 application; all accepted)

| # | Finding | Severity | Pass | Disposition |
|---|---|---|---|---|
| C3-F1 | Cycle 2 moved `errors.py` creation to Story 2.3, but Story 2.1 `_request` already imports `ClusterUnreachableError` from it → execution order broken. | High | A | **Accepted.** `errors.py` moved BACK to Story 2.1 (now created with `ClusterUnreachableError`); Story 2.3 extends with `TargetNotFoundError`; Story 2.5 extends with `InvalidQueryDSLError` + `QueryTimeoutError`. Module exists from the first story that needs it. |
| C3-F2 | Cycle 2's centralized retry / error normalization in `_request` was never applied to `search_batch` (the hot path) — it called `httpx.AsyncClient.post` directly, bypassing both the spec §13 retry and the 401/403 → ClusterUnreachableError translation. | High | B | **Accepted.** `_request` extended to accept `content=` (raw NDJSON), `extra_headers=`, and `translate_errors=`; `search_batch` refactored to use it. Hot path now gets the one-retry behavior + 401/403/5xx translation; top-level 400 separately mapped (strict=True → `InvalidQueryDSLError`; hot-path → `ClusterUnreachableError` for graceful degradation). |
| C3-F3 | Story 3.2 Task 1 text said "engine_type / environment / auth_kind are typed as str", contradicting the corrected schema where `environment: Literal[...]`. An implementer following the task text would reintroduce the C2-F1 regression. | Medium | A | **Accepted.** Task 1 rewritten to call out the deliberate split: `engine_type` + `auth_kind` are `str`; `environment` is `Literal[...]`. Explicit "Do NOT change this back to `str`" warning added. |

#### Convergence note

Cycle 3 raised 3 findings, all of which were regressions introduced by incomplete application of cycle 2 fixes (rather than new analytical disagreements). All three were applied without a fourth cycle: the spec §11 stop rule treats the 3-cycle limit as a safety net for runaway disputes; here the path forward is mechanical and the corrections close the loops they opened. The plan is execution-ready as of these edits, contingent only on the §11 Finding O4 user resolution (whether spec §2's `/healthz` extension gets an FR or is dropped).

Verification ledger (claims-vs-reality, sampled):

| Claim | Verified by | Status |
|---|---|---|
| Migration dir is `migrations/versions/` | `ls migrations/versions/` → only `0001_baseline.py` | Verified |
| Current Alembic head is `0001` | Read `migrations/versions/0001_baseline.py` line 27 (`revision: str = "0001"`) | Verified |
| `Base` lives at `backend/app/db/base.py` | Read file | Verified |
| `Settings.cluster_credentials_yaml` already exists | Read `backend/app/core/settings.py` lines 95–99, 162–169 | Verified |
| `pytest-recording` already in dev deps | Read `pyproject.toml` line 49 | Verified |
| `httpx>=0.28` already in deps | Read `pyproject.toml` line 33 | Verified |
| FastAPI router registration pattern | Read `backend/app/main.py` line 98 | Verified — `app.include_router(health.router)` |
| Error envelope shape | Read `backend/app/api/errors.py` lines 88–91 | Verified — `{"error_code", "message", "retryable"}` passed through if dict |
| `redis.asyncio.Redis` already imported in main lifespan | Read `backend/app/main.py` line 25, 60–62 | Verified |
| ES + OpenSearch container hostnames | Read `backend/app/api/health.py` lines 217–218 | Verified — `http://elasticsearch:9200`, `http://opensearch:9200` |
| ES image is 9.4 + OpenSearch is 2.18 | `grep elasticsearch:|opensearchproject docker-compose.yml` | Verified |

### Cross-reference checks

1. **Spec ↔ plan endpoint count.** Spec §7.1 lists 6 endpoints (`POST /clusters`, `GET /clusters`, `GET /clusters/{id}`, `DELETE /clusters/{id}`, `GET /clusters/{id}/schema`, `POST /clusters/{id}/run_query`). Plan covers all six in Stories 3.2/3.3/3.4. ✓
2. **Spec ↔ plan error code coverage.** Spec §7.5 has 8 codes (`ENGINE_NOT_SUPPORTED`, `AUTH_KIND_NOT_SUPPORTED`, `CLUSTER_NAME_TAKEN`, `CLUSTER_NOT_FOUND`, `TARGET_NOT_FOUND`, `CLUSTER_UNREACHABLE`, `INVALID_QUERY_DSL`, `QUERY_TIMEOUT`). Plan endpoint tables cover all 8. Story 5.1 contract test asserts each. ✓
3. **Spec ↔ plan FR coverage.** All 7 FRs traced in §1 above. ✓
4. **Test file count** — 8 from spec §14 (test_protocol, test_elastic_render, test_elastic_engine_branch, test_auth_kinds, test_elastic_msearch, test_elastic_schema, test_clusters_api, test_seed_clusters_idempotent, test_clusters_api_contract, test_error_codes). Plan §3 inventory adds 4 supporting (test_credentials, test_health_cache, test_render, test_dispatch_run_query, test_clusters_migration, test_cluster_repo, test_elastic_health, test_elastic_explain, test_cluster_service). ✓
5. **Gate arithmetic** — Epic 1 covers 4 stories; Epic 2 covers 7 stories; Epic 3 covers 5 stories; Epic 4 covers 2; Epic 5 covers 2. Total: 20 stories. Tracker matches. ✓
6. **Open questions resolved.** Spec §19 has zero open questions. ✓
7. **Frontend UI Guidance section** — N/A; this feature has no UI.
8. **Enumerated value contract verification** — Spec §7.4 lists `engine_type`, `auth_kind`, `environment`, `health_check.status`. Plan Pydantic schemas in Story 3.2 reflect all four allowlists with `Literal[...]` matching backend ORM CHECK constraints (Story 1.2). No frontend in this feature. ✓
9. **Audit-event coverage** — N/A in MVP1 per spec §6 ("No audit-events subsystem yet"); CLAUDE.md "Activates at MVP2". ✓
10. **Admin/ceiling audit** — N/A in MVP1 (no admin model).

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (where API-facing), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract; e2e N/A) explicitly scoped.
- [x] Documentation updates planned and owned.
- [x] Lean refactor scope is bounded.
- [x] Phase/epic gates are measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Cross-model review (GPT-5.5) — 3 cycles complete: cycle 1 (10 findings), cycle 2 (6 findings), cycle 3 (3 regression fixes). All 19 findings accepted and applied. See §11 Review log.
- [ ] User resolution on §11 Finding O4 (`/healthz` spec gap — Story 3.5 implements per spec §2 text but no FR backs it; either add FR-8 or drop Story 3.5).
