"""Migration 0016 integration test (feat_config_repo_baseline_tracking Story 1.1).

Covers AC-1 (round-trip from prior head + column/FK/index shape) and AC-2 (backfill
seeds ``config_repos.last_merged_proposal_id`` from existing merged proposals).

Same skip-gate pattern as :mod:`backend.tests.integration.test_migrations` — only
runs when Postgres is reachable from the test process (CI service container or
ad-hoc local Postgres).
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
def fresh_at_head() -> Iterator[None]:
    """Ensure the DB ends at head after the test (so siblings aren't affected)."""
    yield
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


# --------------------------------------------------------------------------
# AC-1: column type + FK + partial index introspection (round-trip)
# --------------------------------------------------------------------------


def _assert_column_shape_present(conn: object) -> None:
    """Assert column exists with correct type + nullability + FK + index."""
    column = conn.execute(  # type: ignore[attr-defined]
        text(
            """
            SELECT data_type, character_maximum_length, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'config_repos'
              AND column_name = 'last_merged_proposal_id'
            """
        )
    ).fetchone()
    assert column is not None, "last_merged_proposal_id column missing"
    assert column[0] == "character varying"
    assert column[1] == 36
    assert column[2] == "YES"  # nullable

    fk = conn.execute(  # type: ignore[attr-defined]
        text(
            """
            SELECT
                ccu.table_name,
                ccu.column_name,
                rc.delete_rule
            FROM information_schema.referential_constraints rc
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = rc.constraint_name
            JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = rc.constraint_name
            WHERE kcu.table_name = 'config_repos'
              AND kcu.column_name = 'last_merged_proposal_id'
            """
        )
    ).fetchone()
    assert fk is not None, "FK constraint missing"
    assert fk[0] == "proposals"
    assert fk[1] == "id"
    assert fk[2] == "SET NULL"

    idx = conn.execute(  # type: ignore[attr-defined]
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE tablename = 'config_repos'
              AND indexname = 'config_repos_last_merged_proposal_id_idx'
            """
        )
    ).fetchone()
    assert idx is not None, "partial index missing"
    assert "last_merged_proposal_id" in idx[0]
    assert "WHERE" in idx[0] and "last_merged_proposal_id IS NOT NULL" in idx[0]


def _assert_column_shape_absent(conn: object) -> None:
    """Assert the column + index are gone (post-downgrade state)."""
    column = conn.execute(  # type: ignore[attr-defined]
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'config_repos'
              AND column_name = 'last_merged_proposal_id'
            """
        )
    ).fetchone()
    assert column is None, "column should be gone after downgrade"
    idx = conn.execute(  # type: ignore[attr-defined]
        text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'config_repos'
              AND indexname = 'config_repos_last_merged_proposal_id_idx'
            """
        )
    ).fetchone()
    assert idx is None, "partial index should be gone after downgrade"


@pytest.mark.integration
class TestMigration0016Shape:
    """AC-1: column + FK + partial index round-trip cleanly."""

    def test_ac1_column_fk_index_round_trip(self, fresh_at_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                _assert_column_shape_present(conn)
                head_row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                assert head_row is not None and head_row[0] == "0016"
        finally:
            engine.dispose()

        _alembic("downgrade", "-1")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                _assert_column_shape_absent(conn)
                back_row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                assert back_row is not None and back_row[0] == "0015"
        finally:
            engine.dispose()

        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                _assert_column_shape_present(conn)
        finally:
            engine.dispose()


# --------------------------------------------------------------------------
# AC-2: backfill correctness from raw-SQL seed at revision 0015
# --------------------------------------------------------------------------


@pytest.mark.integration
class TestMigration0016Backfill:
    """AC-2: backfill seeds the column from existing merged proposals.

    Seeds via raw SQL at revision 0015 (BEFORE the new column exists) so
    the test doesn't rely on the updated ConfigRepo ORM model (which
    declares `last_merged_proposal_id` and would try to INSERT/SELECT a
    column that doesn't exist at 0015). Per cycle-2 cross-model review F3.
    """

    def test_ac2_backfill_picks_newest_merged_proposal_per_repo(self, fresh_at_head: None) -> None:
        # 1) Downgrade to 0015 (the prior head, BEFORE this feature's migration).
        _alembic("upgrade", "head")
        _alembic("downgrade", "0015")

        # 2) Seed via raw SQL — only 0015-era columns.
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                # Clean any pre-existing rows from prior test runs.
                conn.execute(text("DELETE FROM proposals"))
                conn.execute(text("DELETE FROM clusters"))
                conn.execute(text("DELETE FROM config_repos"))

                # 2 config_repos.
                conn.execute(
                    text(
                        """
                        INSERT INTO config_repos
                            (id, name, provider, repo_url, default_branch, pr_base_branch,
                             auth_ref)
                        VALUES
                            ('repo-A-0000000000000000000000000000',
                             'repo-a', 'github',
                             'https://github.com/example/a',
                             'main', 'main', 'pat_a'),
                            ('repo-B-0000000000000000000000000000',
                             'repo-b', 'github',
                             'https://github.com/example/b',
                             'main', 'main', 'pat_b');
                        """
                    )
                )

                # 3 clusters: cA1 + cA2 wired to repo-A; cB1 wired to repo-B.
                conn.execute(
                    text(
                        """
                        INSERT INTO clusters
                            (id, name, engine_type, environment, base_url,
                             auth_kind, credentials_ref, config_repo_id)
                        VALUES
                            ('clstr-cA1-000000000000000000000000',
                             'cA1', 'elasticsearch', 'prod',
                             'http://es-a1:9200', 'es_apikey', 'cred_a1',
                             'repo-A-0000000000000000000000000000'),
                            ('clstr-cA2-000000000000000000000000',
                             'cA2', 'elasticsearch', 'dev',
                             'http://es-a2:9200', 'es_apikey', 'cred_a2',
                             'repo-A-0000000000000000000000000000'),
                            ('clstr-cB1-000000000000000000000000',
                             'cB1', 'opensearch', 'prod',
                             'http://os-b1:9200', 'opensearch_basic',
                             'cred_b1',
                             'repo-B-0000000000000000000000000000');
                        """
                    )
                )

                # Need a query template + query set + judgment list + study
                # to satisfy the proposals FKs in 0015's schema. Use minimal
                # rows with only fields known to exist at 0015.
                conn.execute(
                    text(
                        """
                        INSERT INTO query_templates
                            (id, name, engine_type, body, declared_params,
                             version, created_at)
                        VALUES
                            ('tmpl-0000-0000-0000-0000-000000000001',
                             't1', 'elasticsearch', '{}', '{}'::jsonb, 1, now());
                        """
                    )
                )

                # 4 proposals — PA1, PA2 wired via cA1; PB1 via cB1; PA3 pending.
                # PA1: merged 2026-05-10, PA2: merged 2026-05-20, PB1: merged 2026-05-15.
                # Expected: repo-A pointer → PA2 (newest), repo-B pointer → PB1.
                conn.execute(
                    text(
                        """
                        INSERT INTO proposals
                            (id, cluster_id, template_id, config_diff,
                             status, pr_state, pr_merged_at, created_at)
                        VALUES
                            ('prop-PA1-000000000000000000000000',
                             'clstr-cA1-000000000000000000000000',
                             'tmpl-0000-0000-0000-0000-000000000001',
                             '{}'::jsonb,
                             'pr_merged', 'merged',
                             '2026-05-10 12:00:00+00', now()),
                            ('prop-PA2-000000000000000000000000',
                             'clstr-cA2-000000000000000000000000',
                             'tmpl-0000-0000-0000-0000-000000000001',
                             '{}'::jsonb,
                             'pr_merged', 'merged',
                             '2026-05-20 12:00:00+00', now()),
                            ('prop-PB1-000000000000000000000000',
                             'clstr-cB1-000000000000000000000000',
                             'tmpl-0000-0000-0000-0000-000000000001',
                             '{}'::jsonb,
                             'pr_merged', 'merged',
                             '2026-05-15 12:00:00+00', now()),
                            ('prop-PA3-000000000000000000000000',
                             'clstr-cA1-000000000000000000000000',
                             'tmpl-0000-0000-0000-0000-000000000001',
                             '{}'::jsonb,
                             'pending', NULL, NULL, now());
                        """
                    )
                )
        finally:
            engine.dispose()

        # 3) Run the migration (advances 0015 → 0016, runs backfill).
        _alembic("upgrade", "head")

        # 4) Assert backfill picked the newest merged proposal per repo.
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT id, last_merged_proposal_id
                        FROM config_repos
                        ORDER BY id
                        """
                    )
                ).fetchall()
                pointers = {row[0]: row[1] for row in rows}
                assert (
                    pointers["repo-A-0000000000000000000000000000"]
                    == "prop-PA2-000000000000000000000000"
                ), f"repo-A backfill incorrect: {pointers}"
                assert (
                    pointers["repo-B-0000000000000000000000000000"]
                    == "prop-PB1-000000000000000000000000"
                ), f"repo-B backfill incorrect: {pointers}"
        finally:
            engine.dispose()

        # 5) Clean up the seeded rows so other tests aren't affected.
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                # Order: proposals → clusters → config_repos (FK direction).
                # Also clear the FK we just wrote so we can drop proposals.
                conn.execute(text("UPDATE config_repos SET last_merged_proposal_id = NULL"))
                conn.execute(text("DELETE FROM proposals"))
                conn.execute(text("DELETE FROM clusters"))
                conn.execute(text("DELETE FROM config_repos"))
                conn.execute(text("DELETE FROM query_templates"))
        finally:
            engine.dispose()
