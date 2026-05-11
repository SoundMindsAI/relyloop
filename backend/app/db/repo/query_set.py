"""Query-set repository (Phase 1 Story 1.3 + Phase 2 Story 1.4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Query, QuerySet


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


async def list_query_sets(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
) -> Sequence[QuerySet]:
    """Cursor-paginated list, newest first."""
    stmt = select(QuerySet)
    if since is not None:
        stmt = stmt.where(QuerySet.created_at >= since)
    if cursor is not None:
        cursor_at, cursor_id = cursor
        stmt = stmt.where(
            or_(
                QuerySet.created_at < cursor_at,
                and_(QuerySet.created_at == cursor_at, QuerySet.id < cursor_id),
            )
        )
    stmt = stmt.order_by(QuerySet.created_at.desc(), QuerySet.id.desc()).limit(min(limit, 200))
    return list((await db.execute(stmt)).scalars().all())


async def count_query_sets(
    db: AsyncSession,
    *,
    since: datetime | None = None,
) -> int:
    """COUNT(*) query sets for the X-Total-Count header."""
    stmt = select(func.count(QuerySet.id))
    if since is not None:
        stmt = stmt.where(QuerySet.created_at >= since)
    return int((await db.execute(stmt)).scalar_one())


async def count_queries_in_set(db: AsyncSession, query_set_id: str) -> int:
    """COUNT(*) queries in a set (used by ``GET /query-sets/{id}.query_count``)."""
    stmt = select(func.count(Query.id)).where(Query.query_set_id == query_set_id)
    return int((await db.execute(stmt)).scalar_one())
