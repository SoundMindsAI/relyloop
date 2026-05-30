# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Idempotency test for ``make seed-clusters`` (Story 4.1 / spec §14).

Runs the seed entrypoint twice and asserts exactly two cluster rows
remain — i.e. the second run hit ``ClusterNameTaken`` for both
local-es and local-opensearch and treated them as success rather than
inserting duplicates.

Skips when the full stack (Postgres + ES + OpenSearch) isn't reachable.
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.settings import get_settings


def _stack_reachable() -> bool:
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
        url = get_settings().database_url
    except Exception:  # noqa: BLE001
        return False
    parsed = urlparse(url)
    pg_host = parsed.hostname or "localhost"
    pg_port = parsed.port or 5432
    try:
        with socket.create_connection((pg_host, pg_port), timeout=1.0):
            pass
    except (TimeoutError, OSError):
        return False
    for h in (("elasticsearch", 9200), ("opensearch", 9200)):
        try:
            with socket.create_connection(h, timeout=1.0):
                continue
        except (TimeoutError, OSError):
            return False
    return True


pytestmark = pytest.mark.skipif(
    not _stack_reachable(),
    reason=(
        "Stack not fully reachable — needs Postgres + ES + OpenSearch from "
        "this process. Run via the dev-deps container with --network "
        "relyloop_default."
    ),
)


@pytest_asyncio.fixture(autouse=True)
async def _stub_credentials_yaml(tmp_path, monkeypatch):
    """Mount the dev-default credentials so seed_clusters can resolve refs."""
    creds = tmp_path / "creds.yaml"
    creds.write_text(
        "local-es:\n  username: elastic\n  password: changeme\n"
        "local-opensearch:\n  username: admin\n  password: admin\n"
    )
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def reset_clusters_table():
    """Hard-clear clusters before + after the test (no FKs in MVP1)."""
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM clusters"))
    await engine.dispose()
    yield
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM clusters"))
    await engine.dispose()


@pytest.mark.integration
async def test_seed_clusters_idempotent(reset_clusters_table) -> None:
    from backend.app.db.session import get_engine, get_session_factory
    from backend.app.scripts.seed_clusters import main

    # Reset session factory caches so the freshly-cleared DB is used.
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    # Run twice — second run should be a no-op (ClusterNameTaken → skip).
    rc1 = await main()
    rc2 = await main()
    assert rc1 == 0
    assert rc2 == 0

    # Exactly two rows total.
    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        async with engine.connect() as conn:
            count = (await conn.execute(text("SELECT COUNT(*) FROM clusters"))).scalar_one()
            assert count == 2
            names = sorted(
                row[0] for row in (await conn.execute(text("SELECT name FROM clusters"))).all()
            )
            assert names == ["local-es", "local-opensearch"]
    finally:
        await engine.dispose()
