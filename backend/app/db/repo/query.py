"""Query repository (feat_study_lifecycle Phase 1, Story 1.3).

Phase 1 ships create + list-for-set (consumed by `infra_optuna_eval`'s
`run_trial`, which loads every query in the study's query_set to render
a batch of NativeQuery bodies). Phase 2 adds the bulk CSV upload flow.
"""

from __future__ import annotations

from collections.abc import Sequence

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
