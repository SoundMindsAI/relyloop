"""``0015_trials_per_query_metrics`` migration test (feat_pr_metric_confidence Story 1.1).

Asserts the schema shape of the ``trials.per_query_metrics`` column added by
``migrations/versions/0015_trials_per_query_metrics.py``:

* upgrade head adds the nullable JSONB column + CHECK constraint
* downgrade to 0014 drops the CHECK constraint and the column
* upgrade → downgrade → upgrade round-trip preserves the other 10 trial columns
  and leaves ``per_query_metrics`` NULL on existing rows (AC-17 from the spec)
* the CHECK constraint rejects non-object JSONB inserts (AC for INV-1)

Mirrors ``test_clusters_target_filter_migration.py`` for skip semantics +
alembic invocation.
"""

from __future__ import annotations

import json
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
    """Always leave the DB at head, even if the test failed mid-downgrade."""
    yield
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


def _column_info(conn) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'trials'"
        )
    ).fetchall()
    return {r[0]: {"data_type": r[1], "nullable": r[2]} for r in rows}


def _check_constraint_names(conn) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'public.trials'::regclass AND contype = 'c'"
        )
    ).fetchall()
    return {r[0] for r in rows}


@pytest.mark.integration
class TestTrialsPerQueryMetricsMigration:
    def test_upgrade_adds_nullable_jsonb_column_with_check(self, restore_head: None) -> None:
        """0015 upgrade adds ``per_query_metrics`` as a nullable jsonb column
        AND adds the ``trials_per_query_metrics_object_check`` CHECK constraint."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _column_info(conn)
                assert "per_query_metrics" in cols, (
                    "0015 upgrade should add trials.per_query_metrics"
                )
                col = cols["per_query_metrics"]
                assert col["data_type"] == "jsonb"
                assert col["nullable"] == "YES"

                checks = _check_constraint_names(conn)
                assert "trials_per_query_metrics_object_check" in checks, (
                    "0015 upgrade should add the per_query_metrics CHECK constraint"
                )
        finally:
            engine.dispose()

    def test_downgrade_drops_check_and_column(self, restore_head: None) -> None:
        """downgrade to 0014 drops the CHECK constraint and the column."""
        _alembic("upgrade", "head")
        _alembic("downgrade", "0014")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _column_info(conn)
                assert "per_query_metrics" not in cols, (
                    "downgrade to 0014 should drop trials.per_query_metrics"
                )
                checks = _check_constraint_names(conn)
                assert "trials_per_query_metrics_object_check" not in checks, (
                    "downgrade to 0014 should drop the per_query_metrics CHECK"
                )
        finally:
            engine.dispose()

    def test_roundtrip_preserves_other_columns(self, restore_head: None) -> None:
        """Upgrade → downgrade → upgrade leaves the other 10 trials columns intact
        AND ``per_query_metrics`` present + nullable on the final upgrade (AC-17)."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                before = set(_column_info(conn).keys())
        finally:
            engine.dispose()

        _alembic("downgrade", "0014")
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
                assert after["per_query_metrics"]["nullable"] == "YES"
        finally:
            engine.dispose()

    def test_check_constraint_rejects_non_object_jsonb(self, restore_head: None) -> None:
        """``per_query_metrics`` must be NULL or a JSON object — arrays, scalars,
        and booleans MUST be rejected by the CHECK constraint.

        Per cycle-3 GPT-5.5 F3 adjudication: SQLAlchemy wraps the asyncpg
        ``CheckViolationError`` as ``sqlalchemy.exc.IntegrityError``; assert on
        the wrapping type and inspect ``.orig`` for the underlying cause.
        """
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                # Seed the minimal FK chain trials needs: cluster → query_set →
                # judgment_list → query_template → study, then a trial row whose
                # per_query_metrics will violate the CHECK.
                suffix = uuid.uuid4().hex[:8]
                cluster_id = str(uuid.uuid4())
                qs_id = str(uuid.uuid4())
                tpl_id = str(uuid.uuid4())
                jl_id = str(uuid.uuid4())
                study_id = str(uuid.uuid4())
                trial_id = str(uuid.uuid4())

                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO clusters (id, name, engine_type, environment, "
                            "base_url, auth_kind, credentials_ref) VALUES "
                            "(:id, :name, 'elasticsearch', 'dev', "
                            "'http://elasticsearch:9200', 'es_basic', 'local-es')"
                        ),
                        {"id": cluster_id, "name": f"migration-check-{suffix}"},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO query_sets (id, name, cluster_id) "
                            "VALUES (:id, :name, :cid)"
                        ),
                        {"id": qs_id, "name": f"qs-{suffix}", "cid": cluster_id},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO query_templates (id, name, engine_type, body, "
                            "declared_params) VALUES (:id, :name, 'elasticsearch', "
                            ":body, :params)"
                        ),
                        {
                            "id": tpl_id,
                            "name": f"tpl-{suffix}",
                            "body": '{"query":{"match_all":{}}}',
                            "params": json.dumps({}),
                        },
                    )
                    conn.execute(
                        text(
                            "INSERT INTO judgment_lists (id, name, query_set_id, "
                            "cluster_id, target, rubric, status) VALUES "
                            "(:id, :name, :qs, :cid, 'idx', 'r', 'ready')"
                        ),
                        {
                            "id": jl_id,
                            "name": f"jl-{suffix}",
                            "qs": qs_id,
                            "cid": cluster_id,
                        },
                    )
                    conn.execute(
                        text(
                            "INSERT INTO studies (id, name, cluster_id, target, "
                            "template_id, query_set_id, judgment_list_id, search_space, "
                            "objective, config, status, optuna_study_name) VALUES "
                            "(:id, :name, :cid, 'idx', :tpl, :qs, :jl, "
                            ":space, :obj, :cfg, 'queued', :osn)"
                        ),
                        {
                            "id": study_id,
                            "name": f"study-{suffix}",
                            "cid": cluster_id,
                            "tpl": tpl_id,
                            "qs": qs_id,
                            "jl": jl_id,
                            "space": json.dumps({"params": {}}),
                            "obj": json.dumps({"metric": "ndcg", "k": 10, "direction": "maximize"}),
                            "cfg": json.dumps({"max_trials": 1}),
                            "osn": study_id,
                        },
                    )

                # Attempt the CHECK-violating insert. A JSON array should fail.
                with pytest.raises(IntegrityError) as exc_info:
                    with conn.begin():
                        conn.execute(
                            text(
                                "INSERT INTO trials (id, study_id, optuna_trial_number, "
                                "params, metrics, status, per_query_metrics) VALUES "
                                "(:id, :sid, 0, :params, :metrics, 'complete', "
                                ":pq::jsonb)"
                            ),
                            {
                                "id": trial_id,
                                "sid": study_id,
                                "params": json.dumps({}),
                                "metrics": json.dumps({"ndcg": 0.5}),
                                "pq": "[]",
                            },
                        )

                # Confirm the CHECK fired (not an FK / NOT NULL / etc.)
                assert (
                    "trials_per_query_metrics_object_check" in str(exc_info.value.orig)
                    or "check constraint" in str(exc_info.value.orig).lower()
                ), f"expected per_query_metrics CHECK violation; got {exc_info.value.orig}"

                # Cleanup — best-effort delete of the seeded FK chain.
                with conn.begin():
                    conn.execute(text("DELETE FROM studies WHERE id = :id"), {"id": study_id})
                    conn.execute(text("DELETE FROM judgment_lists WHERE id = :id"), {"id": jl_id})
                    conn.execute(text("DELETE FROM query_templates WHERE id = :id"), {"id": tpl_id})
                    conn.execute(text("DELETE FROM query_sets WHERE id = :id"), {"id": qs_id})
                    conn.execute(text("DELETE FROM clusters WHERE id = :id"), {"id": cluster_id})
        finally:
            engine.dispose()
