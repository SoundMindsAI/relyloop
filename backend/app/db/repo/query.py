# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Query repository (Phase 1 Story 1.3 + Phase 2 Story 1.4 + feat_query_inline_crud).

Phase 1 shipped create + list-for-set (consumed by ``run_trial``).
Phase 2 adds bulk insertion for the ``POST /query-sets/{id}/queries``
flow — both JSON and CSV upload paths funnel through
:func:`bulk_create_queries`.

feat_query_inline_crud (Stories 1.2 + 2.2 + 3.2) adds per-query CRUD:

* :func:`get_query` — single-row fetch by id
* :func:`count_queries_for_set` — total count under a set, ``?since``-filterable
* :func:`list_queries_for_set_cursor` — id-based cursor pagination + ``?since``
* :func:`update_query` — partial update with fields-set semantics
* :func:`delete_query` — raw DELETE; caller catches FK ``IntegrityError``

Cursor and ``?since`` filters both use plain UUIDv7 strings (no
``created_at`` column exists on ``queries``; UUIDv7 is lexically
time-ordered, which is sufficient).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy
import uuid_utils
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Judgment, Query


async def create_query(db: AsyncSession, **fields: object) -> Query:
    """Stage a new ``Query`` row. Caller commits.

    Note: the JSONB metadata column maps to the Python attribute
    ``query_metadata`` on the ORM model — pass ``query_metadata={...}`` in
    ``**fields``, not ``metadata={...}``.
    """
    query = Query(**fields)
    db.add(query)
    await db.flush()
    await db.refresh(query)
    return query


async def find_first_judged_query(
    db: AsyncSession,
    *,
    query_set_id: str,
    judgment_list_id: str,
) -> str | None:
    """Return the first ``queries.id`` (by ``id ASC``) in ``query_set`` with judgments.

    ``First`` means the lexically-smallest ``queries.id`` for which ≥1 row
    exists in ``judgments`` under ``judgment_list_id``. Returns ``None`` when
    no qid in the set has any judgments.

    Used by the preflight overlap probe to pick a representative qid without
    fetching ``query_text`` (privacy: query strings stay out of logs per
    ``feat_study_preflight_overlap_probe`` spec §10 Threat 2). Single SELECT
    with a correlated EXISTS subquery; backed by the
    ``judgments_list_query_idx`` on ``(judgment_list_id, query_id)``.
    """
    stmt = (
        select(Query.id)
        .where(Query.query_set_id == query_set_id)
        .where(
            select(Judgment.id)
            .where(Judgment.query_id == Query.id)
            .where(Judgment.judgment_list_id == judgment_list_id)
            .exists()
        )
        .order_by(Query.id.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_queries_for_set(db: AsyncSession, query_set_id: str) -> Sequence[Query]:
    """List every query in a query set, ordered by id (deterministic).

    Used by the worker path (run_trial). For the API list endpoint, use
    :func:`list_queries_for_set_cursor` instead — it supports pagination
    and ``?since`` filtering.
    """
    stmt = select(Query).where(Query.query_set_id == query_set_id).order_by(Query.id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def bulk_create_queries(
    db: AsyncSession,
    query_set_id: str,
    rows: Sequence[dict[str, Any]],
) -> int:
    """Bulk-INSERT ``len(rows)`` ``Query`` rows under ``query_set_id``.

    Each row dict must contain ``query_text`` (str). ``reference_answer``
    (str | None) and ``query_metadata`` (dict | None) are optional.
    Client-side UUIDv7 IDs are generated here so the response handler can
    echo counts without a SELECT round-trip.

    Returns the count of rows actually staged. Caller commits.
    """
    if not rows:
        return 0
    instances = [
        Query(
            id=str(uuid_utils.uuid7()),
            query_set_id=query_set_id,
            query_text=row["query_text"],
            reference_answer=row.get("reference_answer"),
            query_metadata=row.get("query_metadata"),
        )
        for row in rows
    ]
    db.add_all(instances)
    await db.flush()
    return len(instances)


# ---------------------------------------------------------------------------
# feat_query_inline_crud Story 1.2 — per-query reads
# ---------------------------------------------------------------------------


async def get_query(db: AsyncSession, query_id: str) -> Query | None:
    """Fetch a single ``Query`` row by id, or ``None`` if missing.

    The router pairs this with a ``query.query_set_id != set_id`` check for
    cross-set anti-enumeration (see ``feat_query_inline_crud`` spec §10
    Threat 2).
    """
    stmt = select(Query).where(Query.id == query_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def count_queries_for_set(
    db: AsyncSession,
    query_set_id: str,
    *,
    since_lower_bound_id: str | None = None,
) -> int:
    """Total count of queries in a set, optionally filtered by ``?since``.

    ``since_lower_bound_id`` is a UUIDv7 string with the first 48 bits
    set to a Unix-ms timestamp and the remaining bits zero. The filter is
    ``queries.id >= :since_lower_bound_id`` — UUIDv7 lexical ordering
    makes this equivalent to ``created_at_ms >= since_ms``.
    """
    stmt = (
        select(sqlalchemy.func.count()).select_from(Query).where(Query.query_set_id == query_set_id)
    )
    if since_lower_bound_id is not None:
        stmt = stmt.where(Query.id >= since_lower_bound_id)
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def list_queries_for_set_cursor(
    db: AsyncSession,
    query_set_id: str,
    *,
    after_id: str | None = None,
    limit: int = 50,
    since_lower_bound_id: str | None = None,
) -> list[Query]:
    """Cursor-paginated list of queries in a set, ordered by ``id ASC``.

    UUIDv7 lexical ordering is effectively time-ordered, so this is a
    deterministic single-key cursor (no ``(created_at, id)`` tuple needed).

    ``after_id`` filters ``queries.id > :after_id`` (strict — exclusive of
    the cursor row itself, so consecutive pages don't repeat).
    ``since_lower_bound_id`` filters ``queries.id >= :since_lower_bound_id``
    (inclusive — operators expect ``?since=T`` to include rows minted
    exactly at ``T``).
    """
    stmt = select(Query).where(Query.query_set_id == query_set_id)
    if after_id is not None:
        stmt = stmt.where(Query.id > after_id)
    if since_lower_bound_id is not None:
        stmt = stmt.where(Query.id >= since_lower_bound_id)
    stmt = stmt.order_by(Query.id).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# feat_query_inline_crud Story 2.2 — per-query partial update
# ---------------------------------------------------------------------------


async def update_query(
    db: AsyncSession,
    query_id: str,
    *,
    fields_set: dict[str, Any],
) -> Query | None:
    """Apply ONLY the keys present in ``fields_set`` to query ``query_id``.

    The router resolves the body via ``body.model_dump(exclude_unset=True)``
    so omitted keys never reach this function. Explicit null values DO
    reach it and overwrite the column to NULL (used for ``reference_answer``
    and ``query_metadata``).

    Empty ``fields_set`` short-circuits to a fresh SELECT (no UPDATE
    issued — needed for the AC-28 empty-PATCH no-op contract).

    Returns the refreshed ``Query`` row, or ``None`` if the row no longer
    exists (concurrent delete race — caller should treat as 404).
    """
    if not fields_set:
        return await get_query(db, query_id)

    stmt = (
        sqlalchemy.update(Query).where(Query.id == query_id).values(**fields_set).returning(Query)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# feat_query_inline_crud Story 3.2 — per-query hard delete (FK-guarded by caller)
# ---------------------------------------------------------------------------


async def delete_query(db: AsyncSession, query_id: str) -> None:
    """Issue ``DELETE FROM queries WHERE id = :query_id`` and flush.

    The explicit ``await db.flush()`` forces Postgres to check the
    ``judgments.query_id`` foreign-key constraint synchronously. The
    router catches ``IntegrityError``, rolls back, and constructs the
    409 ``QUERY_HAS_JUDGMENTS`` envelope via
    :func:`backend.app.db.repo.judgment.count_and_sample_judgment_refs`.

    No-op if the row doesn't exist (the router checks existence first).
    """
    stmt = sqlalchemy.delete(Query).where(Query.id == query_id)
    await db.execute(stmt)
    await db.flush()
