"""``0020_studies_baseline_trial`` migration test (feat_study_baseline_trial Story 1.1).

Asserts the schema shape of the two columns + partial unique index added by
``migrations/versions/0020_studies_baseline_trial.py``:

* upgrade head adds ``studies.baseline_trial_id VARCHAR(36) NULL``
* upgrade head adds ``trials.is_baseline BOOLEAN NOT NULL DEFAULT FALSE``
* upgrade head creates ``uq_trials_study_baseline_complete`` partial unique
  index with the correct WHERE predicate
* downgrade to 0019 drops all three artifacts
* upgrade → downgrade → upgrade round-trip preserves the other studies +
  trials columns
* Idempotent re-run: running upgrade head twice does not raise
  (the DO $$ ... IF NOT EXISTS $$ guards + CREATE INDEX IF NOT EXISTS make
  the migration safe to re-apply, per AC-13).

Mirrors ``test_clusters_target_filter_migration.py`` for skip semantics +
alembic invocation.
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
def restore_head() -> Iterator[None]:
    yield
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


def _studies_columns(conn) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'studies'"
        )
    ).fetchall()
    return {r[0]: {"data_type": r[1], "max_length": r[2], "nullable": r[3]} for r in rows}


def _trials_columns(conn) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'trials'"
        )
    ).fetchall()
    return {r[0]: {"data_type": r[1], "nullable": r[2], "default": r[3]} for r in rows}


def _partial_index_predicate(conn, index_name: str) -> str | None:
    """Return the WHERE predicate of a partial index, or None if missing."""
    row = conn.execute(
        text("SELECT pg_get_indexdef(c.oid) FROM pg_class c WHERE c.relname = :name"),
        {"name": index_name},
    ).fetchone()
    return row[0] if row else None


@pytest.mark.integration
class TestBaselineTrialMigration:
    def test_upgrade_adds_baseline_trial_id_column(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _studies_columns(conn)
                assert "baseline_trial_id" in cols, (
                    "0020 upgrade should add studies.baseline_trial_id"
                )
                col = cols["baseline_trial_id"]
                assert col["data_type"] == "character varying"
                assert col["max_length"] == 36
                assert col["nullable"] == "YES"
        finally:
            engine.dispose()

    def test_upgrade_adds_is_baseline_column(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _trials_columns(conn)
                assert "is_baseline" in cols, "0020 upgrade should add trials.is_baseline"
                col = cols["is_baseline"]
                assert col["data_type"] == "boolean"
                assert col["nullable"] == "NO"
                assert col["default"] is not None and "false" in str(col["default"]).lower()
        finally:
            engine.dispose()

    def test_upgrade_creates_partial_unique_index(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                indexdef = _partial_index_predicate(conn, "uq_trials_study_baseline_complete")
                assert indexdef is not None, (
                    "0020 upgrade should create uq_trials_study_baseline_complete"
                )
                # Predicate must include both is_baseline and status='complete'.
                lower = indexdef.lower()
                assert "is_baseline" in lower and "complete" in lower, (
                    f"index predicate missing expected clauses: {indexdef!r}"
                )
                assert "unique" in lower, f"index should be UNIQUE: {indexdef!r}"
        finally:
            engine.dispose()

    def test_downgrade_drops_columns_and_index(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        _alembic("downgrade", "0019")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                assert "baseline_trial_id" not in _studies_columns(conn)
                assert "is_baseline" not in _trials_columns(conn)
                assert _partial_index_predicate(conn, "uq_trials_study_baseline_complete") is None
        finally:
            engine.dispose()

    def test_round_trip_preserves_other_columns(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                before_studies = set(_studies_columns(conn).keys())
                before_trials = set(_trials_columns(conn).keys())
        finally:
            engine.dispose()

        _alembic("downgrade", "0019")
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                after_studies = set(_studies_columns(conn).keys())
                after_trials = set(_trials_columns(conn).keys())
                assert after_studies == before_studies
                assert after_trials == before_trials
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self, restore_head: None) -> None:
        """Re-running ``alembic upgrade head`` with the columns + index
        already present must not raise (AC-13 + plan F7).

        Implementation: after the first upgrade, the alembic_version table
        already records 0020 as the head, so a second ``upgrade head`` is
        a trivial no-op at the alembic level. To prove the migration's
        SQL is itself idempotent, we set the alembic version back to 0019
        WITHOUT running the downgrade SQL (which would drop the columns),
        then re-run upgrade — exercising the IF NOT EXISTS guards.
        """
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text("UPDATE alembic_version SET version_num = '0019'"))
        finally:
            engine.dispose()

        # Re-run upgrade — should be a no-op because all idempotency guards
        # see the columns + index already present.
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                assert "baseline_trial_id" in _studies_columns(conn)
                assert "is_baseline" in _trials_columns(conn)
                assert (
                    _partial_index_predicate(conn, "uq_trials_study_baseline_complete") is not None
                )
        finally:
            engine.dispose()
