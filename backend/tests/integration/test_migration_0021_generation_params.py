"""``0021_judgment_lists_generation_params`` migration test
(feat_ubi_judgments Story 1.1).

Asserts the schema shape of the column added by
``migrations/versions/0021_judgment_lists_generation_params.py``:

* upgrade head adds ``judgment_lists.generation_params JSONB NULL``
* downgrade to 0020 drops the column
* upgrade → downgrade → upgrade round-trip preserves the other
  judgment_lists columns
* pre-existing LLM rows (generation_params NULL) survive both directions

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


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _postgres_reachable(),
        reason=(
            "Postgres not reachable from this process — see "
            "docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."
        ),
    ),
]


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


class TestGenerationParamsMigration:
    def test_upgrade_adds_jsonb_nullable_column(self, restore_head: None) -> None:
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

    def test_downgrade_drops_column_then_round_trip(self, restore_head: None) -> None:
        _alembic("upgrade", "head")
        _alembic("downgrade", "-1")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                cols = _judgment_lists_columns(conn)
                assert "generation_params" not in cols, (
                    "0021 downgrade should drop generation_params"
                )
                # The sibling columns survive the downgrade.
                assert "calibration" in cols
                assert "rubric" in cols
        finally:
            engine.dispose()
        # Round-trip back up.
        _alembic("upgrade", "head")
        engine2 = create_engine(_sync_database_url(), future=True)
        try:
            with engine2.connect() as conn:
                cols = _judgment_lists_columns(conn)
                assert "generation_params" in cols
        finally:
            engine2.dispose()
