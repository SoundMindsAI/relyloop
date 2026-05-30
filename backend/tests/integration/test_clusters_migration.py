# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``0002_clusters_config_repos`` + ``0022_solr_engine_auth_check`` migration tests.

Asserts:

- After ``alembic upgrade head`` the ``clusters`` and ``config_repos`` tables
  exist.
- ``alembic downgrade`` removes both tables cleanly.
- The ``clusters_auth_kind_check`` CHECK constraint accepts the six documented
  values (incl. ``solr_basic`` / ``solr_apikey`` after migration 0022) and
  rejects an out-of-allowlist value per spec §7.4.
- Migration 0022 round-trips (0021↔0022) and its ``downgrade()`` aborts with a
  clear error when a Solr-typed row still exists (infra_adapter_solr Story A6 /
  AC-9).

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
        """CHECK rejects an unknown value but accepts the six documented values.

        After migration 0022, ``solr_basic`` / ``solr_apikey`` are in-allowlist;
        the rejection case uses a genuinely-unknown value.
        """
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                # Reject a genuinely out-of-allowlist value (verifies CHECK fires).
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO clusters "
                            "(id, name, engine_type, environment, base_url, auth_kind, "
                            " credentials_ref) "
                            "VALUES ('id-bad', 'bad', 'elasticsearch', 'dev', "
                            "'http://x', 'fusion_basic', 'ref')"
                        )
                    )
            # Each accepted value gets its own row + transaction (the failed insert
            # above poisoned the previous one). engine_type matches the auth family
            # so the row is realistic (no DB-level cross-product CHECK — that's
            # service-layer), but the auth_kind CHECK is what's under test here.
            accepted = [
                ("elasticsearch", "es_apikey"),
                ("elasticsearch", "es_basic"),
                ("opensearch", "opensearch_basic"),
                ("opensearch", "opensearch_sigv4"),
                ("solr", "solr_basic"),
                ("solr", "solr_apikey"),
            ]
            for i, (engine_type, kind) in enumerate(accepted):
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO clusters "
                            "(id, name, engine_type, environment, base_url, auth_kind, "
                            " credentials_ref) "
                            "VALUES (:id, :name, :engine, 'dev', "
                            "'http://x', :auth, 'ref')"
                        ),
                        {
                            "id": f"id-{i}",
                            "name": f"ok-{i}",
                            "engine": engine_type,
                            "auth": kind,
                        },
                    )
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM clusters WHERE id LIKE 'id-%'"))
        finally:
            engine.dispose()

    def test_0022_roundtrips_and_downgrade_aborts_on_solr_row(self, restore_head: None) -> None:
        """0022 round-trips (0021↔0022); downgrade aborts when a Solr row exists.

        infra_adapter_solr Story A6 / AC-9. The downgrade guard prevents
        restoring the narrower CHECK while a Solr-typed row would violate it.
        """
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            # Clean round-trip with NO solr rows present.
            _alembic("downgrade", "0021")
            _alembic("upgrade", "head")

            # Insert a Solr-typed row, then assert downgrade -1 aborts.
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO clusters "
                        "(id, name, engine_type, environment, base_url, auth_kind, "
                        " credentials_ref) "
                        "VALUES ('solr-guard', 'guard', 'solr', 'dev', "
                        "'http://solr:8983', 'solr_basic', 'ref')"
                    )
                )
            with pytest.raises(subprocess.CalledProcessError) as exc:
                _alembic("downgrade", "0021")
            # The RuntimeError message surfaces in alembic's stderr.
            assert "Solr cluster row" in (exc.value.stderr or "")

            # Cleanup: remove the guard row so the restore_head fixture can
            # upgrade cleanly (we're still at 0022 since the downgrade aborted).
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM clusters WHERE id = 'solr-guard'"))
        finally:
            engine.dispose()
