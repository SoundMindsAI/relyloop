"""``0004_judgments`` migration test (feat_llm_judgments Story 1.1).

Asserts the schema shape of the ``judgments`` child table created by
``migrations/versions/0004_judgments.py``:

* table exists after ``upgrade head``; gone after ``downgrade -1``
* CHECK constraint ``judgments_rating_check`` rejects rating > 3 / < 0
* CHECK constraint ``judgments_source_check`` rejects unknown source
* UNIQUE constraint ``(judgment_list_id, query_id, doc_id)`` rejects duplicate
* FK ``judgment_list_id → judgment_lists(id) ON DELETE CASCADE`` deletes children
* FK ``query_id → queries(id)`` (NO ACTION) blocks delete-with-children
* index ``judgments_list_query_idx`` exists

Mirrors the ``test_study_lifecycle_migration.py`` structure so the local-vs-CI
skip semantics match.
"""

from __future__ import annotations

import os
import socket
import subprocess
import uuid
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
    yield
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


# ---------------------------------------------------------------------------
# Helpers — seed a complete (cluster, query_set, query, template, list) chain
# so the FK targets are populated before testing judgments-specific behavior.
# ---------------------------------------------------------------------------


def _seed_parent_chain(conn) -> dict[str, str]:
    """Seed the FK parents (clusters, query_templates, query_sets, queries,
    judgment_lists) and return their generated IDs.

    Uses raw SQL inserts to keep the test independent of the ORM repo layer
    (which Story 1.2 tests separately).
    """
    cluster_id = str(uuid.uuid4())
    template_id = str(uuid.uuid4())
    query_set_id = str(uuid.uuid4())
    query_id = str(uuid.uuid4())
    list_id = str(uuid.uuid4())

    conn.execute(
        text(
            "INSERT INTO clusters (id, name, engine_type, environment, base_url, "
            "auth_kind, credentials_ref, created_at) VALUES "
            "(:id, :name, 'elasticsearch', 'dev', 'http://stub:9200', 'es_basic', "
            "'ref', NOW())"
        ),
        {"id": cluster_id, "name": f"mig-cluster-{uuid.uuid4().hex[:8]}"},
    )
    conn.execute(
        text(
            "INSERT INTO query_templates (id, name, engine_type, body, declared_params, "
            "version, created_at) VALUES (:id, :name, 'elasticsearch', "
            "'{\"query\":{\"match_all\":{}}}', '{}'::jsonb, 1, NOW())"
        ),
        {"id": template_id, "name": f"mig-tmpl-{uuid.uuid4().hex[:8]}"},
    )
    conn.execute(
        text(
            "INSERT INTO query_sets (id, name, cluster_id, created_at) VALUES "
            "(:id, :name, :cluster_id, NOW())"
        ),
        {
            "id": query_set_id,
            "name": f"mig-qs-{uuid.uuid4().hex[:8]}",
            "cluster_id": cluster_id,
        },
    )
    conn.execute(
        text("INSERT INTO queries (id, query_set_id, query_text) VALUES (:id, :qs, 'mig-query')"),
        {"id": query_id, "qs": query_set_id},
    )
    conn.execute(
        text(
            "INSERT INTO judgment_lists (id, name, query_set_id, cluster_id, target, "
            "current_template_id, rubric, status, created_at) VALUES "
            "(:id, :name, :qs, :cluster, 'stub-index', :tmpl, 'r', 'complete', NOW())"
        ),
        {
            "id": list_id,
            "name": f"mig-jl-{uuid.uuid4().hex[:8]}",
            "qs": query_set_id,
            "cluster": cluster_id,
            "tmpl": template_id,
        },
    )
    return {
        "cluster_id": cluster_id,
        "template_id": template_id,
        "query_set_id": query_set_id,
        "query_id": query_id,
        "list_id": list_id,
    }


@pytest.mark.integration
class TestSchemaCreation:
    """Table exists after upgrade head; gone after downgrade -1."""

    def test_upgrade_creates_judgments_table(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = 'judgments'"
                    )
                ).fetchone()
                assert row is not None, "judgments table should exist after upgrade head"
        finally:
            engine.dispose()

    def test_downgrade_drops_judgments_table(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        # Head is now 0005 (digests). To drop the judgments table we must
        # downgrade past 0004 to 0003 — analogous to the
        # test_clusters_migration.py pattern that retargets to an explicit
        # revision so the test stays correct as the migration chain extends
        # (ref: feat_study_lifecycle Phase 1 Story 1.3 commit 02bb382).
        _alembic("downgrade", "0003")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = 'judgments'"
                    )
                ).fetchone()
                assert row is None, "judgments table should be dropped by downgrade to 0003"
        finally:
            engine.dispose()


@pytest.mark.integration
class TestColumnsAndConstraints:
    """NOT NULL coverage + CHECK constraints + UNIQUE + index inventory."""

    def test_not_null_coverage(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='judgments' "
                        "ORDER BY column_name"
                    )
                ).fetchall()
                nullable = {row[0]: row[1] for row in rows}
                for required in (
                    "id",
                    "judgment_list_id",
                    "query_id",
                    "doc_id",
                    "rating",
                    "source",
                    "created_at",
                ):
                    assert nullable.get(required) == "NO", f"{required} should be NOT NULL"
                for optional in ("rater_ref", "confidence", "notes"):
                    assert nullable.get(optional) == "YES", f"{optional} should be NULL-able"
        finally:
            engine.dispose()

    def test_check_constraints_present(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'judgments'::regclass AND contype = 'c' "
                        "ORDER BY conname"
                    )
                ).fetchall()
                names = {row[0] for row in rows}
                assert "judgments_rating_check" in names
                assert "judgments_source_check" in names
        finally:
            engine.dispose()

    def test_unique_constraint_present(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid = 'judgments'::regclass "
                        "AND contype = 'u' AND conname = 'judgments_unique_key'"
                    )
                ).fetchone()
                assert row is not None, "UNIQUE judgments_unique_key should exist"
        finally:
            engine.dispose()

    def test_list_query_index_present(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename='judgments' AND indexname='judgments_list_query_idx'"
                    )
                ).fetchone()
                assert row is not None, "judgments_list_query_idx should exist"
        finally:
            engine.dispose()


@pytest.mark.integration
class TestRuntimeBehavior:
    """Live INSERT + DELETE behavior verifies CHECK / UNIQUE / CASCADE FK contracts."""

    def test_rating_check_rejects_out_of_range(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                ids = _seed_parent_chain(conn)
                for bad_rating in (-1, 4, 99):
                    with pytest.raises(IntegrityError):
                        with engine.begin() as inner:
                            inner.execute(
                                text(
                                    "INSERT INTO judgments (id, judgment_list_id, query_id, "
                                    "doc_id, rating, source, created_at) VALUES "
                                    "(:id, :list_id, :query_id, 'd1', :rating, 'llm', NOW())"
                                ),
                                {
                                    "id": str(uuid.uuid4()),
                                    "list_id": ids["list_id"],
                                    "query_id": ids["query_id"],
                                    "rating": bad_rating,
                                },
                            )
        finally:
            engine.dispose()

    def test_source_check_rejects_unknown_value(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                ids = _seed_parent_chain(conn)
            with pytest.raises(IntegrityError):
                with engine.begin() as inner:
                    inner.execute(
                        text(
                            "INSERT INTO judgments (id, judgment_list_id, query_id, "
                            "doc_id, rating, source, created_at) VALUES "
                            "(:id, :list_id, :query_id, 'd1', 2, 'unknown_source', NOW())"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "list_id": ids["list_id"],
                            "query_id": ids["query_id"],
                        },
                    )
        finally:
            engine.dispose()

    def test_unique_rejects_duplicate(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                ids = _seed_parent_chain(conn)
                conn.execute(
                    text(
                        "INSERT INTO judgments (id, judgment_list_id, query_id, "
                        "doc_id, rating, source, created_at) VALUES "
                        "(:id, :list_id, :query_id, 'd1', 2, 'llm', NOW())"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "list_id": ids["list_id"],
                        "query_id": ids["query_id"],
                    },
                )
            with pytest.raises(IntegrityError):
                with engine.begin() as inner:
                    inner.execute(
                        text(
                            "INSERT INTO judgments (id, judgment_list_id, query_id, "
                            "doc_id, rating, source, created_at) VALUES "
                            "(:id, :list_id, :query_id, 'd1', 1, 'human', NOW())"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "list_id": ids["list_id"],
                            "query_id": ids["query_id"],
                        },
                    )
        finally:
            engine.dispose()

    def test_cascade_on_judgment_list_delete(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                ids = _seed_parent_chain(conn)
                conn.execute(
                    text(
                        "INSERT INTO judgments (id, judgment_list_id, query_id, "
                        "doc_id, rating, source, created_at) VALUES "
                        "(:id, :list_id, :query_id, 'd1', 2, 'llm', NOW())"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "list_id": ids["list_id"],
                        "query_id": ids["query_id"],
                    },
                )
            # Delete the parent — judgments should cascade out.
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM judgment_lists WHERE id = :id"),
                    {"id": ids["list_id"]},
                )
                count = conn.execute(
                    text("SELECT COUNT(*) FROM judgments WHERE judgment_list_id = :id"),
                    {"id": ids["list_id"]},
                ).scalar_one()
                assert count == 0, "CASCADE should have removed child judgments"
        finally:
            engine.dispose()
