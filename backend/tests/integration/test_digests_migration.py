# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``0005_digests`` migration test (feat_digest_proposal Story 1.1).

Asserts the schema shape of the ``digests`` table created by
``migrations/versions/0005_digests.py``:

* table exists after ``upgrade head``; gone after ``downgrade -1``
* NOT NULL coverage matches the spec / data-model.md
* UNIQUE constraint on ``study_id`` (one digest per study)
* FK ``study_id → studies(id)`` is enforced
* ``suggested_followups`` defaults to empty array (cycle-1 F1)
* Round-trip ``upgrade head → downgrade -1 → upgrade head`` is clean
  (CLAUDE.md Absolute Rule #5)

Mirrors the ``test_judgments_migration.py`` structure so the local-vs-CI
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


def _seed_study(conn) -> str:
    """Insert the minimal parent chain a digest needs and return the study_id.

    digests.study_id has a FK to studies; studies has FKs to clusters,
    query_sets, query_templates, judgment_lists. Seed each via raw SQL so
    the test stays decoupled from the repo layer (covered by Story 1.2).
    """
    cluster_id = str(uuid.uuid4())
    template_id = str(uuid.uuid4())
    query_set_id = str(uuid.uuid4())
    list_id = str(uuid.uuid4())
    study_id = str(uuid.uuid4())

    conn.execute(
        text(
            "INSERT INTO clusters (id, name, engine_type, environment, base_url, "
            "auth_kind, credentials_ref, created_at) VALUES "
            "(:id, :name, 'elasticsearch', 'dev', 'http://stub:9200', 'es_basic', "
            "'ref', NOW())"
        ),
        {"id": cluster_id, "name": f"dig-cluster-{uuid.uuid4().hex[:8]}"},
    )
    conn.execute(
        text(
            "INSERT INTO query_templates (id, name, engine_type, body, declared_params, "
            "version, created_at) VALUES (:id, :name, 'elasticsearch', "
            "'{\"query\":{\"match_all\":{}}}', '{}'::jsonb, 1, NOW())"
        ),
        {"id": template_id, "name": f"dig-tmpl-{uuid.uuid4().hex[:8]}"},
    )
    conn.execute(
        text(
            "INSERT INTO query_sets (id, name, cluster_id, created_at) VALUES "
            "(:id, :name, :cluster_id, NOW())"
        ),
        {
            "id": query_set_id,
            "name": f"dig-qs-{uuid.uuid4().hex[:8]}",
            "cluster_id": cluster_id,
        },
    )
    conn.execute(
        text(
            "INSERT INTO judgment_lists (id, name, query_set_id, cluster_id, target, "
            "current_template_id, rubric, status, created_at) VALUES "
            "(:id, :name, :qs, :cluster, 'stub-index', :tmpl, 'r', 'complete', NOW())"
        ),
        {
            "id": list_id,
            "name": f"dig-jl-{uuid.uuid4().hex[:8]}",
            "qs": query_set_id,
            "cluster": cluster_id,
            "tmpl": template_id,
        },
    )
    conn.execute(
        text(
            "INSERT INTO studies (id, name, cluster_id, target, template_id, "
            "query_set_id, judgment_list_id, search_space, objective, config, "
            "status, optuna_study_name, created_at) VALUES "
            "(:id, :name, :cluster, 'stub-index', :tmpl, :qs, :jl, "
            "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
            "'completed', :osn, NOW())"
        ),
        {
            "id": study_id,
            "name": f"dig-study-{uuid.uuid4().hex[:8]}",
            "cluster": cluster_id,
            "tmpl": template_id,
            "qs": query_set_id,
            "jl": list_id,
            "osn": study_id,
        },
    )
    return study_id


@pytest.mark.integration
class TestSchemaCreation:
    """Table exists after upgrade head; gone after downgrade -1."""

    def test_upgrade_creates_digests_table(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = 'digests'"
                    )
                ).fetchone()
                assert row is not None, "digests table should exist after upgrade head"
        finally:
            engine.dispose()

    def test_downgrade_drops_digests_table(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        # Explicitly target 0004 so this test stays correct as the chain
        # extends past 0005 (e.g. feat_github_webhook's 0006 means
        # ``downgrade -1`` from head no longer drops digests).
        _alembic("downgrade", "0004")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = 'digests'"
                    )
                ).fetchone()
                assert row is None, "digests table should be dropped by downgrade -1"
        finally:
            engine.dispose()

    def test_round_trip(self, restore_head: None) -> None:
        """upgrade head → downgrade -1 → upgrade head clean (Absolute Rule #5)."""
        _alembic("upgrade", "head")
        _alembic("downgrade", "-1")
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = 'digests'"
                    )
                ).fetchone()
                assert row is not None
        finally:
            engine.dispose()


@pytest.mark.integration
class TestColumnsAndConstraints:
    """NOT NULL coverage + UNIQUE on study_id + suggested_followups default."""

    def test_not_null_coverage(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='digests' "
                        "ORDER BY column_name"
                    )
                ).fetchall()
                nullable = {row[0]: row[1] for row in rows}
                # Every column on digests is NOT NULL per data-model.md.
                for required in (
                    "id",
                    "study_id",
                    "narrative",
                    "parameter_importance",
                    "recommended_config",
                    "suggested_followups",
                    "generated_by",
                    "generated_at",
                ):
                    assert nullable.get(required) == "NO", f"{required} should be NOT NULL"
        finally:
            engine.dispose()

    def test_study_id_unique_constraint(self, restore_head: None) -> None:
        """One digest per study (UNIQUE on study_id) — spec §9 + data-model.md."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                study_id = _seed_study(conn)
                first = str(uuid.uuid4())
                second = str(uuid.uuid4())
                conn.execute(
                    text(
                        "INSERT INTO digests (id, study_id, narrative, parameter_importance, "
                        "recommended_config, generated_by, generated_at) VALUES "
                        "(:id, :sid, 'n', '{}'::jsonb, '{}'::jsonb, 'local:test', NOW())"
                    ),
                    {"id": first, "sid": study_id},
                )
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO digests (id, study_id, narrative, "
                            "parameter_importance, recommended_config, generated_by, "
                            "generated_at) VALUES (:id, :sid, 'n', '{}'::jsonb, "
                            "'{}'::jsonb, 'local:test', NOW())"
                        ),
                        {"id": second, "sid": study_id},
                    )
        finally:
            engine.dispose()

    def test_suggested_followups_defaults_to_empty_array(self, restore_head: None) -> None:
        """Cycle-1 F1: column NOT NULL with empty-array server default."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                study_id = _seed_study(conn)
                digest_id = str(uuid.uuid4())
                conn.execute(
                    text(
                        "INSERT INTO digests (id, study_id, narrative, "
                        "parameter_importance, recommended_config, generated_by, "
                        "generated_at) VALUES (:id, :sid, 'n', '{}'::jsonb, "
                        "'{}'::jsonb, 'local:test', NOW())"
                    ),
                    {"id": digest_id, "sid": study_id},
                )
                row = conn.execute(
                    text("SELECT suggested_followups FROM digests WHERE id = :id"),
                    {"id": digest_id},
                ).fetchone()
                assert row is not None
                assert row[0] == [], "suggested_followups should default to empty array"
        finally:
            engine.dispose()

    def test_study_id_fk_enforced(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO digests (id, study_id, narrative, "
                            "parameter_importance, recommended_config, generated_by, "
                            "generated_at) VALUES (:id, :sid, 'n', '{}'::jsonb, "
                            "'{}'::jsonb, 'local:test', NOW())"
                        ),
                        {"id": str(uuid.uuid4()), "sid": str(uuid.uuid4())},
                    )
        finally:
            engine.dispose()
