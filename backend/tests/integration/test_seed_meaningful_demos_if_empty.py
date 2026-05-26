"""Integration test for the auto-seed-on-empty SQL contract.

Pins `scripts/seed_meaningful_demos._COUNT_LIVE_CLUSTERS_SQL` so a single
E2E test that soft-deletes its cluster fixtures cannot permanently
disable the auto-seed-on-empty path at `scripts/install.sh:95`. The bug
(`bug_seed_demo_if_empty_counts_soft_deleted`) was: the SQL was
`SELECT COUNT(*) FROM clusters` with no `WHERE deleted_at IS NULL`
filter, so soft-deleted tombstones counted as "exists" and the
`--if-empty` branch false-skipped.

Skips when Postgres isn't reachable (matches the pattern in
`test_seed_clusters_idempotent.py`).
"""

from __future__ import annotations

import os
import socket
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.settings import get_settings
from scripts.seed_meaningful_demos import _COUNT_LIVE_CLUSTERS_SQL


def _postgres_reachable() -> bool:
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
            return True
    except (TimeoutError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md.",
)


@pytest_asyncio.fixture
async def _reset_clusters_table():
    """Hard-clear clusters before + after the test (no business FKs in MVP1
    block a raw DELETE of the cluster row; child rows from this test are
    none, so the cleanup is clean)."""
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
async def test_count_live_clusters_sql_excludes_soft_deleted_row(_reset_clusters_table) -> None:
    """End-to-end semantic guard: run the constant SQL against a DB with
    exactly one soft-deleted cluster row and assert it returns 0.

    Pre-fix SQL (`SELECT COUNT(*) FROM clusters;`) would return 1, causing
    the `--if-empty` auto-seed to false-skip. Post-fix SQL (with `WHERE
    deleted_at IS NULL`) returns 0, allowing the auto-seed to fire.
    """
    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        # Seed one soft-deleted cluster row directly via raw SQL (bypassing
        # the API/repo layer — we want to exercise the literal DB state that
        # an E2E test cleanup would leave behind).
        cluster_id = str(uuid.uuid4())
        deleted_at = datetime.now(UTC)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO clusters "
                    "(id, name, engine_type, environment, base_url, auth_kind, "
                    "credentials_ref, created_at, updated_at, deleted_at) "
                    "VALUES (:id, :name, 'elasticsearch', 'dev', "
                    "'http://stub:9200', 'es_basic', 'stub-ref', "
                    ":created_at, :updated_at, :deleted_at)"
                ),
                {
                    "id": cluster_id,
                    "name": f"sd-tombstone-{cluster_id[:8]}",
                    "created_at": deleted_at,
                    "updated_at": deleted_at,
                    "deleted_at": deleted_at,
                },
            )

        # Sanity check: the unqualified count would see 1 row.
        async with engine.connect() as conn:
            unfiltered = (await conn.execute(text("SELECT COUNT(*) FROM clusters"))).scalar_one()
            assert unfiltered == 1, f"setup error: expected 1 cluster row, found {unfiltered}"

        # The constant's SQL filters out the soft-deleted row → returns 0.
        async with engine.connect() as conn:
            live_count = (await conn.execute(text(_COUNT_LIVE_CLUSTERS_SQL))).scalar_one()
        assert live_count == 0, (
            f"_COUNT_LIVE_CLUSTERS_SQL returned {live_count} despite the only "
            "cluster row being soft-deleted. The --if-empty auto-seed would "
            "false-skip on every `make up` after any E2E test that soft-deletes "
            "its cluster fixtures. See bug_seed_demo_if_empty_counts_soft_deleted."
        )
    finally:
        await engine.dispose()
