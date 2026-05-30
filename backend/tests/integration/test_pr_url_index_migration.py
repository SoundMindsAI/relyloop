# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``0006_proposals_pr_url_idx`` migration test (feat_github_webhook Story 1.1).

Asserts:

- After ``alembic upgrade head`` the partial B-tree index
  ``proposals_pr_url_idx`` exists on ``proposals(pr_url)`` and carries the
  documented ``WHERE pr_url IS NOT NULL`` predicate.
- ``alembic downgrade 0005`` removes the index cleanly; the chain stays
  forward-compatible with future migrations beyond ``0006``.

Marked ``@pytest.mark.integration`` and skipped automatically when Postgres
is not host-reachable from the test process (mirrors the pattern in
``test_clusters_migration.py``).
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
class TestProposalsPrUrlIdxMigration:
    """Verify the 0006 migration creates the partial index and round-trips."""

    def test_upgrade_creates_partial_index(self, restore_head: None) -> None:
        """After upgrade head, ``proposals_pr_url_idx`` exists with the partial predicate."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                # pg_indexes carries the full CREATE INDEX statement in `indexdef`,
                # which lets us assert both index presence AND the partial-WHERE clause.
                row = conn.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE schemaname = 'public' "
                        "AND tablename = 'proposals' "
                        "AND indexname = 'proposals_pr_url_idx'"
                    )
                ).fetchone()
                assert row is not None, "proposals_pr_url_idx missing after upgrade head"
                indexdef = row[1]
                assert "pr_url" in indexdef
                # Partial-index clause; case can vary across PG versions so lowercase compare.
                assert "where (pr_url is not null)" in indexdef.lower()
        finally:
            engine.dispose()

    def test_downgrade_removes_index(self, restore_head: None) -> None:
        """Downgrading to 0005 removes the partial index.

        Uses an explicit target revision (``0005``) rather than ``-1`` so the
        test stays correct as later migrations extend the chain past ``0006``.
        From any head ≥ ``0006``, ``alembic downgrade 0005`` walks back
        through every intermediate migration and lands at ``0005``, where
        the index does not yet exist.
        """
        _alembic("upgrade", "head")
        _alembic("downgrade", "0005")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' "
                        "AND tablename = 'proposals' "
                        "AND indexname = 'proposals_pr_url_idx'"
                    )
                ).fetchall()
                assert rows == []
        finally:
            engine.dispose()

    def test_upgrade_downgrade_upgrade_round_trip(self, restore_head: None) -> None:
        """Full round-trip per CLAUDE.md Rule #5."""
        _alembic("upgrade", "head")
        _alembic("downgrade", "0005")
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' "
                        "AND tablename = 'proposals' "
                        "AND indexname = 'proposals_pr_url_idx'"
                    )
                ).fetchone()
                assert row is not None
        finally:
            engine.dispose()
