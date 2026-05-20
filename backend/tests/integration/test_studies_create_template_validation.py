"""Integration tests for POST /api/v1/studies template validation.

chore_create_study_wizard_polish Story 1.1.

Covers the three behavioral gates:

  AC-5: Unknown param → 400 SEARCH_SPACE_UNKNOWN_PARAM + no studies row inserted.
  AC-6: Missing declared param → 400 SEARCH_SPACE_MISSING_DECLARED_PARAM + no row.
  AC-7: Both present → SEARCH_SPACE_UNKNOWN_PARAM wins (lexicographic on offender).

Seeds independent cluster/template/query_set/judgment_list rows per test so the
existing test_studies_api.py fixture isn't perturbed. (Its seed uses
``declared_params={"bm25_k1": "float"}`` — see the comment in that file's
``_seed_minimum_for_post_studies`` helper.)
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

from backend.app.db import repo
from backend.app.db.models import Study
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed(declared_params: dict[str, str]) -> dict[str, str]:
    """Seed the minimum graph for POST /studies, with caller-controlled declared_params."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"tv-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"tv-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params=declared_params,
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"tv-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"tv-jl-{uuid.uuid4().hex[:8]}",
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
        await db.commit()
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "template_name": template.name,
        "query_set_id": query_set.id,
        "judgment_list_id": judgment_list.id,
    }


async def _count_studies() -> int:
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(Study))
        return len(result.scalars().all())


def _post_body(ids: dict[str, str], search_space: dict[str, object]) -> dict[str, object]:
    return {
        "name": "tv-study",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": search_space,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 5},
    }


async def test_unknown_param_returns_400_and_no_row_inserted(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-5: search_space contains a key not in declared_params → 400 + no row."""
    ids = await _seed({"boost_title": "float"})
    pre = await _count_studies()
    body = _post_body(
        ids,
        {"params": {"boos_title": {"type": "float", "low": 0.5, "high": 10.0, "log": True}}},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "SEARCH_SPACE_UNKNOWN_PARAM"
    assert detail["retryable"] is False
    assert "Param 'boos_title' is not declared by template" in detail["message"]
    assert ids["template_name"] in detail["message"]
    # AC-5: no studies row inserted on validation failure.
    assert await _count_studies() == pre


async def test_missing_declared_param_returns_400_and_no_row_inserted(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-6: declared_params contains a key not in search_space → 400 + no row."""
    ids = await _seed({"boost_title": "float", "fuzziness": "string"})
    pre = await _count_studies()
    body = _post_body(
        ids,
        {"params": {"boost_title": {"type": "float", "low": 0.5, "high": 10.0, "log": True}}},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "SEARCH_SPACE_MISSING_DECLARED_PARAM"
    assert detail["retryable"] is False
    assert "declares param 'fuzziness'" in detail["message"]
    assert "Add it or remove from the template." in detail["message"]
    assert await _count_studies() == pre


async def test_both_errors_unknown_param_wins(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-7: when both unknown AND missing apply, unknown-param is raised first."""
    ids = await _seed({"boost_title": "float", "fuzziness": "string"})
    body = _post_body(
        ids,
        {"params": {"boos_title": {"type": "float", "low": 0.5, "high": 10.0, "log": True}}},
    )
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error_code"] == "SEARCH_SPACE_UNKNOWN_PARAM"
