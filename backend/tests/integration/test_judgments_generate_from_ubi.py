# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``POST /api/v1/judgments/generate-from-ubi``
(feat_ubi_judgments Story 3.2 / FR-3 + FR-4).

Seeds cluster + query set via repo (no ES dependency), monkeypatches the
adapter probe + count so the dispatcher preflight reaches INSERT, and
asserts the row + ``generation_params`` JSONB landed. Mirrors
``test_judgments_api.py`` for the async_client fixture usage.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from backend.app.adapters.protocol import Schema
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.services import agent_judgments_dispatch as dispatch
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed() -> dict[str, str]:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"ubi-ep-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="opensearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="opensearch_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"ubi-ep-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        await repo.create_query(db, id=str(uuid.uuid4()), query_set_id=qs.id, query_text="q")
        await db.commit()
    return {"cluster_id": cluster.id, "query_set_id": qs.id}


def _patch_preflight(monkeypatch: pytest.MonkeyPatch, *, observed: int) -> None:
    """Stub the adapter probe + the U-D2 count so preflight reaches INSERT."""
    adapter = type(
        "A",
        (),
        {
            "engine_type": "opensearch",
            "get_schema": staticmethod(
                lambda *a, **k: _coro(Schema(name="ubi_queries", fields=[]))
            ),
            "aclose": staticmethod(lambda: _coro(None)),
        },
    )()
    monkeypatch.setattr(dispatch, "build_adapter", lambda c: adapter)

    async def _count(*a: Any, **k: Any) -> int:
        return observed

    monkeypatch.setattr(dispatch, "count_ubi_events_in_window", _count)


def _coro(value: Any):
    async def _inner() -> Any:
        return value

    return _inner()


def _body(cluster_id: str, query_set_id: str, **overrides: Any) -> dict[str, Any]:
    b: dict[str, Any] = {
        "name": f"ubi-list-{uuid.uuid4().hex[:8]}",
        "query_set_id": query_set_id,
        "cluster_id": cluster_id,
        "target": "products",
        "since": "2026-05-01T00:00:00+00:00",
        "until": "2026-05-28T00:00:00+00:00",
        "converter": "ctr_threshold",
    }
    b.update(overrides)
    return b


async def test_happy_path_202_persists_generation_params(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed()
    _patch_preflight(monkeypatch, observed=500)
    resp = await async_client.post(
        "/api/v1/judgments/generate-from-ubi",
        json=_body(seeded["cluster_id"], seeded["query_set_id"]),
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "generating"
    jl_id = body["judgment_list_id"]

    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.get_judgment_list(db, jl_id)
        assert jl is not None
        assert jl.generation_params is not None
        assert jl.generation_params["generation_kind"] == "ubi"
        assert jl.generation_params["converter"] == "ctr_threshold"


async def test_insufficient_data_returns_422(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed()
    _patch_preflight(monkeypatch, observed=3)  # below default threshold 100
    resp = await async_client.post(
        "/api/v1/judgments/generate-from-ubi",
        json=_body(seeded["cluster_id"], seeded["query_set_id"]),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "UBI_INSUFFICIENT_DATA"


async def test_ubi_not_enabled_returns_412(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = await _seed()
    from backend.app.adapters.errors import TargetNotFoundError

    adapter = type(
        "A",
        (),
        {
            "engine_type": "opensearch",
            "get_schema": staticmethod(
                lambda *a, **k: _raise_coro(TargetNotFoundError("ubi_queries"))
            ),
            "aclose": staticmethod(lambda: _coro(None)),
        },
    )()
    monkeypatch.setattr(dispatch, "build_adapter", lambda c: adapter)
    resp = await async_client.post(
        "/api/v1/judgments/generate-from-ubi",
        json=_body(seeded["cluster_id"], seeded["query_set_id"]),
    )
    assert resp.status_code == 412
    assert resp.json()["detail"]["error_code"] == "UBI_NOT_ENABLED"


async def test_hybrid_without_template_returns_422(async_client: httpx.AsyncClient) -> None:
    seeded = await _seed()
    resp = await async_client.post(
        "/api/v1/judgments/generate-from-ubi",
        json=_body(
            seeded["cluster_id"],
            seeded["query_set_id"],
            converter="hybrid_ubi_llm",
        ),
    )
    # Pydantic model_validator rejects before the dispatcher runs.
    assert resp.status_code == 422


def _raise_coro(exc: Exception):
    async def _inner() -> Any:
        raise exc

    return _inner()
