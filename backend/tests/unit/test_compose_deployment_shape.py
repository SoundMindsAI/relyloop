"""Compose deployment-shape regression tests (bug_worker_optuna_init_race).

The worker's ``on_startup`` hook constructs Optuna's ``RDBStorage``, which
issues ``CREATE TYPE`` against the ``optuna`` schema. The schema is
created by the ``migrate`` init container (``alembic upgrade head &&
python -m backend.app.db.optuna_schema``). If ``api`` or ``worker``
ever loses its dependency on ``migrate``, the next ``make up`` on a
fresh ``./data/postgres`` volume crashes the worker with
``psycopg2.errors.InvalidSchemaName``.

This file pins the canonical Compose surface so a stray edit can't
silently re-introduce the boot-order race.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE_PATH = Path(__file__).resolve().parents[3] / "docker-compose.yml"


@pytest.fixture(scope="module")
def compose_spec() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_PATH.read_text())


class TestMigrateInitContainer:
    def test_migrate_service_defined(self, compose_spec: dict[str, Any]) -> None:
        services = compose_spec["services"]
        assert "migrate" in services, (
            "docker-compose.yml lost its `migrate` init container — see bug_worker_optuna_init_race"
        )

    def test_migrate_runs_alembic_and_optuna_schema(self, compose_spec: dict[str, Any]) -> None:
        migrate = compose_spec["services"]["migrate"]
        command = migrate["command"]
        # Command is `sh -c "<cmd>"`; the cmd string must reference both
        # `alembic upgrade head` and the optuna_schema module.
        joined = " ".join(command) if isinstance(command, list) else command
        assert "alembic upgrade head" in joined
        assert "backend.app.db.optuna_schema" in joined

    def test_migrate_depends_on_postgres_healthy(self, compose_spec: dict[str, Any]) -> None:
        depends = compose_spec["services"]["migrate"]["depends_on"]
        assert depends["postgres"]["condition"] == "service_healthy"

    def test_migrate_restart_policy_is_no(self, compose_spec: dict[str, Any]) -> None:
        # Init containers run once and exit; `restart: "no"` is the
        # canonical encoding. `restart: unless-stopped` would keep
        # re-running the migration after a clean exit.
        assert compose_spec["services"]["migrate"]["restart"] == "no"


class TestApiAndWorkerDependOnMigrate:
    @pytest.mark.parametrize("service", ["api", "worker"])
    def test_service_depends_on_migrate_completed_successfully(
        self, compose_spec: dict[str, Any], service: str
    ) -> None:
        depends = compose_spec["services"][service]["depends_on"]
        assert "migrate" in depends, (
            f"{service!r} no longer depends on `migrate` — fresh-stack boots "
            "will race the optuna schema (bug_worker_optuna_init_race)"
        )
        assert depends["migrate"]["condition"] == "service_completed_successfully"
