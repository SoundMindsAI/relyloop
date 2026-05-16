"""Cluster repository (infra_adapter_elastic Story 1.4).

CRUD + soft-delete + cursor-pagination helpers for the ``clusters`` table.
All functions accept ``db: AsyncSession`` and use ``db.flush()`` only — the
caller commits per CLAUDE.md "Repository Layer" convention.

The pagination cursor is ``(created_at, id)``; the ordering is
``created_at DESC, id DESC``. We hand-roll the row-value comparison instead
of using SQLAlchemy ``tuple_(...)`` so the predicate is portable across
Postgres/SQLite and clearer in EXPLAIN output.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Cluster
from backend.app.db.repo._fts import fts_predicate


async def create_cluster(db: AsyncSession, **fields: object) -> Cluster:
    """Stage a new ``Cluster`` row. Caller commits."""
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
    q: str | None = None,
) -> Sequence[Cluster]:
    """Cursor-paginated active list, newest first.

    Excludes soft-deleted rows. ``cursor=(created_at, id)`` returns rows
    strictly older than the cursor; ``since`` filters to rows created at
    or after a wall-clock timestamp. ``q`` is an optional Postgres FTS
    match against ``search_vector`` (clusters.name + base_url); ordering
    is unchanged (filter-only FTS per spec FR-1). ``limit`` is clamped to
    200 per api-conventions.md §"Pagination".
    """
    stmt = select(Cluster).where(Cluster.deleted_at.is_(None))
    if since is not None:
        stmt = stmt.where(Cluster.created_at >= since)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
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


async def count_clusters(
    db: AsyncSession, *, since: datetime | None = None, q: str | None = None
) -> int:
    """Count active (non-soft-deleted) cluster rows for the ``X-Total-Count`` header."""
    stmt = select(func.count(Cluster.id)).where(Cluster.deleted_at.is_(None))
    if since is not None:
        stmt = stmt.where(Cluster.created_at >= since)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def get_cluster(db: AsyncSession, cluster_id: str) -> Cluster | None:
    """Fetch an active cluster by id; returns ``None`` for not-found OR soft-deleted."""
    stmt = select(Cluster).where(Cluster.id == cluster_id, Cluster.deleted_at.is_(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_active_cluster_by_name(db: AsyncSession, name: str) -> Cluster | None:
    """Fetch the active cluster with this unique ``name``."""
    stmt = select(Cluster).where(Cluster.name == name, Cluster.deleted_at.is_(None))
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_any_cluster_by_name(db: AsyncSession, name: str) -> Cluster | None:
    """Fetch a cluster by name regardless of ``deleted_at``.

    Used by the registration service to detect a soft-deleted same-named row
    that should be revived rather than re-inserted (the underlying
    ``clusters.name UNIQUE`` constraint applies to all rows; a new INSERT
    would otherwise hit a unique-violation).
    """
    stmt = select(Cluster).where(Cluster.name == name)
    return (await db.execute(stmt)).scalar_one_or_none()


async def revive_cluster(db: AsyncSession, cluster: Cluster, **updates: object) -> Cluster:
    """Clear ``deleted_at`` and apply field updates to a soft-deleted row.

    Used by ``register_cluster`` when an operator re-registers a previously
    soft-deleted name (per spec §10 Data retention).
    """
    cluster.deleted_at = None
    for key, value in updates.items():
        setattr(cluster, key, value)
    await db.flush()
    await db.refresh(cluster)
    return cluster


async def soft_delete_cluster(db: AsyncSession, cluster_id: str) -> Cluster | None:
    """Set ``deleted_at`` on an active cluster; returns the row or ``None`` if absent."""
    cluster = await get_cluster(db, cluster_id)
    if cluster is None:
        return None
    cluster.deleted_at = datetime.now(UTC)
    await db.flush()
    return cluster
