"""``0021_judgment_lists_generation_params`` migration test
(feat_ubi_judgments Story 1.1 / FR-4 + FR-5 backing).

Asserts the schema shape of the one nullable JSONB column added by
``migrations/versions/0021_judgment_lists_generation_params.py``:

* upgrade head adds ``judgment_lists.generation_params JSONB NULL``
* downgrade to 0020 drops the column
* upgrade → downgrade → upgrade round-trip preserves the other
  ``judgment_lists`` columns (no collateral damage on LLM lists)
* Idempotent re-run: running upgrade head a second time on the same head
  via ``UPDATE alembic_version SET version_num = '0020'`` then re-upgrade
  does not raise — the DO $$ ... IF NOT EXISTS $$ guard makes the
  migration safe to re-apply.

Mirrors ``test_baseline_migration_round_trip.py`` for skip semantics +
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


def _judgment_lists_columns(conn) -> dict[str, dict[str, object]]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'judgment_lists'"
        )
    ).fetchall()
    return {r[0]: {"data_type": r[1], "nullable": r[2]} for r in rows}


@pytest.mark.integration
class TestGenerationParamsMigration:
    def test_upgrade_adds_generation_params_column(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _judgment_lists_columns(conn)
                assert "generation_params" in cols, (
                    "0021 upgrade should add judgment_lists.generation_params"
                )
                col = cols["generation_params"]
                assert col["data_type"] == "jsonb"
                assert col["nullable"] == "YES"
        finally:
            engine.dispose()

    def test_downgrade_drops_column(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        _alembic("downgrade", "0020")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _judgment_lists_columns(conn)
                assert "generation_params" not in cols, (
                    "0021 downgrade should drop judgment_lists.generation_params"
                )
                # Other columns survive — spot-check the ones the LLM path relies on.
                for required in (
                    "id",
                    "name",
                    "description",
                    "query_set_id",
                    "cluster_id",
                    "target",
                    "current_template_id",
                    "rubric",
                    "status",
                    "failed_reason",
                    "calibration",
                    "created_at",
                ):
                    assert required in cols, (
                        f"0021 downgrade dropped sibling column {required!r}; "
                        "downgrade must only touch generation_params"
                    )
        finally:
            engine.dispose()

    def test_round_trip_preserves_other_columns(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                before = set(_judgment_lists_columns(conn).keys())
        finally:
            engine.dispose()

        _alembic("downgrade", "0020")
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                after = set(_judgment_lists_columns(conn).keys())
                assert after == before, (
                    "round-trip mutated judgment_lists columns "
                    f"(before={sorted(before)}, after={sorted(after)})"
                )
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self, restore_head: None) -> None:
        """Re-running ``alembic upgrade head`` with the column already present
        must not raise — the DO $$ ... IF NOT EXISTS $$ guard makes the
        migration safe to re-apply (mirrors the 0020 baseline-trial pattern).
        """
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text("UPDATE alembic_version SET version_num = '0020'"))
        finally:
            engine.dispose()

        # Re-run upgrade — must be a no-op because the IF NOT EXISTS guard
        # sees the column already present.
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _judgment_lists_columns(conn)
                assert "generation_params" in cols
                assert cols["generation_params"]["data_type"] == "jsonb"
                assert cols["generation_params"]["nullable"] == "YES"
        finally:
            engine.dispose()

    def test_existing_llm_list_survives_round_trip(self, restore_head: None) -> None:
        """Pre-existing LLM judgment_list rows (which never populate
        generation_params) must survive both upgrade and downgrade cleanly.
        """
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            # Pick any existing judgment_list row if one exists; otherwise
            # the assertion is vacuously satisfied (no rows = no data loss).
            with engine.begin() as conn:
                # Snapshot row count + generation_params nullability for any
                # pre-existing rows.
                row_count_before = conn.execute(
                    text("SELECT COUNT(*) FROM judgment_lists")
                ).scalar_one()
                # Pre-existing LLM lists must have NULL generation_params after
                # upgrade (we never backfill — the column is purely additive).
                null_count = conn.execute(
                    text("SELECT COUNT(*) FROM judgment_lists WHERE generation_params IS NULL")
                ).scalar_one()
                assert null_count == row_count_before, (
                    f"upgrade-head backfilled generation_params on {row_count_before - null_count} "
                    "pre-existing rows; the column must be purely additive (NULL on every LLM list)"
                )
        finally:
            engine.dispose()

        # Round-trip and re-check.
        _alembic("downgrade", "0020")
        _alembic("upgrade", "head")

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row_count_after = conn.execute(
                    text("SELECT COUNT(*) FROM judgment_lists")
                ).scalar_one()
                null_count_after = conn.execute(
                    text("SELECT COUNT(*) FROM judgment_lists WHERE generation_params IS NULL")
                ).scalar_one()
                assert row_count_after == row_count_before, (
                    "round-trip lost rows from judgment_lists; downgrade should only "
                    "drop a column, never delete data"
                )
                assert null_count_after == row_count_after, (
                    "round-trip backfilled generation_params on some rows; the column "
                    "must remain NULL on every LLM list"
                )
        finally:
            engine.dispose()
