# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Query-set repository (Phase 1 Story 1.3 + Phase 2 Story 1.4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Query, QuerySet
from backend.app.db.repo._fts import (
    fts_predicate,
    rank_active,
    rank_bucket_expr,
    rows_with_rank,
)
from backend.app.db.repo._sort import (
    ParsedSort,
    keyset_predicate,
    order_by_clauses,
    parse_sort,
)

_QUERY_SET_SORT_COLUMNS: dict[str, object] = {
    "name": QuerySet.name,
    "created_at": QuerySet.created_at,
}


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
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
    sort: str | None = None,
) -> Sequence[QuerySet]:
    """Cursor-paginated list. Sort-aware cursor per Story 1.3.

    ``q`` is an optional Postgres FTS match against ``search_vector``
    (query_sets.name). Default ordering ``created_at DESC, id DESC`` is
    preserved when ``sort`` is None.
    """
    parsed_sort: ParsedSort | None = parse_sort(sort, _QUERY_SET_SORT_COLUMNS)
    # feat_fts_rank_ordering: relevance ordering when ?q= present and no ?sort=.
    is_rank = rank_active(q, parsed_sort)
    stmt: Select[Any]
    if is_rank and q is not None:  # q is non-None whenever is_rank is True
        rank_col = rank_bucket_expr(q)
        stmt = select(QuerySet, rank_col.label("rb"))
        order_col: Any = rank_col
        keyset_parsed: ParsedSort | None = None
    else:
        stmt = select(QuerySet)
        order_col = QuerySet.created_at
        keyset_parsed = parsed_sort
    if since is not None:
        stmt = stmt.where(QuerySet.created_at >= since)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    if cursor is not None:
        cursor_value, cursor_id = cursor
        stmt = stmt.where(
            keyset_predicate(
                keyset_parsed,
                cursor_value,
                cursor_id,
                default_col=order_col,
                id_col=QuerySet.id,
            )
        )
    stmt = stmt.order_by(
        *order_by_clauses(keyset_parsed, default_col=order_col, id_col=QuerySet.id)
    ).limit(min(limit, 200))
    result = await db.execute(stmt)
    if is_rank:
        return rows_with_rank(result)
    return list(result.scalars().all())


async def count_query_sets(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    q: str | None = None,
) -> int:
    """COUNT(*) query sets for the X-Total-Count header."""
    stmt = select(func.count(QuerySet.id))
    if since is not None:
        stmt = stmt.where(QuerySet.created_at >= since)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    return int((await db.execute(stmt)).scalar_one())


async def count_queries_in_set(db: AsyncSession, query_set_id: str) -> int:
    """COUNT(*) queries in a set (used by ``GET /query-sets/{id}.query_count``)."""
    stmt = select(func.count(Query.id)).where(Query.query_set_id == query_set_id)
    return int((await db.execute(stmt)).scalar_one())


async def count_queries_for_sets(db: AsyncSession, query_set_ids: Sequence[str]) -> dict[str, int]:
    """Batched query counts for a page of query sets.

    One ``GROUP BY query_set_id`` aggregate returning the COUNT(*) of
    queries per set. Powers the query-sets-list ``query_count`` field
    without a per-row count (the no-N+1 pattern mirroring
    ``repo.count_trials_for_studies`` from
    ``feat_studies_convergence_visibility``).

    Sets whose id is in the input but have zero queries are returned
    with ``0`` (backfilled) so callers can index by id without a
    ``KeyError``. Empty input returns an empty dict (no query issued).
    """
    if not query_set_ids:
        return {}
    # Label the aggregate ``query_count`` (NOT ``count``): SQLAlchemy
    # ``Row`` objects are tuple-like and expose a built-in ``.count()``
    # method, so ``row.count`` would resolve to that bound method, not
    # the labeled column. ``query_count`` has no such collision.
    stmt = (
        select(
            Query.query_set_id.label("query_set_id"),
            func.count(Query.id).label("query_count"),
        )
        .where(Query.query_set_id.in_(list(query_set_ids)))
        .group_by(Query.query_set_id)
    )
    rows = (await db.execute(stmt)).all()
    result: dict[str, int] = {row.query_set_id: int(row.query_count) for row in rows}
    for qsid in query_set_ids:
        result.setdefault(qsid, 0)
    return result


# ---------------------------------------------------------------------------
# chore_e2e_test_rows_isolation Story 1.1 — hard-delete for test-only cleanup
# ---------------------------------------------------------------------------


async def hard_delete_query_set(db: AsyncSession, query_set_id: str) -> bool:
    """Hard-delete the query_set row for test-only cleanup.

    Queries cascade-delete via the existing ``ondelete='CASCADE'`` FK
    at ``backend/app/db/models/query.py:32``.

    Returns ``True`` if a row was deleted, ``False`` if no row existed.
    Caller commits. Used ONLY by the test-only `DELETE /api/v1/_test/
    query-sets/{id}` endpoint per ``chore_e2e_test_rows_isolation`` FR-5.
    The handler is responsible for preflight EXISTS checks against
    ``studies`` and ``judgment_lists`` (both non-cascade) and emitting 409
    with the resource-specific code if either references the query_set.
    """
    existing = await db.get(QuerySet, query_set_id)
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True
