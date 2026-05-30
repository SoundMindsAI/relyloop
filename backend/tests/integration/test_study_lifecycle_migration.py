# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``0003_study_lifecycle_schema`` migration test (feat_study_lifecycle Phase 1, Story 1.2).

Per cycle-1 GPT-5.5 review F7, this test goes beyond table-existence + CHECK
constraints to assert the full schema shape: NOT NULL coverage, FK targets +
ON DELETE CASCADE behavior, UNIQUE constraints (including composite
``(name, version)`` on query_templates), the ``trials_study_metric`` index,
and live cascade-delete behavior.

Marked ``@pytest.mark.integration`` and skipped automatically when Postgres
is not host-reachable from the test process; see ``test_migrations.py``
module docstring for the rationale.
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


@pytest.mark.integration
class TestSchemaCreation:
    """All 7 tables exist after upgrade head; all 7 are gone after downgrade -1."""

    def test_upgrade_creates_seven_tables(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name IN ('query_templates', 'query_sets', 'queries', "
                        "'judgment_lists', 'studies', 'trials', 'proposals') "
                        "ORDER BY table_name"
                    )
                ).fetchall()
                names = [row[0] for row in rows]
                assert names == [
                    "judgment_lists",
                    "proposals",
                    "queries",
                    "query_sets",
                    "query_templates",
                    "studies",
                    "trials",
                ]
        finally:
            engine.dispose()

    def test_downgrade_removes_seven_tables(self, restore_head: None) -> None:
        # ``head`` is now ``0004_judgments`` so a bare ``downgrade -1`` only
        # peels back the judgments child table; targeting ``0002`` explicitly
        # peels back BOTH 0004 and 0003 so this test still asserts that
        # 0003_study_lifecycle_schema's down path removes its 7 tables.
        # Mirrors the test_clusters_migration retarget that landed when 0003
        # extended the chain.
        _alembic("upgrade", "head")
        _alembic("downgrade", "0002")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name IN ('query_templates', 'query_sets', 'queries', "
                        "'judgment_lists', 'studies', 'trials', 'proposals')"
                    )
                ).fetchall()
                assert rows == []
        finally:
            engine.dispose()


@pytest.mark.integration
class TestCheckConstraints:
    """All 5 CHECK constraints fire on bad values and accept good ones."""

    def test_studies_status_check(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            cluster_id, qt_id, qs_id, jl_id = _seed_study_prereqs(engine)

            for status in ["queued", "running", "completed", "cancelled", "failed"]:
                study_id = str(uuid.uuid4())
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO studies "
                            "(id, name, cluster_id, target, template_id, query_set_id, "
                            " judgment_list_id, search_space, objective, config, status, "
                            " optuna_study_name) VALUES "
                            "(:id, 'n', :c, 't', :qt, :qs, :jl, '{}'::jsonb, '{}'::jsonb, "
                            " '{}'::jsonb, :status, :osn)"
                        ),
                        {
                            "id": study_id,
                            "c": cluster_id,
                            "qt": qt_id,
                            "qs": qs_id,
                            "jl": jl_id,
                            "status": status,
                            "osn": study_id,
                        },
                    )
            with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO studies "
                            "(id, name, cluster_id, target, template_id, query_set_id, "
                            " judgment_list_id, search_space, objective, config, status, "
                            " optuna_study_name) VALUES "
                            "('bad','n',:c,'t',:qt,:qs,:jl,'{}'::jsonb,'{}'::jsonb,"
                            "'{}'::jsonb,'foo','optuna-bad')"
                        ),
                        {"c": cluster_id, "qt": qt_id, "qs": qs_id, "jl": jl_id},
                    )
        finally:
            engine.dispose()

    def test_trials_status_check(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            cluster_id, qt_id, qs_id, jl_id = _seed_study_prereqs(engine)
            study_id = _seed_study(engine, cluster_id, qt_id, qs_id, jl_id)

            for trial_number, status in enumerate(["complete", "failed", "pruned"]):
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO trials (id, study_id, optuna_trial_number, "
                            "params, metrics, status) VALUES "
                            "(:id, :sid, :n, '{}'::jsonb, '{}'::jsonb, :status)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "sid": study_id,
                            "n": trial_number,
                            "status": status,
                        },
                    )
            with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO trials (id, study_id, optuna_trial_number, "
                            "params, metrics, status) VALUES "
                            "('bad', :sid, 99, '{}'::jsonb, '{}'::jsonb, 'archived')"
                        ),
                        {"sid": study_id},
                    )
        finally:
            engine.dispose()

    def test_judgment_lists_status_check(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            cluster_id, _qt_id, qs_id, _jl_id = _seed_study_prereqs(engine)
            for status in ["generating", "complete", "failed"]:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO judgment_lists (id, name, query_set_id, "
                            "cluster_id, target, rubric, status) VALUES "
                            "(:id, :name, :qs, :c, 't', 'r', :status)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "name": f"jl-{status}-extra",
                            "qs": qs_id,
                            "c": cluster_id,
                            "status": status,
                        },
                    )
            with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO judgment_lists (id, name, query_set_id, "
                            "cluster_id, target, rubric, status) VALUES "
                            "('bad', 'jl-bad', :qs, :c, 't', 'r', 'cancelled')"
                        ),
                        {"qs": qs_id, "c": cluster_id},
                    )
        finally:
            engine.dispose()

    def test_proposals_status_check(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            cluster_id, qt_id, _qs, _jl = _seed_study_prereqs(engine)
            for _i, status in enumerate(["pending", "pr_opened", "pr_merged", "rejected"]):
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO proposals (id, cluster_id, template_id, "
                            "config_diff, status) VALUES "
                            "(:id, :c, :qt, '{}'::jsonb, :status)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "c": cluster_id,
                            "qt": qt_id,
                            "status": status,
                        },
                    )
            with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO proposals (id, cluster_id, template_id, "
                            "config_diff, status) VALUES "
                            "('bad', :c, :qt, '{}'::jsonb, 'archived')"
                        ),
                        {"c": cluster_id, "qt": qt_id},
                    )
        finally:
            engine.dispose()

    def test_proposals_pr_state_check(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            cluster_id, qt_id, _qs, _jl = _seed_study_prereqs(engine)
            # NULL accepted (default).
            for pr_state in [None, "open", "closed", "merged"]:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO proposals (id, cluster_id, template_id, "
                            "config_diff, status, pr_state) VALUES "
                            "(:id, :c, :qt, '{}'::jsonb, 'pending', :ps)"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "c": cluster_id,
                            "qt": qt_id,
                            "ps": pr_state,
                        },
                    )
            with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO proposals (id, cluster_id, template_id, "
                            "config_diff, status, pr_state) VALUES "
                            "('bad', :c, :qt, '{}'::jsonb, 'pending', 'archived')"
                        ),
                        {"c": cluster_id, "qt": qt_id},
                    )
        finally:
            engine.dispose()


@pytest.mark.integration
class TestUniqueConstraints:
    """Composite (name, version) on query_templates; singletons on the rest."""

    def test_query_templates_name_version_unique(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO query_templates (id, name, engine_type, body, "
                        "declared_params, version) VALUES "
                        "('qt-1', 'unit-test-tpl', 'elasticsearch', '{}', '{}'::jsonb, 1)"
                    )
                )
                # Same name, different version — OK.
                conn.execute(
                    text(
                        "INSERT INTO query_templates (id, name, engine_type, body, "
                        "declared_params, version) VALUES "
                        "('qt-2', 'unit-test-tpl', 'elasticsearch', '{}', '{}'::jsonb, 2)"
                    )
                )
            # Same (name, version) — UNIQUE violation.
            with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO query_templates (id, name, engine_type, body, "
                            "declared_params, version) VALUES "
                            "('qt-3', 'unit-test-tpl', 'elasticsearch', '{}', '{}'::jsonb, 1)"
                        )
                    )
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM query_templates WHERE id LIKE 'qt-%'"))
        finally:
            engine.dispose()


@pytest.mark.integration
class TestNotNullCoverage:
    """Per plan §3 (cycle-1 GPT-5.5 F7): introspect information_schema.columns
    and assert NOT NULL boundaries match data-model.md for every column on
    each of the 7 tables.
    """

    # (table, column, expected is_nullable). Mirrors data-model.md §"Tables
    # added by feat_study_lifecycle". query_sets.cluster_id ships as NOT NULL
    # in the migration (stricter than the SQL excerpt in data-model.md, which
    # leaves it implicit) — codify the migration's choice.
    _EXPECTED: tuple[tuple[str, str, str], ...] = (
        # query_templates
        ("query_templates", "id", "NO"),
        ("query_templates", "name", "NO"),
        ("query_templates", "engine_type", "NO"),
        ("query_templates", "body", "NO"),
        ("query_templates", "declared_params", "NO"),
        ("query_templates", "version", "NO"),
        ("query_templates", "parent_id", "YES"),
        ("query_templates", "created_at", "NO"),
        # query_sets
        ("query_sets", "id", "NO"),
        ("query_sets", "name", "NO"),
        ("query_sets", "description", "YES"),
        ("query_sets", "cluster_id", "NO"),
        ("query_sets", "created_at", "NO"),
        # queries
        ("queries", "id", "NO"),
        ("queries", "query_set_id", "NO"),
        ("queries", "query_text", "NO"),
        ("queries", "reference_answer", "YES"),
        ("queries", "metadata", "YES"),
        # judgment_lists
        ("judgment_lists", "id", "NO"),
        ("judgment_lists", "name", "NO"),
        ("judgment_lists", "description", "YES"),
        ("judgment_lists", "query_set_id", "NO"),
        ("judgment_lists", "cluster_id", "NO"),
        ("judgment_lists", "target", "NO"),
        ("judgment_lists", "current_template_id", "YES"),
        ("judgment_lists", "rubric", "NO"),
        ("judgment_lists", "status", "NO"),
        ("judgment_lists", "failed_reason", "YES"),
        ("judgment_lists", "calibration", "YES"),
        ("judgment_lists", "created_at", "NO"),
        # studies
        ("studies", "id", "NO"),
        ("studies", "name", "NO"),
        ("studies", "cluster_id", "NO"),
        ("studies", "target", "NO"),
        ("studies", "template_id", "NO"),
        ("studies", "query_set_id", "NO"),
        ("studies", "judgment_list_id", "NO"),
        ("studies", "search_space", "NO"),
        ("studies", "objective", "NO"),
        ("studies", "config", "NO"),
        ("studies", "status", "NO"),
        ("studies", "failed_reason", "YES"),
        ("studies", "optuna_study_name", "NO"),
        ("studies", "parent_study_id", "YES"),
        ("studies", "baseline_metric", "YES"),
        ("studies", "baseline_trial_id", "YES"),  # feat_study_baseline_trial 0020
        ("studies", "best_metric", "YES"),
        ("studies", "best_trial_id", "YES"),
        ("studies", "created_at", "NO"),
        ("studies", "started_at", "YES"),
        ("studies", "completed_at", "YES"),
        # trials
        ("trials", "id", "NO"),
        ("trials", "study_id", "NO"),
        ("trials", "optuna_trial_number", "NO"),
        ("trials", "params", "NO"),
        ("trials", "primary_metric", "YES"),
        ("trials", "metrics", "NO"),
        ("trials", "duration_ms", "YES"),
        ("trials", "status", "NO"),
        ("trials", "error", "YES"),
        ("trials", "started_at", "YES"),
        ("trials", "ended_at", "YES"),
        ("trials", "is_baseline", "NO"),  # feat_study_baseline_trial 0020
        # proposals
        ("proposals", "id", "NO"),
        ("proposals", "study_id", "YES"),
        ("proposals", "study_trial_id", "YES"),
        ("proposals", "cluster_id", "NO"),
        ("proposals", "template_id", "NO"),
        ("proposals", "config_diff", "NO"),
        ("proposals", "metric_delta", "YES"),
        ("proposals", "status", "NO"),
        ("proposals", "pr_url", "YES"),
        ("proposals", "pr_state", "YES"),
        ("proposals", "pr_merged_at", "YES"),
        ("proposals", "pr_open_error", "YES"),
        ("proposals", "rejected_reason", "YES"),
        ("proposals", "created_at", "NO"),
    )

    def test_not_null_boundaries(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_name, column_name, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_schema = 'public' "
                        "AND table_name IN ('query_templates', 'query_sets', 'queries', "
                        "'judgment_lists', 'studies', 'trials', 'proposals')"
                    )
                ).fetchall()
                actual = {(t, c): n for t, c, n in rows}
            for table, column, expected in self._EXPECTED:
                got = actual.get((table, column))
                assert got == expected, (
                    f"{table}.{column}: expected is_nullable={expected!r}, got {got!r}"
                )
        finally:
            engine.dispose()


@pytest.mark.integration
class TestForeignKeyTargets:
    """Per plan §3: introspect information_schema.referential_constraints +
    key_column_usage to verify every FK target and ON DELETE rule.
    """

    # (constraint_name_substring, table, column, ref_table, ref_column, delete_rule).
    # Constraint names follow Alembic's auto-generated <table>_<col>_fkey
    # convention; we match by table+column rather than exact name to stay
    # robust to future renames.
    _EXPECTED_FKS: tuple[tuple[str, str, str, str, str], ...] = (
        # CASCADE behavior
        ("queries", "query_set_id", "query_sets", "id", "CASCADE"),
        ("trials", "study_id", "studies", "id", "CASCADE"),
        # NO ACTION (default) — studies' five outgoing FKs
        ("studies", "cluster_id", "clusters", "id", "NO ACTION"),
        ("studies", "template_id", "query_templates", "id", "NO ACTION"),
        ("studies", "query_set_id", "query_sets", "id", "NO ACTION"),
        ("studies", "judgment_list_id", "judgment_lists", "id", "NO ACTION"),
        ("studies", "parent_study_id", "studies", "id", "NO ACTION"),
        # judgment_lists' three outgoing FKs
        ("judgment_lists", "query_set_id", "query_sets", "id", "NO ACTION"),
        ("judgment_lists", "cluster_id", "clusters", "id", "NO ACTION"),
        ("judgment_lists", "current_template_id", "query_templates", "id", "NO ACTION"),
        # query_templates self-FK + query_sets cluster FK
        ("query_templates", "parent_id", "query_templates", "id", "NO ACTION"),
        ("query_sets", "cluster_id", "clusters", "id", "NO ACTION"),
        # proposals' four outgoing FKs
        ("proposals", "study_id", "studies", "id", "NO ACTION"),
        ("proposals", "study_trial_id", "trials", "id", "NO ACTION"),
        ("proposals", "cluster_id", "clusters", "id", "NO ACTION"),
        ("proposals", "template_id", "query_templates", "id", "NO ACTION"),
    )

    def test_foreign_key_targets_and_delete_rules(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                # Join referential_constraints + key_column_usage so we can
                # match by (table, column) rather than relying on Alembic's
                # auto-generated constraint name format.
                rows = conn.execute(
                    text(
                        "SELECT kcu.table_name, kcu.column_name, "
                        "ccu.table_name AS ref_table, ccu.column_name AS ref_column, "
                        "rc.delete_rule "
                        "FROM information_schema.referential_constraints rc "
                        "JOIN information_schema.key_column_usage kcu "
                        "  ON rc.constraint_name = kcu.constraint_name "
                        " AND rc.constraint_schema = kcu.constraint_schema "
                        "JOIN information_schema.constraint_column_usage ccu "
                        "  ON rc.unique_constraint_name = ccu.constraint_name "
                        " AND rc.unique_constraint_schema = ccu.constraint_schema "
                        "WHERE rc.constraint_schema = 'public' "
                        "AND kcu.table_name IN ('query_templates', 'query_sets', "
                        "'queries', 'judgment_lists', 'studies', 'trials', 'proposals')"
                    )
                ).fetchall()
                actual = {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}
            for table, column, ref_table, ref_column, delete_rule in self._EXPECTED_FKS:
                got = actual.get((table, column))
                assert got is not None, f"FK {table}.{column} → {ref_table}.{ref_column} not found"
                got_ref_table, got_ref_column, got_delete_rule = got
                assert got_ref_table == ref_table, (
                    f"{table}.{column}: expected ref_table={ref_table}, got {got_ref_table}"
                )
                assert got_ref_column == ref_column, (
                    f"{table}.{column}: expected ref_column={ref_column}, got {got_ref_column}"
                )
                assert got_delete_rule == delete_rule, (
                    f"{table}.{column}: expected delete_rule={delete_rule}, got {got_delete_rule}"
                )
        finally:
            engine.dispose()


@pytest.mark.integration
class TestUniqueConstraintCatalog:
    """Per plan §3: introspect pg_constraint for the 4 documented UNIQUE
    constraints (composite + 3 single-column).
    """

    def test_unique_constraint_inventory(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                # pg_constraint stores key columns as an int[] of attnums;
                # join through pg_attribute to materialize column names.
                rows = conn.execute(
                    text(
                        "SELECT t.relname AS table_name, "
                        "ARRAY_AGG(a.attname ORDER BY u.ord) AS columns "
                        "FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord) ON TRUE "
                        "JOIN pg_attribute a "
                        "  ON a.attrelid = c.conrelid AND a.attnum = u.attnum "
                        "WHERE c.contype = 'u' "
                        "AND n.nspname = 'public' "
                        "AND t.relname IN ('query_templates', 'query_sets', "
                        "'judgment_lists', 'studies') "
                        "GROUP BY t.relname, c.oid"
                    )
                ).fetchall()
                actual = {(r[0], tuple(r[1])) for r in rows}
            expected = {
                ("query_templates", ("name", "version")),
                ("query_sets", ("name",)),
                ("judgment_lists", ("name",)),
                ("studies", ("optuna_study_name",)),
            }
            missing = expected - actual
            assert not missing, f"missing UNIQUE constraints: {missing}"
        finally:
            engine.dispose()


@pytest.mark.integration
class TestForeignKeysAndCascade:
    """ON DELETE CASCADE for query_set→query and study→trial; FK targets resolve."""

    def test_query_set_delete_cascades_queries(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            cluster_id = _seed_cluster(engine)
            qs_id = str(uuid.uuid4())
            q_id = str(uuid.uuid4())
            with engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO query_sets (id, name, cluster_id) VALUES (:id, :name, :c)"),
                    {"id": qs_id, "name": f"qs-{qs_id[:8]}", "c": cluster_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO queries (id, query_set_id, query_text) "
                        "VALUES (:id, :qs, 'hello')"
                    ),
                    {"id": q_id, "qs": qs_id},
                )
            # Delete the parent set; the child query should cascade.
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM query_sets WHERE id = :id"), {"id": qs_id})
            with engine.connect() as conn:
                count = conn.execute(
                    text("SELECT COUNT(*) FROM queries WHERE id = :id"),
                    {"id": q_id},
                ).scalar_one()
                assert count == 0, "query was not cascade-deleted with its query_set"
        finally:
            engine.dispose()

    def test_study_delete_cascades_trials(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            cluster_id, qt_id, qs_id, jl_id = _seed_study_prereqs(engine)
            study_id = _seed_study(engine, cluster_id, qt_id, qs_id, jl_id)
            trial_id = str(uuid.uuid4())
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO trials (id, study_id, optuna_trial_number, "
                        "params, metrics, status) VALUES "
                        "(:id, :sid, 0, '{}'::jsonb, '{}'::jsonb, 'complete')"
                    ),
                    {"id": trial_id, "sid": study_id},
                )
            # Delete the parent study; trials should cascade.
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM studies WHERE id = :id"), {"id": study_id})
            with engine.connect() as conn:
                count = conn.execute(
                    text("SELECT COUNT(*) FROM trials WHERE id = :id"),
                    {"id": trial_id},
                ).scalar_one()
                assert count == 0, "trial was not cascade-deleted with its study"
        finally:
            engine.dispose()


@pytest.mark.integration
class TestIndexes:
    """The trials_study_metric index is created with the documented column ordering."""

    def test_trials_study_metric_index_exists(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE tablename = 'trials' AND indexname = 'trials_study_metric'"
                    )
                ).fetchall()
                assert len(rows) == 1
                indexdef = rows[0][1]
                # PG normalizes the index definition; check the key bits are present.
                assert "study_id" in indexdef
                assert "primary_metric" in indexdef
                assert "DESC NULLS LAST" in indexdef
        finally:
            engine.dispose()


# ---------------------------------------------------------------------------
# Seed helpers — keep tests focused on the assertion under test.
# ---------------------------------------------------------------------------


def _seed_cluster(engine) -> str:
    cid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO clusters (id, name, engine_type, environment, base_url, "
                "auth_kind, credentials_ref) VALUES "
                "(:id, :name, 'elasticsearch', 'dev', 'http://x', 'es_basic', 'ref')"
            ),
            {"id": cid, "name": f"c-{cid[:8]}"},
        )
    return cid


def _seed_study_prereqs(engine) -> tuple[str, str, str, str]:
    """Return (cluster_id, query_template_id, query_set_id, judgment_list_id)."""
    cluster_id = _seed_cluster(engine)
    qt_id = str(uuid.uuid4())
    qs_id = str(uuid.uuid4())
    jl_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO query_templates (id, name, engine_type, body, declared_params) "
                "VALUES (:id, :name, 'elasticsearch', '{}', '{}'::jsonb)"
            ),
            {"id": qt_id, "name": f"qt-{qt_id[:8]}"},
        )
        conn.execute(
            text("INSERT INTO query_sets (id, name, cluster_id) VALUES (:id, :name, :c)"),
            {"id": qs_id, "name": f"qs-{qs_id[:8]}", "c": cluster_id},
        )
        conn.execute(
            text(
                "INSERT INTO judgment_lists (id, name, query_set_id, cluster_id, "
                "target, rubric, status) VALUES "
                "(:id, :name, :qs, :c, 't', 'r', 'complete')"
            ),
            {"id": jl_id, "name": f"jl-{jl_id[:8]}", "qs": qs_id, "c": cluster_id},
        )
    return cluster_id, qt_id, qs_id, jl_id


def _seed_study(engine, cluster_id: str, qt_id: str, qs_id: str, jl_id: str) -> str:
    sid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO studies "
                "(id, name, cluster_id, target, template_id, query_set_id, "
                " judgment_list_id, search_space, objective, config, status, "
                " optuna_study_name) VALUES "
                "(:id, 'n', :c, 't', :qt, :qs, :jl, '{}'::jsonb, '{}'::jsonb, "
                " '{}'::jsonb, 'queued', :osn)"
            ),
            {"id": sid, "c": cluster_id, "qt": qt_id, "qs": qs_id, "jl": jl_id, "osn": sid},
        )
    return sid
