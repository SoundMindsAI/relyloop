"""Query repository (Phase 1 Story 1.3 + Phase 2 Story 1.4).

Phase 1 shipped create + list-for-set (consumed by ``run_trial``).
Phase 2 adds bulk insertion for the ``POST /query-sets/{id}/queries``
flow — both JSON and CSV upload paths funnel through
:func:`bulk_create_queries`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import uuid_utils
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Query


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


async def list_queries_for_set(db: AsyncSession, query_set_id: str) -> Sequence[Query]:
    """List every query in a query set, ordered by id (deterministic)."""
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
