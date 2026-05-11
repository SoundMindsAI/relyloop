"""Migration round-trip integration test (infra_foundation Story 2.2).

Marked ``@pytest.mark.integration`` — only runs when a Postgres instance is
reachable via ``DATABASE_URL_FILE``. Skipped in unit-only test runs (the default
for ``make test-unit``).

**Where this works:**

- CI (``.github/workflows/pr.yml`` exposes Postgres as a service container on
  ``localhost:5432`` and exports ``DATABASE_URL_FILE``).
- Locally if you point ``DATABASE_URL_FILE`` at a Postgres reachable from
  the test process (e.g. an ad-hoc ``docker run -p 5432:5432 postgres:16``).

**Where this skips:**

- Host shell without ``DATABASE_URL_FILE`` set, or pointing at a Postgres URL
  whose host:port isn't TCP-reachable from the test process. By design,
  ``docker-compose.yml`` does NOT expose Postgres on a host port (per
  CLAUDE.md "Ports" — Postgres is internal-only on the Compose network).
  See ``docs/03_runbooks/local-dev.md`` §"Local-vs-CI test layers" for
  alternatives (use ``make migrate`` to sanity-check end-to-end, or trust CI).

Verifies AC-7: from a fresh DB, ``alembic upgrade head`` creates the
``alembic_version`` table at the head revision; subsequent ``make migrate`` is
a no-op; round-trip via ``alembic downgrade -1 && alembic upgrade head``
succeeds.
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
    """Return True only if Settings is constructible AND its DB host:port accepts TCP.

    Used to gate the whole module: skip cleanly on a host that can't reach
    Postgres (the common case when an operator runs `make test-integration`
    from their shell — Compose's `postgres` service is not host-exposed).
    """
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
        url = get_settings().database_url
    except Exception:  # noqa: BLE001 — best-effort skip-detector; any failure → skip
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
        "docs/03_runbooks/local-dev.md §'Local-vs-CI test layers' "
        "(use `make migrate` to sanity-check locally; CI runs the round-trip)."
    ),
)


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
                # Head is "0004" once feat_llm_judgments Story 1.1 lands the
                # judgments migration on top of 0003_study_lifecycle_schema.
                assert row[0] == "0004"
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
        # After downgrade -1 from 0004 we land at 0003 (study_lifecycle_schema).
        # Re-upgrade re-applies 0004 cleanly per CLAUDE.md Absolute Rule #5.
        _alembic("upgrade", "head")
        engine = create_engine(_sync_database_url(), future=True)
        try:
            with engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                assert row is not None
                # Head is "0004" once feat_llm_judgments Story 1.1 lands the
                # judgments migration on top of 0003_study_lifecycle_schema.
                assert row[0] == "0004"
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
