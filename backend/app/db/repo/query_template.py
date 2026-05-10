"""Query-template repository (feat_study_lifecycle Phase 1, Story 1.3).

Phase 1 ships only the read/write functions needed by `infra_optuna_eval`'s
`run_trial` (which loads a template by id) plus enough seeding helpers for
the migration tests. Phase 2 extends with cursor pagination + the
``POST /query-templates`` create-and-validate flow.
"""

from __future__ import annotations

from sqlalchemy import select
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
