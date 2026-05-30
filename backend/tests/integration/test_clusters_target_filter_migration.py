# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``0014_clusters_target_filter`` migration test (feat_cluster_target_filter Story B1).

Asserts the schema shape of the ``clusters.target_filter`` column added by
``migrations/versions/0014_clusters_target_filter.py``:

* upgrade head adds the nullable VARCHAR(256) column
* downgrade to 0013 drops the column
* upgrade → downgrade → upgrade round-trip preserves the other 13 cluster columns
  and leaves ``target_filter`` NULL on existing rows (AC-1 from the spec)

Mirrors ``test_conversations_migration.py`` for skip semantics + alembic invocation.
"""

from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text

from backend.app.core.settings import get_settings

REPO = Path(__file__).resolve().parents[3]


def _postgres_reachable() -> bool:
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
        url = get_settings().database_url
    except Exception:  # noqa: BLE001
        return False
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (TimeoutError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=(
        "Postgres not reachable from this process — see "
        "docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."
    ),
)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )


def _sync_database_url() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
def restore_head() -> Iterator[None]:
    """Always leave the DB at head, even if the test failed mid-downgrade."""
    yield
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


def _column_info(conn) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'clusters'"
        )
    ).fetchall()
    return {r[0]: {"data_type": r[1], "max_length": r[2], "nullable": r[3]} for r in rows}


@pytest.mark.integration
class TestClustersTargetFilterMigration:
    def test_upgrade_adds_nullable_varchar256_column(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _column_info(conn)
                assert "target_filter" in cols, "0014 upgrade should add clusters.target_filter"
                col = cols["target_filter"]
                assert col["data_type"] == "character varying"
                assert col["max_length"] == 256
                assert col["nullable"] == "YES"
        finally:
            engine.dispose()

    def test_downgrade_drops_column(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        _alembic("downgrade", "0013")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _column_info(conn)
                assert "target_filter" not in cols, (
                    "downgrade to 0013 should drop clusters.target_filter"
                )
        finally:
            engine.dispose()

    def test_roundtrip_preserves_other_columns(self, restore_head: None) -> None:
        """Upgrade → downgrade → upgrade leaves the other 13 columns intact
        and target_filter present + nullable on the final upgrade (AC-1)."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                before = set(_column_info(conn).keys())
        finally:
            engine.dispose()

        _alembic("downgrade", "0013")
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                after = _column_info(conn)
                assert set(after.keys()) == before, (
                    f"column set changed across round-trip: "
                    f"only-before={before - set(after.keys())}, "
                    f"only-after={set(after.keys()) - before}"
                )
                assert after["target_filter"]["nullable"] == "YES"
        finally:
            engine.dispose()
