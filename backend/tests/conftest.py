"""Pytest fixtures for the RelyLoop backend test suite.

Most fixtures land with the stories that need them:

- ``async_client`` (httpx.AsyncClient against the FastAPI app) — Story 3.1+
- ``db_session`` (async SQLAlchemy session against a test database) — Story 2.1+
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

import pytest


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
