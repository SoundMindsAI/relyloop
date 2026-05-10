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

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Study

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
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
) -> Sequence[Study]:
    """Cursor-paginated study list, newest first.

    Order: ``created_at DESC, id DESC``. ``cursor=(created_at, id)``
    returns rows strictly older than the cursor; ``since`` filters to
    rows created at or after a wall-clock timestamp; ``status`` filters
    to a single state. Limit clamped at 200 per api-conventions.md.
    """
    stmt = select(Study)
    if status is not None:
        stmt = stmt.where(Study.status == status)
    if since is not None:
        stmt = stmt.where(Study.created_at >= since)
    if cursor is not None:
        cursor_at, cursor_id = cursor
        stmt = stmt.where(
            or_(
                Study.created_at < cursor_at,
                and_(Study.created_at == cursor_at, Study.id < cursor_id),
            )
        )
    stmt = stmt.order_by(Study.created_at.desc(), Study.id.desc()).limit(min(limit, 200))
    return list((await db.execute(stmt)).scalars().all())


async def count_studies(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
) -> int:
    """COUNT(*) studies matching the filter (for the X-Total-Count header)."""
    stmt = select(func.count(Study.id))
    if status is not None:
        stmt = stmt.where(Study.status == status)
    if since is not None:
        stmt = stmt.where(Study.created_at >= since)
    return int((await db.execute(stmt)).scalar_one())


async def list_running_study_ids(db: AsyncSession) -> list[str]:
    """Return ids of every study currently in ``status='running'``.

    Consumed by the worker's ``on_startup`` resume sweep (Story 2.3 / FR-5):
    after a worker restart, every running study gets a fresh
    ``resume_study`` Arq job enqueued so the orchestrator loop re-enters.
    """
    stmt = select(Study.id).where(Study.status == "running")
    return list((await db.execute(stmt)).scalars().all())
