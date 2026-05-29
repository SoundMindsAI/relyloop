"""Integration tests for ``GET /api/v1/clusters/{id}/ubi-readiness``
(feat_ubi_judgments Story 3.1 / FR-7).

Seeds the cluster + query set via the repo layer (no ES dependency) and
monkeypatches ``classify_rung`` + ``acquire_adapter`` so the endpoint
exercises the real router → DB-resolve → response-model path without a
live engine. Mirrors ``test_clusters_api_targets_errors.py``'s
acquire_adapter-stub pattern.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.services import cluster as cluster_svc
from backend.app.services.ubi_readiness import UbiReadiness
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_cluster_and_query_set() -> dict[str, str]:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"ubi-rd-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="opensearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="opensearch_basic",
            credentials_ref="ref",
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"ubi-rd-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        await repo.create_query(
            db, id=str(uuid.uuid4()), query_set_id=query_set.id, query_text="red shoes"
        )
        await db.commit()
    return {"cluster_id": cluster.id, "query_set_id": query_set.id}


def _patch_adapter_and_rung(monkeypatch: pytest.MonkeyPatch, rung: str) -> None:
    @asynccontextmanager
    async def _acquire(cluster: Any):
        adapter = object()
        try:
            yield adapter
        finally:
            pass

    monkeypatch.setattr(cluster_svc, "acquire_adapter", _acquire)

    async def _classify(**kwargs: Any) -> UbiReadiness:
        return UbiReadiness(
            rung=rung,  # type: ignore[arg-type]
            covered_pairs_pct=None,
            head_covered=None,
            checked_at=datetime.now(UTC),
        )

    monkeypatch.setattr("backend.app.api.v1.clusters.classify_rung", _classify)


async def test_missing_cluster_returns_404(async_client: httpx.AsyncClient) -> None:
    resp = await async_client.get(
        f"/api/v1/clusters/{uuid.uuid4()}/ubi-readiness",
        params={"query_set_id": str(uuid.uuid4()), "target": "products"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


async def test_missing_query_set_returns_404(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed_cluster_and_query_set()
    resp = await async_client.get(
        f"/api/v1/clusters/{seeded['cluster_id']}/ubi-readiness",
        params={"query_set_id": str(uuid.uuid4()), "target": "products"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_NOT_FOUND"


async def test_missing_query_params_returns_422(async_client: httpx.AsyncClient) -> None:
    seeded = await _seed_cluster_and_query_set()
    resp = await async_client.get(f"/api/v1/clusters/{seeded['cluster_id']}/ubi-readiness")
    assert resp.status_code == 422


@pytest.mark.parametrize("rung", ["rung_0", "rung_1", "rung_2", "rung_3"])
async def test_each_rung_returns_200_shape(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, rung: str
) -> None:
    seeded = await _seed_cluster_and_query_set()
    _patch_adapter_and_rung(monkeypatch, rung)
    resp = await async_client.get(
        f"/api/v1/clusters/{seeded['cluster_id']}/ubi-readiness",
        params={"query_set_id": seeded["query_set_id"], "target": "products"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rung"] == rung
    assert set(body.keys()) == {"rung", "covered_pairs_pct", "head_covered", "checked_at"}
