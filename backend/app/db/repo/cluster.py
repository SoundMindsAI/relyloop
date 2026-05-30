# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Cluster
from backend.app.db.repo._fts import fts_predicate
from backend.app.db.repo._sort import (
    ParsedSort,
    keyset_predicate,
    order_by_clauses,
    parse_sort,
)

# Allowlist for ``?sort=<col>:<dir>`` on ``/api/v1/clusters``. Keys mirror the
# ``ClusterSortKey`` Literal in ``backend.app.api.v1.schemas``.
_CLUSTER_SORT_COLUMNS: dict[str, object] = {
    "name": Cluster.name,
    "created_at": Cluster.created_at,
    "environment": Cluster.environment,
}


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
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
    sort: str | None = None,
    engine_type: str | None = None,
    environment: str | None = None,
) -> Sequence[Cluster]:
    """Cursor-paginated active list.

    Default ordering: ``created_at DESC, id DESC``. When ``sort`` is non-default
    (e.g. ``name:asc``), the ORDER BY + keyset cursor predicate are switched
    to the requested column with explicit NULLS handling and ``id DESC``
    tie-breaker (see ``backend/app/db/repo/_sort.py``).

    ``since`` filters to ``created_at >= since``. ``q`` is an optional
    Postgres FTS match against ``search_vector`` (clusters.name + base_url).
    Excludes soft-deleted rows. ``limit`` clamped to 200.
    """
    parsed_sort: ParsedSort | None = parse_sort(sort, _CLUSTER_SORT_COLUMNS)
    stmt = select(Cluster).where(Cluster.deleted_at.is_(None))
    if since is not None:
        stmt = stmt.where(Cluster.created_at >= since)
    if engine_type is not None:
        stmt = stmt.where(Cluster.engine_type == engine_type)
    if environment is not None:
        stmt = stmt.where(Cluster.environment == environment)
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
                default_col=Cluster.created_at,
                id_col=Cluster.id,
            )
        )
    stmt = stmt.order_by(
        *order_by_clauses(parsed_sort, default_col=Cluster.created_at, id_col=Cluster.id)
    ).limit(min(limit, 200))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_clusters(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    q: str | None = None,
    engine_type: str | None = None,
    environment: str | None = None,
) -> int:
    """Count active (non-soft-deleted) cluster rows for the ``X-Total-Count`` header.

    ``sort`` is intentionally NOT an argument — sort doesn't affect count.
    """
    stmt = select(func.count(Cluster.id)).where(Cluster.deleted_at.is_(None))
    if since is not None:
        stmt = stmt.where(Cluster.created_at >= since)
    if engine_type is not None:
        stmt = stmt.where(Cluster.engine_type == engine_type)
    if environment is not None:
        stmt = stmt.where(Cluster.environment == environment)
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


async def get_cluster_by_id_for_update(db: AsyncSession, cluster_id: str) -> Cluster | None:
    """Fetch an active cluster with ``SELECT … FOR UPDATE`` row-lock.

    Used by ``services.cluster.reprobe_cluster`` (infra_adapter_solr Story A9)
    to serialize concurrent /reprobe calls — the second call blocks on the
    row lock until the first commits, then re-reads the (now updated)
    engine_config before running its own probe.
    """
    stmt = (
        select(Cluster)
        .where(Cluster.id == cluster_id, Cluster.deleted_at.is_(None))
        .with_for_update()
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_cluster_engine_config(
    db: AsyncSession,
    cluster_id: str,
    *,
    engine_config: dict[str, object] | None,
) -> Cluster | None:
    """Update ``clusters.engine_config`` for ``cluster_id``; caller commits.

    Used by ``services.cluster.reprobe_cluster`` (Story A9) to persist the
    refreshed capability probe. Returns the updated row or ``None`` if the
    row was already deleted/missing.
    """
    cluster = await get_cluster(db, cluster_id)
    if cluster is None:
        return None
    cluster.engine_config = engine_config
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
