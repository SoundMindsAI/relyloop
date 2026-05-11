"""AC-8 — CSV bulk upload to /api/v1/query-sets/{id}/queries (Story 3.2).

Round-trip: POST a 50-row CSV → 201 + ``{added: 50}`` → GET
``/query-sets/{id}`` returns ``query_count: 50``. The unit-test layer
(``tests/unit/domain/test_csv_parser.py``) covers every parser error
path. This integration test ensures the router + repo + DB chain
honours the contract.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _create_cluster() -> str:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"csv-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        await db.commit()
    return cluster.id


async def test_csv_upload_50_rows_round_trip(async_client: httpx.AsyncClient) -> None:
    """AC-8: POST CSV → 201 + ``{added: 50}`` → GET query_count == 50."""
    cluster_id = await _create_cluster()

    create_resp = await async_client.post(
        "/api/v1/query-sets",
        json={
            "name": f"qs-csv-{uuid.uuid4().hex[:8]}",
            "description": "csv upload test",
            "cluster_id": cluster_id,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    query_set_id = create_resp.json()["id"]
    assert create_resp.json()["query_count"] == 0

    csv_rows = "\n".join(f"how do i do thing {i},answer {i}" for i in range(50))
    csv_body = f"query_text,reference_answer\n{csv_rows}\n"
    upload_resp = await async_client.post(
        f"/api/v1/query-sets/{query_set_id}/queries",
        content=csv_body.encode("utf-8"),
        headers={"Content-Type": "text/csv"},
    )
    assert upload_resp.status_code == 201, upload_resp.text
    assert upload_resp.json()["added"] == 50

    detail = await async_client.get(f"/api/v1/query-sets/{query_set_id}")
    assert detail.status_code == 200
    assert detail.json()["query_count"] == 50


async def test_json_upload_round_trip(async_client: httpx.AsyncClient) -> None:
    """JSON upload path round-trip."""
    cluster_id = await _create_cluster()
    create_resp = await async_client.post(
        "/api/v1/query-sets",
        json={
            "name": f"qs-json-{uuid.uuid4().hex[:8]}",
            "cluster_id": cluster_id,
        },
    )
    assert create_resp.status_code == 201
    query_set_id = create_resp.json()["id"]

    payload = {
        "queries": [
            {"query_text": "alpha", "query_metadata": {"intent": "greeting"}},
            {"query_text": "bravo"},
        ]
    }
    upload_resp = await async_client.post(
        f"/api/v1/query-sets/{query_set_id}/queries",
        json=payload,
    )
    assert upload_resp.status_code == 201, upload_resp.text
    assert upload_resp.json()["added"] == 2


async def test_query_set_create_missing_cluster_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """POST /query-sets with unknown cluster_id → 404 CLUSTER_NOT_FOUND."""
    resp = await async_client.post(
        "/api/v1/query-sets",
        json={
            "name": f"qs-bad-{uuid.uuid4().hex[:8]}",
            "cluster_id": "nonexistent",
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"
