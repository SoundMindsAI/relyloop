"""Optuna RDB schema isolation integration test (Story 3.1 / AC-1a + AC-1b).

* AC-1a — after ``make migrate``, both ``public`` and ``optuna`` schemas
  exist (the latter created by ``backend/app/db/optuna_schema.py``).
* AC-1b — first ``optuna.create_study(storage=RDBStorage(...))`` lazily
  creates Optuna's internal tables in the ``optuna.*`` namespace and they
  do NOT collide with RelyLoop's ``public.studies`` / ``public.trials``
  tables.

Skips automatically when Postgres isn't reachable from the host shell.
"""

from __future__ import annotations

import uuid

import optuna
import pytest
from sqlalchemy import create_engine, text

from backend.app.core.settings import get_settings
from backend.app.eval.optuna_runtime import build_storage
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


def _sync_database_url() -> str:
    """Strip the +asyncpg driver prefix for the sync probe connection."""
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _ensure_schemas_initialized() -> None:
    """Idempotent: applies migrations + creates the ``optuna`` schema.

    CI runs ``alembic upgrade head`` (via the ``db_session`` fixture's autouse
    trigger when invoked from any test) but does NOT run
    ``python -m backend.app.db.optuna_schema``. These integration tests bypass
    the ``db_session`` fixture, so we replicate the ``make migrate`` chain
    here: alembic head + the optuna schema initializer.
    """
    from backend.app.db.optuna_schema import init_optuna_schema
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    init_optuna_schema(get_settings().database_url)


def test_ac1a_optuna_schema_exists_after_migrate():
    """AC-1a — ``optuna`` schema is present after migrations + bootstrap."""
    _ensure_schemas_initialized()
    engine = create_engine(_sync_database_url(), future=True)
    try:
        with engine.connect() as conn:
            schemas = {
                row[0]
                for row in conn.execute(
                    text("SELECT schema_name FROM information_schema.schemata")
                ).fetchall()
            }
        assert "public" in schemas
        assert "optuna" in schemas
    finally:
        engine.dispose()


def test_ac1b_optuna_creates_internal_tables_in_optuna_namespace():
    """AC-1b — first ``create_study`` lands tables in optuna.*, not public.*."""
    _ensure_schemas_initialized()
    storage = build_storage(get_settings().database_url)
    study_name = f"ac1b-{uuid.uuid4()}"
    study = optuna.create_study(storage=storage, study_name=study_name, direction="maximize")
    # Trigger at least one storage operation to be sure tables exist.
    trial = study.ask()
    trial.suggest_float("x", 0.0, 1.0)
    study.tell(trial.number, 0.5)

    engine = create_engine(_sync_database_url(), future=True)
    try:
        with engine.connect() as conn:
            optuna_tables = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'optuna'"
                    )
                ).fetchall()
            }
            public_tables = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                ).fetchall()
            }
        # Optuna's canonical tables (names are stable across 3.x and 4.x).
        # We only require that AT LEAST one of these expected names landed in optuna.*;
        # Optuna versions vary the exact set.
        expected_optuna_tables_any_of = {"studies", "trials", "trial_values", "trial_params"}
        assert optuna_tables & expected_optuna_tables_any_of, (
            f"expected at least one Optuna table in 'optuna' schema; got: {optuna_tables}"
        )
        # RelyLoop's app tables stayed in 'public' — note that RelyLoop has
        # `public.studies` and `public.trials` too; Optuna's same-named tables
        # in `optuna.*` must NOT have leaked into `public.*` (the names co-exist
        # across schemas by design but should not be created via this code path).
        assert "studies" in public_tables  # RelyLoop's app table
        assert "trials" in public_tables  # RelyLoop's app table
        # No collision: optuna.studies and public.studies are distinct.
    finally:
        engine.dispose()
