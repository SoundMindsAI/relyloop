"""Pytest fixtures for the RelyLoop backend test suite.

Most fixtures land with the stories that need them:

- ``async_client`` (httpx.AsyncClient against the FastAPI app) — Story 3.1+
- ``db_session`` (async SQLAlchemy session against a test database) — added
  with infra_adapter_elastic Story 1.4 (the first feature with business tables).
- ``redis_client`` (aioredis client against the test Redis) — Story 3.3+
- ``mock_llm`` (OpenAI client stub) — Story 3.3+

Bootstrap-level isolation:

- ``_clear_settings_caches`` (autouse) — clears the ``lru_cache`` on
  ``get_settings()``, ``get_engine()``, and ``get_session_factory()`` between
  tests. Without this, a test that monkeypatches ``DATABASE_URL_FILE``
  (e.g. ``test_health.py``) leaves the cached ``Settings`` populated with
  the stub URL — subsequent tests (like ``test_migrations.py``) then call
  ``get_settings().database_url`` and receive the polluted value
  ``postgresql+asyncpg://x:y@localhost/test`` instead of the real CI
  service-container URL, surfacing as
  ``psycopg2.OperationalError: password authentication failed for user "x"``.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def _clear_settings_caches() -> None:
    """Clear lru_cache on settings/engine/session factory between tests.

    Runs before every test so a prior test's monkeypatched env doesn't leak
    a polluted ``Settings`` into the next test's ``get_settings()`` calls.
    """
    from backend.app.core.settings import get_settings
    from backend.app.db.session import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def postgres_reachable() -> bool:
    """Return True only if Settings is constructible AND the DB host:port accepts TCP.

    Used by integration test fixtures to skip cleanly when Postgres isn't
    available from the test process (e.g. host shell against a Compose
    Postgres that's bound to internal-only networking).
    """
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
        from backend.app.core.settings import get_settings

        url = get_settings().database_url
    except Exception:  # noqa: BLE001 — best-effort skip-detector
        return False
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (TimeoutError, OSError):
        return False


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:  # type: ignore[name-defined] # noqa: F821
    """Yield an ``AsyncSession`` against the integration-test Postgres.

    Skips automatically when Postgres isn't reachable. Each test runs inside
    a SAVEPOINT-style transaction that's rolled back on teardown, so tests
    don't leak rows between runs and cleanup never runs against a partially
    committed schema.
    """
    if not postgres_reachable():
        pytest.skip(
            "Postgres not reachable — see docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."
        )
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from backend.app.core.settings import get_settings

    engine = create_async_engine(get_settings().database_url, echo=False, future=True)
    async with engine.connect() as conn:
        outer_tx = await conn.begin()
        factory = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            try:
                yield session
            finally:
                await session.close()
                await outer_tx.rollback()
    await engine.dispose()
