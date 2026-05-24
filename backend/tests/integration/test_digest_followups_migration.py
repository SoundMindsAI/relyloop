"""``0019_digests_suggested_followups_jsonb`` migration round-trip test (Story 3.6).

Drives the column-type migration over two seeded ``digests`` rows (one
populated text array, one empty) so both PL/pgSQL helper branches are
exercised, then drives the symmetric downgrade and asserts the rationale-
only round-trip.

Mirrors the subprocess-driven pattern in ``test_digests_migration.py``
because column-type changes need a real Alembic transition (the ORM-level
write path always emits the head column type).
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
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
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
    """Wipe any seeded digests + restore to head at the end of the test."""
    yield
    engine = create_engine(_sync_database_url(), future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM digests"))
            conn.execute(text("DELETE FROM proposals"))
            conn.execute(text("DELETE FROM trials"))
            conn.execute(text("DELETE FROM studies"))
            conn.execute(text("DELETE FROM judgment_lists"))
            conn.execute(text("DELETE FROM query_sets"))
            conn.execute(text("DELETE FROM query_templates"))
            conn.execute(text("DELETE FROM clusters"))
    finally:
        engine.dispose()
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


def _seed_chain(conn) -> str:
    """Insert cluster + template + query_set + judgment_list + study, return study_id."""
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
            "name": f"mig-study-{uuid.uuid4().hex[:8]}",
            "cluster": cluster_id,
            "tmpl": template_id,
            "qs": query_set_id,
            "jl": list_id,
            "osn": study_id,
        },
    )
    return study_id


@pytest.mark.integration
class TestDigestFollowupsMigrationRoundTrip:
    """Migration 0019 wraps text rows + collapses on downgrade, both fixtures."""

    def test_upgrade_wraps_populated_and_empty_rows(self, restore_head: None) -> None:
        # Roll back to 0018 (pre-JSONB), seed two rows in the text[] shape.
        _alembic("downgrade", "0018")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                study_a = _seed_chain(conn)
                study_b = _seed_chain(conn)
                digest_a = str(uuid.uuid4())
                digest_b = str(uuid.uuid4())
                conn.execute(
                    text(
                        "INSERT INTO digests (id, study_id, narrative, parameter_importance, "
                        "recommended_config, suggested_followups, generated_by, generated_at) "
                        "VALUES (:id, :sid, 'n', '{}'::jsonb, '{}'::jsonb, "
                        ":sf, 'local:test', NOW())"
                    ),
                    {
                        "id": digest_a,
                        "sid": study_a,
                        "sf": ["try widen title_boost", "add tie_breaker"],
                    },
                )
                conn.execute(
                    text(
                        "INSERT INTO digests (id, study_id, narrative, parameter_importance, "
                        "recommended_config, suggested_followups, generated_by, generated_at) "
                        "VALUES (:id, :sid, 'n', '{}'::jsonb, '{}'::jsonb, "
                        ":sf, 'local:test', NOW())"
                    ),
                    {"id": digest_b, "sid": study_b, "sf": []},
                )
        finally:
            engine.dispose()

        # Apply 0019 — wraps text rows.
        _alembic("upgrade", "0019")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row_a = conn.execute(
                    text("SELECT suggested_followups FROM digests WHERE id = :id"),
                    {"id": digest_a},
                ).scalar_one()
                row_b = conn.execute(
                    text("SELECT suggested_followups FROM digests WHERE id = :id"),
                    {"id": digest_b},
                ).scalar_one()
                assert row_a == [
                    {"kind": "text", "rationale": "try widen title_boost", "search_space": None},
                    {"kind": "text", "rationale": "add tie_breaker", "search_space": None},
                ]
                assert row_b == []
        finally:
            engine.dispose()

        # Downgrade — collapses to rationale-only text array.
        _alembic("downgrade", "0018")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row_a = conn.execute(
                    text("SELECT suggested_followups FROM digests WHERE id = :id"),
                    {"id": digest_a},
                ).scalar_one()
                row_b = conn.execute(
                    text("SELECT suggested_followups FROM digests WHERE id = :id"),
                    {"id": digest_b},
                ).scalar_one()
                assert row_a == ["try widen title_boost", "add tie_breaker"]
                assert row_b == []
        finally:
            engine.dispose()

        # Re-upgrade — JSONB shape restored.
        _alembic("upgrade", "0019")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row_a = conn.execute(
                    text("SELECT suggested_followups FROM digests WHERE id = :id"),
                    {"id": digest_a},
                ).scalar_one()
                assert row_a == [
                    {"kind": "text", "rationale": "try widen title_boost", "search_space": None},
                    {"kind": "text", "rationale": "add tie_breaker", "search_space": None},
                ]
        finally:
            engine.dispose()
