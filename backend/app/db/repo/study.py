"""Study repository (feat_study_lifecycle Phase 1 Story 1.3 + Phase 2 Story 1.4).

Phase 1 shipped create + get. Phase 2 extends with cursor-paginated list +
status filtering + ``?since=`` filter + count for the X-Total-Count header
+ a running-study-ids helper used by the orchestrator's resume-on-startup
sweep (FR-5).

Cursor pagination matches the ``backend.app.db.repo.cluster`` precedent:
``(created_at, id)`` ordering DESC with row-value comparison hand-rolled
for portability across Postgres / SQLite.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Study
from backend.app.db.repo._fts import fts_predicate
from backend.app.db.repo._sort import (
    ParsedSort,
    keyset_predicate,
    order_by_clauses,
    parse_sort,
)

# Allowlist for ``?sort=<col>:<dir>`` on ``/api/v1/studies``. Keys mirror
# ``StudySortKey`` Literal in ``backend.app.api.v1.schemas``.
_STUDY_SORT_COLUMNS: dict[str, object] = {
    "name": Study.name,
    "created_at": Study.created_at,
    "completed_at": Study.completed_at,
    "best_metric": Study.best_metric,
    "status": Study.status,
}

# Wire values for `?status=` filter on `GET /api/v1/studies`.
# Must match backend/app/db/models/study.py CHECK constraint + the
# StudyStatusWire Literal in backend/app/api/v1/schemas.py.
StudyStatusFilter = Literal["queued", "running", "completed", "cancelled", "failed"]


async def create_study(db: AsyncSession, **fields: object) -> Study:
    """Stage a new ``Study`` row. Caller commits.

    The study row is created via this repo function in tests; production
    creation goes through ``backend/services/study_state.py`` for
    status-mutating operations (Phase 2 FR-7).
    """
    study = Study(**fields)
    db.add(study)
    await db.flush()
    await db.refresh(study)
    return study


async def get_study(db: AsyncSession, study_id: str) -> Study | None:
    """Fetch a study by id."""
    stmt = select(Study).where(Study.id == study_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_studies(
    db: AsyncSession,
    *,
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
    cluster_id: str | None = None,
    q: str | None = None,
    sort: str | None = None,
) -> Sequence[Study]:
    """Cursor-paginated study list.

    Default ordering: ``created_at DESC, id DESC``. When ``sort`` is non-default
    (e.g. ``name:asc``, ``best_metric:desc``), the ORDER BY + keyset cursor
    predicate are switched accordingly with explicit NULLS handling and
    ``id DESC`` tie-breaker.

    ``since`` filters to ``created_at >= since``. ``status`` filters to a
    single state. ``cluster_id`` scopes to studies belonging to a single
    cluster (used by the cluster detail page's "Studies using this cluster"
    section). ``q`` is an optional Postgres FTS match against
    ``search_vector`` (studies.name + target). Limit clamped at 200.
    """
    parsed_sort: ParsedSort | None = parse_sort(sort, _STUDY_SORT_COLUMNS)
    stmt = select(Study)
    if status is not None:
        stmt = stmt.where(Study.status == status)
    if since is not None:
        stmt = stmt.where(Study.created_at >= since)
    if cluster_id is not None:
        stmt = stmt.where(Study.cluster_id == cluster_id)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    if cursor is not None:
        cursor_value, cursor_id = cursor
        stmt = stmt.where(
            keyset_predicate(
                parsed_sort,
                cursor_value,
                cursor_id,
                default_col=Study.created_at,
                id_col=Study.id,
            )
        )
    stmt = stmt.order_by(
        *order_by_clauses(parsed_sort, default_col=Study.created_at, id_col=Study.id)
    ).limit(min(limit, 200))
    return list((await db.execute(stmt)).scalars().all())


async def count_studies(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
    cluster_id: str | None = None,
    q: str | None = None,
) -> int:
    """COUNT(*) studies matching the filter (for the X-Total-Count header)."""
    stmt = select(func.count(Study.id))
    if status is not None:
        stmt = stmt.where(Study.status == status)
    if since is not None:
        stmt = stmt.where(Study.created_at >= since)
    if cluster_id is not None:
        stmt = stmt.where(Study.cluster_id == cluster_id)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    return int((await db.execute(stmt)).scalar_one())


async def list_running_study_ids(db: AsyncSession) -> list[str]:
    """Return ids of every study currently in ``status='running'``.

    Consumed by the worker's ``on_startup`` resume sweep (Story 2.3 / FR-5):
    after a worker restart, every running study gets a fresh
    ``resume_study`` Arq job enqueued so the orchestrator loop re-enters.
    """
    stmt = select(Study.id).where(Study.status == "running")
    return list((await db.execute(stmt)).scalars().all())


async def list_queued_study_ids(db: AsyncSession) -> list[str]:
    """Return ids of every study currently in ``status='queued'``.

    Consumed by the worker's ``on_startup`` sweep to pick up studies whose
    ``POST /studies`` enqueue was lost (e.g., the API committed the row
    but the Arq pool was unreachable at the time). Without this, a study
    that the API failed to enqueue would sit at ``queued`` forever — the
    ``running``-only sweep wouldn't re-dispatch it.
    """
    stmt = select(Study.id).where(Study.status == "queued")
    return list((await db.execute(stmt)).scalars().all())
