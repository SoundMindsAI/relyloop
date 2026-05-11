"""Test fixtures for feat_study_lifecycle Phase 2 orchestrator tests.

Provides:

- :func:`seed_study` — create a full study (cluster + template + query_set +
  queries + judgment_list + study row) ready for the orchestrator to pick
  up. Status starts at ``queued``.
- :func:`monkeypatch_qrels` — replace
  ``backend.app.eval.qrels_loader.load_qrels`` for tests that need to
  bypass the MVP1 ``JudgmentsTableMissing`` stub.
- :func:`install_stub_adapter` — install a deterministic stub adapter on
  ``backend.workers.trials.build_adapter``.
- :func:`cleanup_study` — FK-safe teardown of all rows created by
  :func:`seed_study` plus any trials / proposals the orchestrator wrote.

These helpers parallel ``run_trial_setup.py`` but use
``status='queued'`` so the orchestrator can drive the lifecycle.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.app.db import repo
from backend.app.db.models import (
    Cluster,
    JudgmentList,
    Proposal,
    QuerySet,
    QueryTemplate,
    Study,
    Trial,
)
from backend.app.db.session import get_session_factory
from backend.tests.integration.fixtures.handbuilt_qrels import (
    build_hits_response,
    build_qrels,
)
from backend.tests.integration.fixtures.stub_adapter import StubAdapter


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass
class StudyFixture:
    """All IDs the orchestrator tests need to assert against."""

    cluster_id: str
    template_id: str
    query_set_id: str
    query_ids: list[str]
    judgment_list_id: str
    study_id: str
    optuna_study_name: str


async def seed_study(
    *,
    max_trials: int | None = 5,
    parallelism: int | None = 2,
    time_budget_min: float | None = None,
    sampler: str = "tpe",
    objective_metric: str = "ndcg",
    objective_k: int = 10,
    search_space: dict[str, Any] | None = None,
    n_queries: int = 3,
    cluster_base_url: str = "http://stub:9200",
    status: str = "queued",
) -> StudyFixture:
    """Create the full study row chain ready for the orchestrator.

    Defaults to a tiny study (5 trials, 2-wide parallelism) so the
    orchestrator can complete within an integration-test wall budget.

    ``status='queued'`` lets the orchestrator transition to ``running``
    naturally; pass ``status='running'`` to simulate a resume-after-restart
    scenario.
    """
    from backend.app.core.settings import get_settings
    from backend.app.db.optuna_schema import init_optuna_schema
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    init_optuna_schema(get_settings().database_url)

    config: dict[str, Any] = {"sampler": sampler}
    if max_trials is not None:
        config["max_trials"] = max_trials
    if parallelism is not None:
        config["parallelism"] = parallelism
    if time_budget_min is not None:
        config["time_budget_min"] = time_budget_min

    objective: dict[str, Any] = {
        "metric": objective_metric,
        "k": objective_k,
        "direction": "maximize",
    }

    if search_space is None:
        # Default tiny float-only space — matches the orchestrator's
        # SearchSpace.model_validate contract.
        search_space = {
            "params": {
                "bm25_k1": {"type": "float", "low": 0.1, "high": 2.0},
                "bm25_b": {"type": "float", "low": 0.0, "high": 1.0},
            }
        }

    factory = get_session_factory()
    async with factory() as db:
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
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=_uuid(),
            name=f"qs-{_uuid()[:8]}",
            cluster_id=cluster.id,
        )
        query_ids: list[str] = []
        for i in range(n_queries):
            q = await repo.create_query(
                db,
                id=_uuid(),
                query_set_id=query_set.id,
                query_text=f"query {i}",
                reference_answer=None,
                query_metadata=None,
            )
            query_ids.append(q.id)
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
        study = await repo.create_study(
            db,
            id=study_id,
            name=f"s-{_uuid()[:8]}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=judgment_list.id,
            search_space=search_space,
            objective=objective,
            config=config,
            status=status,
            optuna_study_name=study_id,
        )
        await db.commit()

    return StudyFixture(
        cluster_id=cluster.id,
        template_id=template.id,
        query_set_id=query_set.id,
        query_ids=query_ids,
        judgment_list_id=judgment_list.id,
        study_id=study.id,
        optuna_study_name=study.optuna_study_name,
    )


def install_stub_adapter(
    monkeypatch: pytest.MonkeyPatch,
    query_ids: Sequence[str],
    *,
    raise_on_search: BaseException | None = None,
) -> StubAdapter:
    """Install a deterministic StubAdapter on the worker's build_adapter.

    Returns the stub so tests can read ``stub.search_batch_calls`` to
    verify AC-7 etc. When ``raise_on_search`` is set, every search call
    raises — useful for the AC-5 5-consecutive-failure path.
    """
    stub = StubAdapter(
        engine_type="elasticsearch",
        search_batch_response=build_hits_response(query_ids),
        raise_on_search=raise_on_search,
    )
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _cluster: stub)
    return stub


def monkeypatch_qrels(
    monkeypatch: pytest.MonkeyPatch,
    query_ids: Sequence[str],
) -> None:
    """Replace ``load_qrels`` with a hand-built fixture for these queries."""
    handbuilt = build_qrels(query_ids)
    monkeypatch.setattr(
        "backend.workers.trials.load_qrels",
        AsyncMock(return_value=handbuilt),
    )


async def cleanup_study(fixture: StudyFixture) -> None:
    """FK-safe teardown of every row created by :func:`seed_study` + the
    orchestrator's trials/proposals."""
    from sqlalchemy import delete

    factory = get_session_factory()
    async with factory() as db:
        # Proposals reference trials via study_trial_id (FK NO ACTION) — must
        # be deleted before trials, regardless of study CASCADE chain.
        await db.execute(delete(Proposal).where(Proposal.study_id == fixture.study_id))
        await db.execute(delete(Trial).where(Trial.study_id == fixture.study_id))
        await db.execute(delete(Study).where(Study.id == fixture.study_id))
        await db.execute(delete(JudgmentList).where(JudgmentList.id == fixture.judgment_list_id))
        await db.execute(delete(QuerySet).where(QuerySet.id == fixture.query_set_id))
        await db.execute(delete(QueryTemplate).where(QueryTemplate.id == fixture.template_id))
        await db.execute(delete(Cluster).where(Cluster.id == fixture.cluster_id))
        await db.commit()


__all__ = [
    "StudyFixture",
    "cleanup_study",
    "install_stub_adapter",
    "monkeypatch_qrels",
    "seed_study",
]
