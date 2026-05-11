"""AC-9 — pagination + since + X-Total-Count across the 4 list endpoints.

12 methods (4 endpoints × 3 behaviors) called out by Story 3.3 task 7 +
Story 3.4 task 3.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.models import Study, Trial
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


# ---------------------------------------------------------------------------
# /api/v1/studies
# ---------------------------------------------------------------------------


async def _seed_studies(n: int) -> None:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"pag-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"pag-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"pag-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"pag-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=qs.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        for i in range(n):
            await repo.create_study(
                db,
                id=str(uuid.uuid4()),
                name=f"pag-s-{i}-{uuid.uuid4().hex[:6]}",
                cluster_id=cluster.id,
                target="stub-index",
                template_id=template.id,
                query_set_id=qs.id,
                judgment_list_id=jl.id,
                search_space={"params": {"k": {"type": "float", "low": 0.1, "high": 1.0}}},
                objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
                config={"max_trials": 5},
                status="queued",
                optuna_study_name=str(uuid.uuid4()),
            )
        await db.commit()


async def test_studies_list_cursor_pagination(async_client: httpx.AsyncClient) -> None:
    """AC-9 studies: 75 rows paginate as 50 + 25 with has_more correct."""
    await _seed_studies(75)
    page1 = await async_client.get("/api/v1/studies?limit=50")
    assert page1.status_code == 200
    p1 = page1.json()
    assert len(p1["data"]) == 50
    assert p1["has_more"] is True
    assert p1["next_cursor"] is not None
    page2 = await async_client.get(f"/api/v1/studies?limit=50&cursor={p1['next_cursor']}")
    assert page2.status_code == 200
    p2 = page2.json()
    assert len(p2["data"]) >= 25
    ids1 = {s["id"] for s in p1["data"]}
    ids2 = {s["id"] for s in p2["data"]}
    assert ids1.isdisjoint(ids2)


async def test_studies_list_since_filter(async_client: httpx.AsyncClient) -> None:
    """AC-9 studies: ?since=<iso8601> filters out earlier rows."""
    await _seed_studies(3)
    future = quote((datetime.now(UTC) + timedelta(days=365)).isoformat())
    resp = await async_client.get(f"/api/v1/studies?since={future}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []
    assert resp.headers["X-Total-Count"] == "0"


async def test_studies_list_x_total_count_header(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-9 studies: X-Total-Count matches total ignoring pagination."""
    await _seed_studies(5)
    resp = await async_client.get("/api/v1/studies?limit=2")
    assert resp.status_code == 200
    total = int(resp.headers["X-Total-Count"])
    assert total >= 5
    assert len(resp.json()["data"]) == 2


# ---------------------------------------------------------------------------
# /api/v1/query-templates
# ---------------------------------------------------------------------------


async def _seed_query_templates(n: int) -> None:
    factory = get_session_factory()
    async with factory() as db:
        for i in range(n):
            await repo.create_query_template(
                db,
                id=str(uuid.uuid4()),
                name=f"pag-tmpl-{i}-{uuid.uuid4().hex[:6]}",
                engine_type="elasticsearch",
                body='{"query": {"match_all": {}}}',
                declared_params={},
                version=1,
            )
        await db.commit()


async def test_query_templates_list_cursor_pagination(
    async_client: httpx.AsyncClient,
) -> None:
    await _seed_query_templates(60)
    page1 = await async_client.get("/api/v1/query-templates?limit=50")
    assert page1.status_code == 200
    p1 = page1.json()
    assert len(p1["data"]) == 50
    assert p1["has_more"] is True
    page2 = await async_client.get(f"/api/v1/query-templates?limit=50&cursor={p1['next_cursor']}")
    assert page2.status_code == 200


async def test_query_templates_list_since_filter(
    async_client: httpx.AsyncClient,
) -> None:
    future = quote((datetime.now(UTC) + timedelta(days=365)).isoformat())
    resp = await async_client.get(f"/api/v1/query-templates?since={future}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []
    assert resp.headers["X-Total-Count"] == "0"


async def test_query_templates_list_x_total_count_header(
    async_client: httpx.AsyncClient,
) -> None:
    await _seed_query_templates(3)
    resp = await async_client.get("/api/v1/query-templates?limit=1")
    assert resp.status_code == 200
    assert int(resp.headers["X-Total-Count"]) >= 3


# ---------------------------------------------------------------------------
# /api/v1/query-sets
# ---------------------------------------------------------------------------


async def _seed_query_sets(n: int) -> tuple[str, list[str]]:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"pag-qs-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        ids: list[str] = []
        for i in range(n):
            qs = await repo.create_query_set(
                db,
                id=str(uuid.uuid4()),
                name=f"pag-qs-{i}-{uuid.uuid4().hex[:6]}",
                cluster_id=cluster.id,
            )
            ids.append(qs.id)
        await db.commit()
        return cluster.id, ids


async def test_query_sets_list_cursor_pagination(
    async_client: httpx.AsyncClient,
) -> None:
    await _seed_query_sets(60)
    page1 = await async_client.get("/api/v1/query-sets?limit=50")
    assert page1.status_code == 200
    p1 = page1.json()
    assert len(p1["data"]) == 50
    page2 = await async_client.get(f"/api/v1/query-sets?limit=50&cursor={p1['next_cursor']}")
    assert page2.status_code == 200


async def test_query_sets_list_since_filter(async_client: httpx.AsyncClient) -> None:
    future = quote((datetime.now(UTC) + timedelta(days=365)).isoformat())
    resp = await async_client.get(f"/api/v1/query-sets?since={future}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []
    assert resp.headers["X-Total-Count"] == "0"


async def test_query_sets_list_x_total_count_header(
    async_client: httpx.AsyncClient,
) -> None:
    await _seed_query_sets(3)
    resp = await async_client.get("/api/v1/query-sets?limit=1")
    assert resp.status_code == 200
    assert int(resp.headers["X-Total-Count"]) >= 3


# ---------------------------------------------------------------------------
# /api/v1/studies/{id}/trials
# ---------------------------------------------------------------------------


async def _seed_trials(n: int) -> str:
    """Seed N trials under a fresh study; return the study_id."""
    await _seed_studies(1)
    factory = get_session_factory()
    async with factory() as db:
        from sqlalchemy import select

        study_id_row = await db.execute(select(Study.id).order_by(Study.created_at.desc()).limit(1))
        study_id = study_id_row.scalar_one()
        for i in range(n):
            trial = Trial(
                id=str(uuid.uuid4()),
                study_id=study_id,
                optuna_trial_number=i,
                params={"k": 0.5},
                primary_metric=float(n - i),
                metrics={"ndcg@10": float(n - i)},
                duration_ms=100,
                status="complete",
                error=None,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
            )
            db.add(trial)
        await db.commit()
        return study_id


async def test_trials_list_cursor_pagination(async_client: httpx.AsyncClient) -> None:
    """AC-9 trials: cursor pagination round-trip."""
    study_id = await _seed_trials(60)
    page1 = await async_client.get(
        f"/api/v1/studies/{study_id}/trials?limit=50&sort=optuna_trial_number_asc"
    )
    assert page1.status_code == 200
    p1 = page1.json()
    assert len(p1["data"]) == 50
    assert p1["has_more"] is True
    page2 = await async_client.get(
        f"/api/v1/studies/{study_id}/trials?limit=50&sort=optuna_trial_number_asc"
        f"&cursor={p1['next_cursor']}"
    )
    assert page2.status_code == 200


async def test_trials_list_since_filter(async_client: httpx.AsyncClient) -> None:
    study_id = await _seed_trials(3)
    future = quote((datetime.now(UTC) + timedelta(days=365)).isoformat())
    resp = await async_client.get(
        f"/api/v1/studies/{study_id}/trials?since={future}&sort=optuna_trial_number_asc"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == []
    assert resp.headers["X-Total-Count"] == "0"


async def test_trials_list_x_total_count_header(
    async_client: httpx.AsyncClient,
) -> None:
    study_id = await _seed_trials(5)
    resp = await async_client.get(
        f"/api/v1/studies/{study_id}/trials?limit=2&sort=optuna_trial_number_asc"
    )
    assert resp.status_code == 200
    assert int(resp.headers["X-Total-Count"]) == 5
