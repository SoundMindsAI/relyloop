"""Shared setup helpers for the run_trial integration tests.

These helpers use ``get_session_factory()`` directly (NOT the ``db_session``
fixture's savepoint-wrapped session) because the ``run_trial`` worker opens
its own session via the same factory. Savepoint-isolated test data wouldn't
be visible to the worker's separate connection.

Each test gets a unique ``study_id`` UUID; cleanup is via a ``DELETE`` on
the study row at teardown (cascades to trials, judgments via FK).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import optuna
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.models import Query, Study
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_pruner, build_sampler, get_or_create_study


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class TrialFixture:
    """Bundle of IDs returned by ``setup_study_with_cluster``."""

    cluster_id: str
    template_id: str
    query_set_id: str
    query_ids: list[str]
    judgment_list_id: str
    study_id: str
    optuna_study_name: str


async def setup_study_with_cluster(
    *,
    sampler: str = "tpe",
    pruner: str | None = None,
    max_trials: int = 100,
    objective_metric: str = "ndcg",
    objective_k: int = 10,
    cluster_base_url: str = "http://stub:9200",
    n_queries: int = 3,
) -> TrialFixture:
    """Create cluster + template + query_set + queries + judgment_list + study.

    Returns a TrialFixture with all generated IDs. The Optuna study is NOT
    created here — the caller drives that via ``create_optuna_trial_for_study``
    (simulating the orchestrator per spec §11 / plan Conventions).

    Migrations are applied here on first call (CI doesn't run a separate
    ``make migrate`` before pytest, and tests that bypass the ``db_session``
    fixture's autouse migration trigger would otherwise hit
    ``relation "clusters" does not exist``).
    """
    # Apply migrations once per test session — module-level idempotent flag
    # inside conftest._apply_migrations_if_needed.
    from backend.app.core.settings import get_settings
    from backend.app.db.optuna_schema import init_optuna_schema
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    # CI runs `alembic upgrade head` (via the autouse trigger) but does NOT
    # run `python -m backend.app.db.optuna_schema`. The Makefile's `make migrate`
    # target chains both; in tests we replicate the second step manually so
    # the ``optuna`` schema exists before ``RDBStorage`` touches it.
    # Idempotent (CREATE SCHEMA IF NOT EXISTS).
    init_optuna_schema(get_settings().database_url)

    config: dict[str, object] = {"max_trials": max_trials, "sampler": sampler}
    if pruner is not None:
        config["pruner"] = pruner
    objective: dict[str, object] = {
        "metric": objective_metric,
        "k": objective_k,
        "direction": "maximize",
    }

    factory = get_session_factory()
    async with factory() as db:
        fixture = await _create_rows(
            db,
            config=config,
            objective=objective,
            cluster_base_url=cluster_base_url,
            n_queries=n_queries,
        )
        await db.commit()
    return fixture


async def _create_rows(
    db: AsyncSession,
    *,
    config: dict[str, object],
    objective: dict[str, object],
    cluster_base_url: str,
    n_queries: int,
) -> TrialFixture:
    """Create the seven rows. Caller commits."""
    cluster = await repo.create_cluster(
        db,
        id=_uuid(),
        name=f"c-{_uuid()[:8]}",
        engine_type="elasticsearch",
        environment="dev",
        base_url=cluster_base_url,
        auth_kind="es_basic",
        credentials_ref="ref",
    )
    template = await repo.create_query_template(
        db,
        id=_uuid(),
        name=f"qt-{_uuid()[:8]}",
        engine_type="elasticsearch",
        body='{"query": {"match_all": {}}}',
        declared_params={"q": "string"},
        version=1,
    )
    query_set = await repo.create_query_set(
        db,
        id=_uuid(),
        name=f"qs-{_uuid()[:8]}",
        cluster_id=cluster.id,
    )
    queries: list[Query] = []
    for i in range(n_queries):
        q = await repo.create_query(
            db,
            id=_uuid(),
            query_set_id=query_set.id,
            query_text=f"query {i}",
            reference_answer=None,
            query_metadata=None,
        )
        queries.append(q)

    judgment_list = await repo.create_judgment_list(
        db,
        id=_uuid(),
        name=f"jl-{_uuid()[:8]}",
        description=None,
        query_set_id=query_set.id,
        cluster_id=cluster.id,
        target="stub-index",
        current_template_id=template.id,
        rubric="hand-built",
        status="complete",
        failed_reason=None,
        calibration=None,
    )
    study_id = _uuid()
    optuna_study_name = study_id  # convention from data-model.md
    study = await repo.create_study(
        db,
        id=study_id,
        name=f"s-{_uuid()[:8]}",
        cluster_id=cluster.id,
        target="stub-index",
        template_id=template.id,
        query_set_id=query_set.id,
        judgment_list_id=judgment_list.id,
        search_space={"bm25_k1": [0.0, 4.0], "bm25_b": [0.0, 1.0]},
        objective=objective,
        config=config,
        status="running",
        optuna_study_name=optuna_study_name,
    )
    return TrialFixture(
        cluster_id=cluster.id,
        template_id=template.id,
        query_set_id=query_set.id,
        query_ids=[q.id for q in queries],
        judgment_list_id=judgment_list.id,
        study_id=study.id,
        optuna_study_name=study.optuna_study_name,
    )


def create_optuna_trial_for_study(
    storage: optuna.storages.RDBStorage,
    *,
    optuna_study_name: str,
    config: dict[str, object] | None = None,
    objective: dict[str, object] | None = None,
) -> int:
    """Simulate Phase 2's orchestrator: ask() + suggest_*().

    Per spec §11 the worker doesn't call ask() — the orchestrator does, AND
    populates ``trial.params`` via ``suggest_*`` before enqueue. Tests call
    this helper from setup to allocate an Optuna trial with populated params.

    Returns the allocated ``optuna_trial_number``.
    """
    config = config or {"max_trials": 100, "sampler": "tpe"}
    objective = objective or {"metric": "ndcg", "k": 10, "direction": "maximize"}

    sampler = build_sampler(config, seed=config.get("seed"))  # type: ignore[arg-type]
    pruner = build_pruner(config)
    study = get_or_create_study(
        storage=storage,
        optuna_study_name=optuna_study_name,
        direction=objective["direction"],  # type: ignore[arg-type]
        sampler=sampler,
        pruner=pruner,
    )
    trial = study.ask()
    # Populate params per a tiny search space — matches the study row's
    # search_space declaration above.
    trial.suggest_float("bm25_k1", 0.0, 4.0)
    trial.suggest_float("bm25_b", 0.0, 1.0)
    return trial.number


async def cleanup_study(study_id: str) -> None:
    """Delete the study row at teardown (cascades to trials via FK).

    Other rows (cluster, template, query_set, queries, judgment_list) are
    left in place — they're cheap to accumulate in the test DB; CI uses
    an ephemeral container so they don't survive across runs anyway.
    """
    factory = get_session_factory()
    async with factory() as db:
        await db.execute(delete(Study).where(Study.id == study_id))
        await db.commit()
