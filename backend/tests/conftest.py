# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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


def postgres_skip_reason() -> str | None:
    """Return ``None`` if Postgres is reachable, else a precise skip-reason string.

    Three failure modes (any one triggers a skip), each with a distinct,
    operator-actionable reason:

    1. ``DATABASE_URL_FILE`` or ``POSTGRES_PASSWORD_FILE`` env var is absent
       — Postgres might be perfectly reachable, but the test process can't
       construct a ``Settings`` instance against it. Hint: probably a
       missing ``-e`` flag on the test invocation (e.g.
       ``make test-worktree`` before PR #257 didn't propagate
       ``POSTGRES_PASSWORD_FILE``).
    2. ``Settings`` construction itself fails — secret file is mounted but
       unreadable, or contents are malformed. Hint: regenerate via
       ``bash scripts/install.sh``.
    3. TCP connect to ``host:port`` times out — Postgres container isn't
       running. Hint: ``make up`` from the main worktree.

    Used by ``db_session`` (below) for its skip message AND by ``postgres_
    reachable()`` (the existing boolean-returning helper that 100+ test files
    consume via ``pytest.mark.skipif(not postgres_reachable(), ...)``).
    Tests that just need the boolean keep using ``postgres_reachable()``;
    fixtures that want a precise reason for operators use this one.

    The disambiguation closes ``chore_db_session_skip_reason_disambiguation``
    — the prior skip reason was hardcoded to ``"Postgres not reachable"``,
    which is correct only for case 3 and misleads operators in cases 1 + 2.
    """
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return (
            "Postgres skip: DATABASE_URL_FILE or POSTGRES_PASSWORD_FILE env var "
            "not present — see docs/03_runbooks/local-dev.md §'Local-vs-CI test "
            "layers' (likely a missing -e flag on the test invocation; cf. "
            "infra_test_worktree_missing_integration_envs)."
        )
    try:
        from backend.app.core.settings import get_settings

        url = get_settings().database_url
    except Exception as exc:  # noqa: BLE001 — best-effort skip-detector
        return (
            f"Postgres skip: Settings construction failed ({type(exc).__name__}) — "
            "secret file may be unreadable or malformed. Regenerate via "
            "`bash scripts/install.sh`."
        )
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return None
    except (TimeoutError, OSError):
        return (
            f"Postgres skip: TCP connect to {host}:{port} timed out — Postgres "
            "container may not be running (try `make up` from the main worktree). "
            "See docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."
        )


def postgres_reachable() -> bool:
    """Return True only if Settings is constructible AND the DB host:port accepts TCP.

    Thin wrapper over ``postgres_skip_reason()``. Kept for backward compat
    with the 100+ callsites that use ``pytest.mark.skipif(not postgres_
    reachable(), reason="Postgres not reachable")`` — refactoring them all
    to use the precise reason is out of scope.

    Used by integration test fixtures to skip cleanly when Postgres isn't
    available from the test process (e.g. host shell against a Compose
    Postgres that's bound to internal-only networking).
    """
    return postgres_skip_reason() is None


_MIGRATIONS_APPLIED = False
"""Module-level flag to apply Alembic migrations exactly once per test session.

CI doesn't run a migration step before pytest, so any test that reads/writes
business tables (``test_cluster_repo.py``, etc.) needs the schema in place
on first use. ``test_clusters_migration.py`` exercises the full upgrade /
downgrade cycle itself and resets this flag to force re-application after.
"""


def _apply_migrations_if_needed() -> None:
    """Apply ``alembic upgrade head`` once if schema isn't already present."""
    global _MIGRATIONS_APPLIED
    if _MIGRATIONS_APPLIED:
        return
    import subprocess
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    _MIGRATIONS_APPLIED = True


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:  # type: ignore[name-defined] # noqa: F821
    """Yield an ``AsyncSession`` against the integration-test Postgres.

    Skips automatically when Postgres isn't reachable. Each test runs inside
    a SAVEPOINT-style transaction that's rolled back on teardown, so tests
    don't leak rows between runs and cleanup never runs against a partially
    committed schema. On first use per session, applies Alembic migrations
    so the business tables exist (CI doesn't have a separate migration step).
    """
    reason = postgres_skip_reason()
    if reason is not None:
        pytest.skip(reason)
    _apply_migrations_if_needed()

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
