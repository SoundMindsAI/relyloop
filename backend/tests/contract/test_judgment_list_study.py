# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for GET /judgment-lists/{id}/study (feat_ubi_llm_study_comparison Story 2.2).

Found / null / 404. Skips without Postgres; CI runs against the service-container DB.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — endpoint flows through get_db",
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


async def _seed_list_with_study(*, with_study: bool = True) -> tuple[str, str | None]:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=_u(),
            name=f"c-{_u()[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://s:9200",
            auth_kind="es_basic",
            credentials_ref="r",
        )
        qs = await repo.create_query_set(db, id=_u(), name=f"qs-{_u()[:8]}", cluster_id=cluster.id)
        tpl = await repo.create_query_template(
            db,
            id=_u(),
            name=f"t-{_u()[:8]}",
            engine_type="elasticsearch",
            body='{"query":{"match_all":{}}}',
            declared_params={"boost": "float"},
            version=1,
        )
        jl = await repo.create_judgment_list(
            db,
            id=_u(),
            name=f"jl-{_u()[:8]}",
            description=None,
            query_set_id=qs.id,
            cluster_id=cluster.id,
            target="products",
            current_template_id=None,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
            generation_params=None,
        )
        study_id: str | None = None
        if with_study:
            sid = _u()
            await repo.create_study(
                db,
                id=sid,
                name=f"s-{_u()[:8]}",
                cluster_id=cluster.id,
                target="products",
                template_id=tpl.id,
                query_set_id=qs.id,
                judgment_list_id=jl.id,
                search_space={"params": {"boost": {"type": "float", "low": 0.0, "high": 4.0}}},
                objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
                config={"max_trials": 10, "sampler": "tpe"},
                status="completed",
                optuna_study_name=sid,
            )
            study_id = sid
        await db.commit()
        return jl.id, study_id


async def test_found(async_client: httpx.AsyncClient) -> None:
    jl_id, sid = await _seed_list_with_study(with_study=True)
    r = await async_client.get(f"/api/v1/judgment-lists/{jl_id}/study")
    assert r.status_code == 200, r.text
    assert r.json() == {"study_id": sid}


async def test_null_when_no_completed_study(async_client: httpx.AsyncClient) -> None:
    jl_id, _ = await _seed_list_with_study(with_study=False)
    r = await async_client.get(f"/api/v1/judgment-lists/{jl_id}/study")
    assert r.status_code == 200, r.text
    assert r.json() == {"study_id": None}


async def test_404_when_list_missing(async_client: httpx.AsyncClient) -> None:
    r = await async_client.get(f"/api/v1/judgment-lists/{_u()}/study")
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error_code"] == "JUDGMENT_LIST_NOT_FOUND"
