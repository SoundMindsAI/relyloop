# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``dispatch_run_query`` unit tests (Story 3.4 / 5.1).

Verifies the wrapper around ``ElasticAdapter.search_batch``:

* Happy path returns the hits keyed under ``run_query`` query_id.
* ``InvalidQueryDSLError`` from the adapter propagates verbatim.
* ``ClusterUnreachableError`` from the adapter propagates verbatim.
* The outer ``asyncio.wait_for`` guard surfaces as ``QueryTimeoutError`` even
  when httpx itself ignores the deadline.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
)
from backend.app.core.settings import get_settings
from backend.app.services.cluster import dispatch_run_query


@pytest.fixture(autouse=True)
def _stub_credentials(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yaml"
    creds.write_text("ref:\n  username: u\n  password: p\n")
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "db_url"))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(tmp_path / "pg_pw"))
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    (tmp_path / "db_url").write_text("postgresql+asyncpg://u:p@h/d")
    (tmp_path / "pg_pw").write_text("p")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _adapter(handler) -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="id",
        engine_type="elasticsearch",
        base_url="http://es:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class TestDispatchRunQuery:
    async def test_happy_path_returns_hits(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"responses": [{"hits": {"hits": [{"_id": "doc-1", "_score": 0.9}]}}]},
            )

        adapter = _adapter(handler)
        try:
            hits = await dispatch_run_query(
                adapter,
                target="products",
                query_dsl={"match_all": {}},
                top_k=10,
                timeout_s=5.0,
            )
        finally:
            await adapter.aclose()
        assert len(hits) == 1
        assert hits[0].doc_id == "doc-1"

    async def test_invalid_dsl_propagates(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"responses": [{"error": {"type": "parsing_exception", "reason": "boom"}}]},
            )

        adapter = _adapter(handler)
        try:
            with pytest.raises(InvalidQueryDSLError):
                await dispatch_run_query(
                    adapter,
                    target="products",
                    query_dsl={"bogus": {}},
                    top_k=10,
                    timeout_s=5.0,
                )
        finally:
            await adapter.aclose()

    async def test_cluster_error_propagates(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope", request=req)

        adapter = _adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await dispatch_run_query(
                    adapter,
                    target="products",
                    query_dsl={"match_all": {}},
                    top_k=10,
                    timeout_s=5.0,
                )
        finally:
            await adapter.aclose()

    async def test_outer_wait_for_timeout(self) -> None:
        """When the adapter hangs past timeout_s + 1, asyncio.wait_for fires."""

        async def slow_search(*args, **kwargs):
            await asyncio.sleep(5.0)
            return {}

        # Build a real adapter to keep the type contract, but replace
        # search_batch with our slow stub.
        adapter = _adapter(
            lambda req: httpx.Response(200, json={"responses": [{"hits": {"hits": []}}]})
        )
        adapter.search_batch = slow_search  # type: ignore[method-assign]
        try:
            with pytest.raises(QueryTimeoutError):
                await dispatch_run_query(
                    adapter,
                    target="products",
                    query_dsl={"match_all": {}},
                    top_k=10,
                    timeout_s=0.1,  # outer wall-clock = 1.1s; slow stub sleeps 5s
                )
        finally:
            await adapter.aclose()
