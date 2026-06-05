# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Query-template repository (Phase 1 Story 1.3 + Phase 2 Story 1.4).

Phase 1 shipped create + get + get-by-name-version. Phase 2 adds
cursor-paginated list + count for the X-Total-Count header.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import QueryTemplate
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

_QUERY_TEMPLATE_SORT_COLUMNS: dict[str, object] = {
    "name": QueryTemplate.name,
    "created_at": QueryTemplate.created_at,
    "engine_type": QueryTemplate.engine_type,
    "version": QueryTemplate.version,
}


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
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
    sort: str | None = None,
    engine_type: str | None = None,
) -> Sequence[QueryTemplate]:
    """Cursor-paginated list, sort-aware (Story 1.3) + engine_type filter (Story 1.4)."""
    parsed_sort: ParsedSort | None = parse_sort(sort, _QUERY_TEMPLATE_SORT_COLUMNS)
    # feat_fts_rank_ordering: relevance ordering when ?q= present and no ?sort=.
    is_rank = rank_active(q, parsed_sort)
    stmt: Select[Any]
    if is_rank and q is not None:  # q is non-None whenever is_rank is True
        rank_col = rank_bucket_expr(q)
        stmt = select(QueryTemplate, rank_col.label("rb"))
        order_col: Any = rank_col
        keyset_parsed: ParsedSort | None = None
    else:
        stmt = select(QueryTemplate)
        order_col = QueryTemplate.created_at
        keyset_parsed = parsed_sort
    if since is not None:
        stmt = stmt.where(QueryTemplate.created_at >= since)
    if engine_type is not None:
        stmt = stmt.where(QueryTemplate.engine_type == engine_type)
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
                id_col=QueryTemplate.id,
            )
        )
    stmt = stmt.order_by(
        *order_by_clauses(
            keyset_parsed,
            default_col=order_col,
            id_col=QueryTemplate.id,
        )
    ).limit(min(limit, 200))
    result = await db.execute(stmt)
    if is_rank:
        return rows_with_rank(result)
    return list(result.scalars().all())


async def count_query_templates(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    q: str | None = None,
    engine_type: str | None = None,
) -> int:
    """COUNT(*) templates for the X-Total-Count header."""
    stmt = select(func.count(QueryTemplate.id))
    if since is not None:
        stmt = stmt.where(QueryTemplate.created_at >= since)
    if engine_type is not None:
        stmt = stmt.where(QueryTemplate.engine_type == engine_type)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    return int((await db.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# chore_e2e_test_rows_isolation Story 1.1 — hard-delete for test-only cleanup
# ---------------------------------------------------------------------------


async def hard_delete_query_template(db: AsyncSession, template_id: str) -> bool:
    """Hard-delete the query_template row for test-only cleanup.

    No FK children cascade with template; the handler must preflight all
    three dependent tables (``studies``, ``proposals``,
    ``judgment_lists.current_template_id``).

    Returns ``True`` if a row was deleted, ``False`` if no row existed.
    Caller commits. Used ONLY by the test-only `DELETE /api/v1/_test/
    query-templates/{id}` endpoint per ``chore_e2e_test_rows_isolation`` FR-6.
    """
    existing = await db.get(QueryTemplate, template_id)
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True
