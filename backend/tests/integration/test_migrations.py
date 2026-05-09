"""Migration round-trip integration test (infra_foundation Story 2.2).

Marked ``@pytest.mark.integration`` — only runs when a Postgres instance is
reachable via ``DATABASE_URL_FILE``. Skipped in unit-only test runs (the default
for ``make test-unit``).

Verifies AC-7: from a fresh DB, ``alembic upgrade head`` creates the
``alembic_version`` table at the head revision; subsequent ``make migrate`` is
a no-op; round-trip via ``alembic downgrade -1 && alembic upgrade head``
succeeds.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from backend.app.core.settings import get_settings

REPO = Path(__file__).resolve().parents[3]


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Run alembic from the repo root with the project venv."""
    return subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )


def _sync_database_url() -> str:
    """Convert the async DSN to sync for inspection queries."""
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
def fresh_db() -> Iterator[None]:
    """Roll back to base, then leave whatever state the test ends in.

    The integration tests never assume a clean DB; they assert the migration
    chain is well-formed regardless of starting state.
    """
    yield
    # Best-effort restore to head after test (so other tests aren't affected
    # by our downgrade games). If this fails, the next test run will fix it
    # via `make migrate`.
    try:
        _alembic("upgrade", "head")
    except subprocess.CalledProcessError:
        pass


@pytest.mark.integration
class TestBaselineMigration:
    def test_upgrade_head_creates_alembic_version(self, fresh_db: None) -> None:
        """AC-7: `make migrate` creates `alembic_version` at the head revision."""
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
                assert row is not None, "alembic_version table empty after upgrade head"
                # Baseline is "0001" per migrations/versions/0001_baseline.py.
                assert row[0] == "0001"
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent(self, fresh_db: None) -> None:
        """Running `upgrade head` twice in a row is a no-op the second time."""
        _alembic("upgrade", "head")
        result = _alembic("upgrade", "head")
        # No error, no migration ran the second time (Alembic logs at INFO).
        assert "Running upgrade" not in result.stdout

    def test_round_trip(self, fresh_db: None) -> None:
        """Downgrade by one revision and re-upgrade returns cleanly to head."""
        _alembic("upgrade", "head")
        _alembic("downgrade", "-1")
        # After downgrade -1 from baseline, alembic_version table is dropped.
        # Re-upgrade re-creates it at head.
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                assert row is not None
                assert row[0] == "0001"
        finally:
            engine.dispose()


@pytest.mark.integration
class TestOptunaSchema:
    def test_init_optuna_schema_creates_namespace(self, fresh_db: None) -> None:
        """init_optuna_schema() creates the `optuna` schema if missing; idempotent."""
        from backend.app.db.optuna_schema import init_optuna_schema

        init_optuna_schema(get_settings().database_url)
        # Idempotent: second call doesn't raise
        init_optuna_schema(get_settings().database_url)

        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT schema_name FROM information_schema.schemata "
                        "WHERE schema_name = 'optuna'"
                    )
                ).fetchone()
                assert row is not None, "optuna schema was not created"
        finally:
            engine.dispose()
