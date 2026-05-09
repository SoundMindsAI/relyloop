"""Async SQLAlchemy engine + session factory (infra_foundation Story 2.1).

Provides:

- ``engine`` — module-level ``AsyncEngine`` constructed once at import time
  from ``Settings.database_url`` (resolved from ``DATABASE_URL_FILE``).
- ``async_session_factory`` — ``async_sessionmaker`` bound to the engine.
- ``get_db()`` — FastAPI dependency yielding an ``AsyncSession``; used as
  ``db: AsyncSession = Depends(get_db)`` in routers (when those land in
  Story 3.x and beyond).

The engine is created lazily so that ``import backend.app.db.session`` does
not fail at module-load time when secrets aren't yet configured (e.g. during
unit tests that mock the database). Use ``get_engine()`` in callers that
need the engine; ``get_db()`` constructs the session factory on first use.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.core.settings import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Construct the singleton async SQLAlchemy engine.

    The DSN is read from ``Settings.database_url`` (which reads
    ``DATABASE_URL_FILE``). ``pool_pre_ping=True`` issues a lightweight
    ``SELECT 1`` before borrowing a connection so dropped connections get
    transparently re-established (cheap; cost-justified for laptop deploys
    where Docker may pause Postgres).
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Construct the singleton ``async_sessionmaker`` bound to the engine."""
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an ``AsyncSession``.

    Usage in routers (lands with Story 3.x+):

    .. code-block:: python

        from fastapi import Depends
        from sqlalchemy.ext.asyncio import AsyncSession
        from backend.app.db.session import get_db


        @router.get("/clusters/{cluster_id}")
        async def read_cluster(
            cluster_id: str,
            db: AsyncSession = Depends(get_db),
        ): ...
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session
