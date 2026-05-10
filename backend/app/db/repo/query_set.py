"""Query-set repository (feat_study_lifecycle Phase 1, Story 1.3).

Phase 1 ships create + get; Phase 2 extends with cursor-paginated list +
``POST /query-sets`` create flow + bulk CSV upload.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import QuerySet


async def create_query_set(db: AsyncSession, **fields: object) -> QuerySet:
    """Stage a new ``QuerySet`` row. Caller commits."""
    query_set = QuerySet(**fields)
    db.add(query_set)
    await db.flush()
    await db.refresh(query_set)
    return query_set


async def get_query_set(db: AsyncSession, query_set_id: str) -> QuerySet | None:
    """Fetch a query set by id."""
    stmt = select(QuerySet).where(QuerySet.id == query_set_id)
    return (await db.execute(stmt)).scalar_one_or_none()
