# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the list-summary count fields (feat_list_count_columns).

Two additions to the list endpoints:

* ``GET /api/v1/query-sets`` items carry ``query_count`` — the number of
  queries in the set, resolved via one batched ``GROUP BY`` aggregate per
  page (``repo.count_queries_for_sets``), NOT a per-row count.
* ``GET /api/v1/query-templates`` items carry ``param_count`` —
  ``len(declared_params)``, free off the already-loaded JSONB column.

All assertions go through the real FastAPI request pipeline via
``async_client`` so the Pydantic response model + serialization are
exercised end-to-end against a real Postgres.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import uuid_utils

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


async def _seed_query_set(num_queries: int) -> str:
    """Seed cluster → query_set → N queries; return the query_set id."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"lcc-c-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"lcc-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        for i in range(num_queries):
            await repo.create_query(
                db,
                id=str(uuid_utils.uuid7()),
                query_set_id=qs.id,
                query_text=f"q-{i}",
                reference_answer=None,
                query_metadata=None,
            )
        await db.commit()
        return str(qs.id)


async def _seed_template(declared_params: dict[str, str]) -> str:
    """Seed a query_template with the given declared_params; return its id."""
    factory = get_session_factory()
    async with factory() as db:
        tmpl = await repo.create_query_template(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"lcc-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params=declared_params,
            version=1,
            parent_id=None,
        )
        await db.commit()
        return str(tmpl.id)


def _find_item(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    for it in items:
        if it["id"] == item_id:
            return it
    raise AssertionError(f"id {item_id} not found in list response")


# ---------------------------------------------------------------------------
# query-sets: query_count
# ---------------------------------------------------------------------------


async def test_query_sets_list_includes_query_count(
    async_client: httpx.AsyncClient,
) -> None:
    """A set with 3 queries reports query_count == 3 in the list."""
    set_id = await _seed_query_set(num_queries=3)
    resp = await async_client.get("/api/v1/query-sets", params={"limit": 200})
    assert resp.status_code == 200, resp.text
    item = _find_item(resp.json()["data"], set_id)
    assert item["query_count"] == 3


async def test_query_sets_list_zero_queries_reports_zero(
    async_client: httpx.AsyncClient,
) -> None:
    """A set with no queries reports query_count == 0 (backfilled, not missing)."""
    set_id = await _seed_query_set(num_queries=0)
    resp = await async_client.get("/api/v1/query-sets", params={"limit": 200})
    assert resp.status_code == 200, resp.text
    item = _find_item(resp.json()["data"], set_id)
    assert item["query_count"] == 0


async def test_query_sets_list_counts_are_per_set(
    async_client: httpx.AsyncClient,
) -> None:
    """Two sets with different cardinalities each get their own count.

    Guards the batched ``GROUP BY`` mapping — a regression that collapsed
    all sets to one count (or mis-keyed the dict) would fail here.
    """
    five_id = await _seed_query_set(num_queries=5)
    one_id = await _seed_query_set(num_queries=1)
    resp = await async_client.get("/api/v1/query-sets", params={"limit": 200})
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]
    assert _find_item(items, five_id)["query_count"] == 5
    assert _find_item(items, one_id)["query_count"] == 1


# ---------------------------------------------------------------------------
# query-templates: param_count
# ---------------------------------------------------------------------------


async def test_templates_list_includes_param_count(
    async_client: httpx.AsyncClient,
) -> None:
    """A template with 3 declared params reports param_count == 3."""
    tmpl_id = await _seed_template({"a": "term", "b": "term", "c": "term"})
    resp = await async_client.get("/api/v1/query-templates", params={"limit": 200})
    assert resp.status_code == 200, resp.text
    item = _find_item(resp.json()["data"], tmpl_id)
    assert item["param_count"] == 3


async def test_templates_list_zero_params_reports_zero(
    async_client: httpx.AsyncClient,
) -> None:
    """A template with no declared params reports param_count == 0."""
    tmpl_id = await _seed_template({})
    resp = await async_client.get("/api/v1/query-templates", params={"limit": 200})
    assert resp.status_code == 200, resp.text
    item = _find_item(resp.json()["data"], tmpl_id)
    assert item["param_count"] == 0
