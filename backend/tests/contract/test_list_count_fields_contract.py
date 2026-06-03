# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract assertions for the list-summary count fields (feat_list_count_columns).

Asserts the OpenAPI schema documents:

* ``QuerySetSummary.query_count`` as a required integer.
* ``QueryTemplateSummary.param_count`` as a required integer.

These guard the wire contract the frontend's generated ``types.ts``
consumes — if a future edit drops either field from the summary model,
the freshness gate would catch the snapshot drift but this test pins the
*shape* (type + required-ness) explicitly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

_skip_if_no_pg = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — router resolves get_db at boot",
)


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


@_skip_if_no_pg
async def test_query_set_summary_documents_query_count(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()["components"]["schemas"]["QuerySetSummary"]
    props = schema["properties"]
    assert "query_count" in props, "QuerySetSummary missing query_count"
    assert props["query_count"]["type"] == "integer"
    assert "query_count" in schema["required"], "query_count must be required"


@_skip_if_no_pg
async def test_query_template_summary_documents_param_count(
    async_client: httpx.AsyncClient,
) -> None:
    resp = await async_client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()["components"]["schemas"]["QueryTemplateSummary"]
    props = schema["properties"]
    assert "param_count" in props, "QueryTemplateSummary missing param_count"
    assert props["param_count"]["type"] == "integer"
    assert "param_count" in schema["required"], "param_count must be required"
