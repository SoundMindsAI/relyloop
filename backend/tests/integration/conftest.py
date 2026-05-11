"""Integration-test conftest (Phase 2).

Two autouse fixtures:

* :func:`_clean_phase2_tables` — wipes Phase 2 tables after every test so
  TestClient-driven commits (which bypass the savepoint-scoped
  ``db_session`` fixture) don't leak rows into the next test.

* :func:`async_client` — an ``httpx.AsyncClient`` mounted on the
  FastAPI app via ``LifespanManager``. The lifespan-driven Arq pool
  wiring is suppressed via ``app.state`` injection so the studies
  POST handler degrades gracefully to a no-op enqueue (operators must
  boot the worker separately to drive the lifecycle).

  Mixing ``async def`` tests with the sync ``TestClient`` triggers
  "Future attached to a different loop" errors because TestClient
  spawns its own loop nested inside pytest-asyncio's loop. Using
  ``httpx.AsyncClient`` keeps every coroutine on the test's single
  loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from asgi_lifespan import LifespanManager
from sqlalchemy import text

from backend.tests.conftest import postgres_reachable


@pytest_asyncio.fixture(autouse=True)
async def _clean_phase2_tables() -> AsyncIterator[None]:
    """Wipe Phase 2 tables after each test (FK-safe order).

    Uses a **one-shot engine** that we dispose at the end of the fixture
    so the asyncpg connections don't get pooled and re-issued to the next
    test (which runs on a fresh event loop and would hit
    ``MissingGreenlet`` when asyncpg tries to close the prior-loop
    connection).
    """
    yield
    if not postgres_reachable():
        return

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.app.core.settings import get_settings

    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as db:
            for table in (
                "proposals",
                "trials",
                "studies",
                "judgment_lists",
                "queries",
                "query_sets",
                "query_templates",
                "clusters",
            ):
                await db.execute(text(f"DELETE FROM {table}"))
            await db.commit()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield an ``httpx.AsyncClient`` mounted on the FastAPI app.

    Applies Alembic migrations on first call (CI doesn't run migrations
    as a separate workflow step). Uses ``LifespanManager`` so
    startup/shutdown hooks run (including the Arq pool builder). In
    tests Redis IS reachable (CI service container) so the pool
    builds; the enqueued ``start_study`` jobs sit in the queue with no
    worker to pick them up — that's fine, the tests don't assert
    worker behavior.
    """
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client
