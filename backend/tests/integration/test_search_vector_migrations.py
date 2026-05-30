# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``0008``–``0013`` migration tests (feat_data_table_primitive Story 1.1).

Six migrations add a `search_vector tsvector GENERATED ALWAYS AS … STORED`
column + a `GIN(search_vector)` index to each searchable table:

- ``0008_search_vector_clusters`` (clusters)
- ``0009_search_vector_studies`` (studies)
- ``0010_search_vector_query_sets`` (query_sets)
- ``0011_search_vector_query_templates`` (query_templates)
- ``0012_search_vector_judgment_lists`` (judgment_lists)
- ``0013_search_vector_conversations`` (conversations)

Asserts:

- After ``alembic upgrade head`` all 6 ``search_vector`` columns and
  ``<table>_search_idx`` GIN indexes exist.
- ``alembic downgrade 0007`` removes every column and index cleanly.
- Per-migration round-trip clean: ``upgrade <rev> → downgrade -1 →
  upgrade <rev>`` succeeds for each of the 6 revisions.
- The ORM models do NOT declare ``search_vector`` (spec FR-2 invariant —
  the column is generated; writes from the application layer would
  trigger ``cannot insert into column "search_vector"``).

Marked ``@pytest.mark.integration``; skipped automatically when Postgres
is not host-reachable.
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

# Use bare numeric revision IDs (matching `revision: str = "NNNN"` in each
# migration file). The file *names* include the descriptive slug
# (`0008_search_vector_clusters.py`) but alembic looks up revisions by the
# `revision` string only.
SEARCH_VECTOR_REVS = ["0008", "0009", "0010", "0011", "0012", "0013"]
TABLES = [
    "clusters",
    "studies",
    "query_sets",
    "query_templates",
    "judgment_lists",
    "conversations",
]


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
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'.",
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


def _columns_with_search_vector() -> list[str]:
    engine = create_engine(_sync_database_url(), future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'search_vector' "
                    "ORDER BY table_name"
                )
            ).fetchall()
            return [r[0] for r in rows]
    finally:
        engine.dispose()


def _gin_indexes_for_search_vector() -> list[str]:
    """Return index names for every GIN index over `search_vector`."""
    engine = create_engine(_sync_database_url(), future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = 'public' AND indexdef ILIKE '%USING gin%search_vector%' "
                    "ORDER BY indexname"
                )
            ).fetchall()
            return [r[0] for r in rows]
    finally:
        engine.dispose()


@pytest.mark.integration
class TestSearchVectorMigrationsFullStack:
    """Full-stack round-trip: head → 0007 → head."""

    def test_upgrade_head_adds_all_six_search_vector_columns(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        tables_with_col = _columns_with_search_vector()
        assert set(tables_with_col) >= set(TABLES), (
            f"Missing search_vector columns: {set(TABLES) - set(tables_with_col)}"
        )

    def test_upgrade_head_creates_all_six_gin_indexes(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        indexes = _gin_indexes_for_search_vector()
        # Each migration names its index `<table>_search_idx`.
        for table in TABLES:
            assert any(table in idx for idx in indexes), (
                f"Missing GIN(search_vector) index for {table}; found: {indexes}"
            )

    def test_downgrade_to_0007_removes_all_search_vector_columns(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        _alembic("downgrade", "0007")
        tables_with_col = _columns_with_search_vector()
        assert tables_with_col == [], (
            f"search_vector columns leaked after downgrade 0007: {tables_with_col}"
        )

    def test_downgrade_to_0007_removes_all_gin_indexes(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        _alembic("downgrade", "0007")
        indexes = _gin_indexes_for_search_vector()
        assert indexes == [], f"GIN(search_vector) indexes leaked after downgrade 0007: {indexes}"

    def test_full_round_trip_clean(self, restore_head: None) -> None:
        """head → 0007 → head leaves the schema identical to a fresh head."""
        _alembic("upgrade", "head")
        before = _columns_with_search_vector()
        _alembic("downgrade", "0007")
        _alembic("upgrade", "head")
        after = _columns_with_search_vector()
        assert before == after


@pytest.mark.integration
@pytest.mark.parametrize("rev", SEARCH_VECTOR_REVS)
class TestSearchVectorMigrationsPerRevision:
    """Each migration round-trips cleanly in isolation: upgrade rev →
    downgrade -1 → upgrade rev."""

    def test_per_revision_round_trip(self, rev: str, restore_head: None) -> None:
        _alembic("upgrade", rev)
        _alembic("downgrade", "-1")
        _alembic("upgrade", rev)
        # No assertion on shape — exit code 0 from each alembic call is
        # the contract. The full-stack class above asserts the steady-state.


@pytest.mark.integration
class TestOrmDoesNotDeclareSearchVector:
    """Spec FR-2 invariant: `search_vector` is database-generated; the ORM
    models MUST NOT declare it (writes from the app layer would fail with
    `cannot insert into column "search_vector"`)."""

    def test_no_orm_model_declares_search_vector(self) -> None:
        """Grep-assert the source tree: no `Column(... 'search_vector' ...)`
        anywhere under `backend/app/db/models/`."""
        import re

        models_dir = REPO / "backend" / "app" / "db" / "models"
        offenders: list[str] = []
        for py in models_dir.rglob("*.py"):
            text_content = py.read_text(encoding="utf-8")
            # Look for any line that references search_vector outside a comment.
            for lineno, line in enumerate(text_content.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if re.search(r"\bsearch_vector\b", stripped):
                    offenders.append(f"{py.relative_to(REPO)}:{lineno}: {stripped}")
        assert offenders == [], (
            "ORM models must NOT declare search_vector (spec FR-2). Offenders:\n  "
            + "\n  ".join(offenders)
        )
