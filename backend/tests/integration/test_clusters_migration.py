"""``0002_clusters_config_repos`` migration test (infra_adapter_elastic Story 1.3).

Asserts:

- After ``alembic upgrade head`` the ``clusters`` and ``config_repos`` tables
  exist.
- ``alembic downgrade -1`` removes both tables cleanly.
- The ``clusters_auth_kind_check`` CHECK constraint accepts the four
  documented values and rejects an out-of-allowlist value (e.g.
  ``solr_basic``) per spec §7.4 + the wire-value source of truth.

Marked ``@pytest.mark.integration`` and skipped automatically when Postgres
is not host-reachable from the test process; see
``test_migrations.py`` module docstring for the rationale.
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
from sqlalchemy.exc import IntegrityError

from backend.app.core.settings import get_settings

REPO = Path(__file__).resolve().parents[3]


def _postgres_reachable() -> bool:
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
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
    yield
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


@pytest.mark.integration
class TestClustersMigration:
    """Verify the 0002 migration creates both tables, round-trips, and enforces CHECKs."""

    def test_upgrade_creates_clusters_and_config_repos(self, restore_head: None) -> None:
        """After upgrade head, both tables exist with the expected primary keys."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name IN ('clusters', 'config_repos') "
                        "ORDER BY table_name"
                    )
                ).fetchall()
                names = [row[0] for row in rows]
                assert names == ["clusters", "config_repos"]
        finally:
            engine.dispose()

    def test_downgrade_removes_both_tables(self, restore_head: None) -> None:
        """Downgrading to 0001 removes both clusters + config_repos.

        Uses an explicit target revision (``0001``) rather than ``-1`` so the
        test stays correct as later migrations (e.g. ``0003`` from
        ``feat_study_lifecycle`` Phase 1) extend the chain. From any head ≥
        ``0002``, ``alembic downgrade 0001`` walks back through every
        intermediate migration and lands at ``0001``, where neither
        ``clusters`` nor ``config_repos`` exists yet.
        """
        _alembic("upgrade", "head")
        _alembic("downgrade", "0001")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name IN ('clusters', 'config_repos')"
                    )
                ).fetchall()
                assert rows == []
        finally:
            engine.dispose()

    def test_auth_kind_check_constraint(self, restore_head: None) -> None:
        """CHECK rejects 'solr_basic' but accepts the four documented values."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                # Reject the out-of-allowlist value first (verifies CHECK fires).
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO clusters "
                            "(id, name, engine_type, environment, base_url, auth_kind, "
                            " credentials_ref) "
                            "VALUES ('id-bad', 'bad', 'elasticsearch', 'dev', "
                            "'http://x', 'solr_basic', 'ref')"
                        )
                    )
            # Each accepted value gets its own row + transaction (the failed insert
            # above poisoned the previous one).
            for i, kind in enumerate(
                ["es_apikey", "es_basic", "opensearch_basic", "opensearch_sigv4"]
            ):
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO clusters "
                            "(id, name, engine_type, environment, base_url, auth_kind, "
                            " credentials_ref) "
                            "VALUES (:id, :name, 'elasticsearch', 'dev', "
                            "'http://x', :auth, 'ref')"
                        ),
                        {"id": f"id-{i}", "name": f"ok-{i}", "auth": kind},
                    )
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM clusters WHERE id LIKE 'id-%'"))
        finally:
            engine.dispose()
