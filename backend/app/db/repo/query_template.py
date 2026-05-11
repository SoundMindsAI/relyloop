"""Query-template repository (Phase 1 Story 1.3 + Phase 2 Story 1.4).

Phase 1 shipped create + get + get-by-name-version. Phase 2 adds
cursor-paginated list + count for the X-Total-Count header.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import QueryTemplate


async def create_query_template(db: AsyncSession, **fields: object) -> QueryTemplate:
    """Stage a new ``QueryTemplate`` row. Caller commits."""
    template = QueryTemplate(**fields)
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


async def get_query_template(db: AsyncSession, template_id: str) -> QueryTemplate | None:
    """Fetch a query template by id."""
    stmt = select(QueryTemplate).where(QueryTemplate.id == template_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_query_template_by_name_version(
    db: AsyncSession, name: str, version: int
) -> QueryTemplate | None:
    """Fetch a query template by the composite UNIQUE ``(name, version)``."""
    stmt = select(QueryTemplate).where(QueryTemplate.name == name, QueryTemplate.version == version)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_query_templates(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
) -> Sequence[QueryTemplate]:
    """Cursor-paginated list, newest first. Mirror of repo.cluster.list_clusters."""
    stmt = select(QueryTemplate)
    if since is not None:
        stmt = stmt.where(QueryTemplate.created_at >= since)
    if cursor is not None:
        cursor_at, cursor_id = cursor
        stmt = stmt.where(
            or_(
                QueryTemplate.created_at < cursor_at,
                and_(QueryTemplate.created_at == cursor_at, QueryTemplate.id < cursor_id),
            )
        )
    stmt = stmt.order_by(QueryTemplate.created_at.desc(), QueryTemplate.id.desc()).limit(
        min(limit, 200)
    )
    return list((await db.execute(stmt)).scalars().all())


async def count_query_templates(
    db: AsyncSession,
    *,
    since: datetime | None = None,
) -> int:
    """COUNT(*) templates for the X-Total-Count header."""
    stmt = select(func.count(QueryTemplate.id))
    if since is not None:
        stmt = stmt.where(QueryTemplate.created_at >= since)
    return int((await db.execute(stmt)).scalar_one())
