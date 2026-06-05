# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the compare + pair endpoints (feat_ubi_llm_study_comparison).

Covers ``GET /studies/compare`` (success + 3 warning payloads + every 422/404 +
AC-8 route ordering) and ``GET /studies/{id}/pair`` (found / null / 404). Skips
without Postgres; CI runs against the service-container DB.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — compare endpoints flow through get_db",
)


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


def _u() -> str:
    return str(uuid.uuid4())


async def _seed(
    *,
    same_cluster: bool = True,
    same_query_set: bool = True,
    llm_status: str = "completed",
    second_kind: str = "ubi",
    target_b: str = "products",
    objective_b: dict[str, object] | None = None,
) -> dict[str, str]:
    """Seed a pair and return {llm, ubi, jl_llm, jl_ubi}. The 'b' study's kind /
    cluster / query-set / target / objective are parameterized for the gates."""
    from backend.app.core.settings import get_settings
    from backend.app.db.optuna_schema import init_optuna_schema

    init_optuna_schema(get_settings().database_url)
    factory = get_session_factory()
    async with factory() as db:
        c1 = await repo.create_cluster(
            db,
            id=_u(),
            name=f"c-{_u()[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://s:9200",
            auth_kind="es_basic",
            credentials_ref="r",
        )
        c2 = (
            c1
            if same_cluster
            else await repo.create_cluster(
                db,
                id=_u(),
                name=f"c2-{_u()[:8]}",
                engine_type="elasticsearch",
                environment="dev",
                base_url="http://s:9200",
                auth_kind="es_basic",
                credentials_ref="r",
            )
        )
        qs1 = await repo.create_query_set(db, id=_u(), name=f"qs-{_u()[:8]}", cluster_id=c1.id)
        qs2 = (
            qs1
            if same_query_set
            else await repo.create_query_set(db, id=_u(), name=f"qs2-{_u()[:8]}", cluster_id=c2.id)
        )
        tpl = await repo.create_query_template(
            db,
            id=_u(),
            name=f"t-{_u()[:8]}",
            engine_type="elasticsearch",
            body='{"query":{"match_all":{}}}',
            declared_params={"boost": "float"},
            version=1,
        )

        async def mk_jl(cluster_id, query_set_id, kind, target) -> Any:  # noqa: ANN001
            gp = {"generation_kind": "ubi"} if kind == "ubi" else None
            return await repo.create_judgment_list(
                db,
                id=_u(),
                name=f"jl-{kind}-{_u()[:8]}",
                description=None,
                query_set_id=query_set_id,
                cluster_id=cluster_id,
                target=target,
                current_template_id=None,
                rubric="hand-built",
                status="complete",
                failed_reason=None,
                calibration=None,
                generation_params=gp,
            )

        async def mk_study(cluster_id, query_set_id, jl_id, status, target, objective) -> Any:  # noqa: ANN001
            sid = _u()
            return await repo.create_study(
                db,
                id=sid,
                name=f"s-{_u()[:8]}",
                cluster_id=cluster_id,
                target=target,
                template_id=tpl.id,
                query_set_id=query_set_id,
                judgment_list_id=jl_id,
                search_space={"params": {"boost": {"type": "float", "low": 0.0, "high": 4.0}}},
                objective=objective or {"metric": "ndcg", "k": 10, "direction": "maximize"},
                config={"max_trials": 10, "sampler": "tpe"},
                status=status,
                optuna_study_name=sid,
            )

        jl_llm = await mk_jl(c1.id, qs1.id, "llm", "products")
        jl_b = await mk_jl(c2.id, qs2.id, second_kind, target_b)
        llm = await mk_study(c1.id, qs1.id, jl_llm.id, llm_status, "products", None)
        b = await mk_study(c2.id, qs2.id, jl_b.id, "completed", target_b, objective_b)
        await db.commit()
        return {"llm": llm.id, "ubi": b.id, "jl_llm": jl_llm.id, "jl_ubi": jl_b.id}


async def test_compare_happy_no_warnings(async_client: httpx.AsyncClient) -> None:
    ids = await _seed()
    r = await async_client.get(f"/api/v1/studies/compare?a={ids['llm']}&b={ids['ubi']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {body["a_kind"], body["b_kind"]} == {"llm", "ubi"}
    assert body["warnings"] == []


async def test_compare_cross_cluster_warning(async_client: httpx.AsyncClient) -> None:
    ids = await _seed(same_cluster=False)
    r = await async_client.get(f"/api/v1/studies/compare?a={ids['llm']}&b={ids['ubi']}")
    assert r.status_code == 200, r.text
    assert "CROSS_CLUSTER" in [w["code"] for w in r.json()["warnings"]]


async def test_compare_target_mismatch_warning(async_client: httpx.AsyncClient) -> None:
    ids = await _seed(target_b="catalog")
    r = await async_client.get(f"/api/v1/studies/compare?a={ids['llm']}&b={ids['ubi']}")
    assert r.status_code == 200, r.text
    assert "TARGET_MISMATCH" in [w["code"] for w in r.json()["warnings"]]


async def test_compare_objective_mismatch_warning(async_client: httpx.AsyncClient) -> None:
    ids = await _seed(objective_b={"metric": "map", "k": 10, "direction": "maximize"})
    r = await async_client.get(f"/api/v1/studies/compare?a={ids['llm']}&b={ids['ubi']}")
    assert r.status_code == 200, r.text
    assert "OBJECTIVE_MISMATCH" in [w["code"] for w in r.json()["warnings"]]


async def test_compare_not_llm_ubi_pair(async_client: httpx.AsyncClient) -> None:
    ids = await _seed(second_kind="llm")  # two LLM studies
    r = await async_client.get(f"/api/v1/studies/compare?a={ids['llm']}&b={ids['ubi']}")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error_code"] == "COMPARE_NOT_LLM_UBI_PAIR"


async def test_compare_query_set_mismatch(async_client: httpx.AsyncClient) -> None:
    ids = await _seed(same_query_set=False)
    r = await async_client.get(f"/api/v1/studies/compare?a={ids['llm']}&b={ids['ubi']}")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error_code"] == "COMPARE_QUERY_SET_MISMATCH"


async def test_compare_not_completed(async_client: httpx.AsyncClient) -> None:
    ids = await _seed(llm_status="running")
    r = await async_client.get(f"/api/v1/studies/compare?a={ids['llm']}&b={ids['ubi']}")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error_code"] == "COMPARE_STUDY_NOT_COMPLETED"


async def test_compare_study_not_found(async_client: httpx.AsyncClient) -> None:
    ids = await _seed()
    r = await async_client.get(f"/api/v1/studies/compare?a={ids['llm']}&b={_u()}")
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error_code"] == "STUDY_NOT_FOUND"


async def test_compare_no_params_is_422_not_404(async_client: httpx.AsyncClient) -> None:
    # AC-8 route ordering: bare /studies/compare reaches the compare handler
    # (missing required params -> 422 VALIDATION_ERROR), NOT /studies/{id} (404).
    r = await async_client.get("/api/v1/studies/compare")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error_code"] == "VALIDATION_ERROR"


async def test_pair_found(async_client: httpx.AsyncClient) -> None:
    ids = await _seed()
    r = await async_client.get(f"/api/v1/studies/{ids['llm']}/pair")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["study_id"] == ids["ubi"]
    assert body["kind"] == "ubi"


async def test_pair_null_when_no_counterpart(async_client: httpx.AsyncClient) -> None:
    ids = await _seed(second_kind="llm")  # no UBI counterpart
    r = await async_client.get(f"/api/v1/studies/{ids['llm']}/pair")
    assert r.status_code == 200, r.text
    assert r.json() == {"study_id": None, "kind": None}


async def test_pair_404_when_study_missing(async_client: httpx.AsyncClient) -> None:
    r = await async_client.get(f"/api/v1/studies/{_u()}/pair")
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error_code"] == "STUDY_NOT_FOUND"
