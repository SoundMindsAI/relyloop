# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter.search_batch`` unit tests via httpx.MockTransport (Story 2.5).

Covers FR-3 + AC-4 (single _msearch call) plus the strict_errors / timeout
contract finalized in cycle 1 F7 + cycle 1 F9 + cycle 2 F2.

Cases:
* AC-4: 5-query batch → exactly **one** HTTP call observed; query_id mapping
  preserved (each query's hits keyed under its own query_id).
* Per-query parsing_exception with strict_errors=False → empty list for that
  query_id (hot-path / Optuna trial runner contract).
* Per-query parsing_exception with strict_errors=True → InvalidQueryDSLError
  (run_query API path contract).
* Cluster connection error → ClusterUnreachableError.
* Read timeout (strict=True) → QueryTimeoutError; (strict=False) →
  ClusterUnreachableError (so trials degrade rather than abort).
* Empty queries list → empty dict, no HTTP call.
* 400 top-level → InvalidQueryDSLError when strict, ClusterUnreachableError
  when not strict.
* 5xx → ClusterUnreachableError.
* 401 → ClusterUnreachableError.
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
)
from backend.app.adapters.protocol import NativeQuery
from backend.app.core.settings import get_settings


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


def _build_adapter(handler) -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="id",
        engine_type="elasticsearch",
        base_url="http://es:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _query(query_id: str) -> NativeQuery:
    return NativeQuery(query_id=query_id, body={"query": {"match": {"title": query_id}}})


class TestSingleMsearchCall:
    async def test_five_queries_one_http_call(self) -> None:
        """AC-4: 5-query batch produces exactly one _msearch HTTP call."""
        call_count: list[int] = []

        def handler(req: httpx.Request) -> httpx.Response:
            call_count.append(1)
            assert req.url.path == "/_msearch"
            assert req.headers["content-type"] == "application/x-ndjson"
            return httpx.Response(
                200,
                json={
                    "responses": [
                        {"hits": {"hits": [{"_id": f"d-{i}", "_score": 1.0 - i * 0.1}]}}
                        for i in range(5)
                    ]
                },
            )

        adapter = _build_adapter(handler)
        try:
            queries = [_query(f"q-{i}") for i in range(5)]
            result = await adapter.search_batch("products", queries, top_k=10)
        finally:
            await adapter.aclose()
        assert len(call_count) == 1
        # Each query_id keyed in result.
        assert set(result.keys()) == {f"q-{i}" for i in range(5)}
        assert result["q-0"][0].doc_id == "d-0"
        assert result["q-0"][0].score == 1.0


class TestPerQueryErrors:
    async def test_parsing_exception_strict_false_yields_empty(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "responses": [
                        {"hits": {"hits": [{"_id": "d1", "_score": 0.5}]}},
                        {
                            "error": {
                                "type": "parsing_exception",
                                "reason": "malformed",
                            }
                        },
                    ]
                },
            )

        adapter = _build_adapter(handler)
        try:
            result = await adapter.search_batch("products", [_query("ok"), _query("bad")], top_k=10)
        finally:
            await adapter.aclose()
        assert result["ok"][0].doc_id == "d1"
        assert result["bad"] == []

    async def test_parsing_exception_strict_true_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "responses": [
                        {
                            "error": {
                                "type": "parsing_exception",
                                "reason": "expected ]",
                            }
                        }
                    ]
                },
            )

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(InvalidQueryDSLError, match="expected"):
                await adapter.search_batch(
                    "products",
                    [_query("bad")],
                    top_k=10,
                    strict_errors=True,
                )
        finally:
            await adapter.aclose()

    async def test_other_per_query_error_strict_true_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"responses": [{"error": {"type": "shard_failure", "reason": "shard down"}}]},
            )

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="shard down"):
                await adapter.search_batch(
                    "products",
                    [_query("q")],
                    top_k=10,
                    strict_errors=True,
                )
        finally:
            await adapter.aclose()


class TestConnectionAndTimeout:
    async def test_connection_error_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope", request=req)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.search_batch("products", [_query("q")], top_k=10)
        finally:
            await adapter.aclose()

    async def test_read_timeout_strict_raises_query_timeout(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=req)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(QueryTimeoutError):
                await adapter.search_batch(
                    "products",
                    [_query("q")],
                    top_k=10,
                    strict_errors=True,
                )
        finally:
            await adapter.aclose()

    async def test_read_timeout_non_strict_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=req)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.search_batch("products", [_query("q")], top_k=10)
        finally:
            await adapter.aclose()


class TestEmptyAndStatusCodes:
    async def test_empty_queries_returns_empty_dict_no_http_call(self) -> None:
        call_count: list[int] = []

        def handler(req: httpx.Request) -> httpx.Response:
            call_count.append(1)
            return httpx.Response(200, json={})

        adapter = _build_adapter(handler)
        try:
            result = await adapter.search_batch("products", [], top_k=10)
        finally:
            await adapter.aclose()
        assert result == {}
        assert call_count == []

    async def test_top_level_400_strict_raises_invalid(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="bad request")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(InvalidQueryDSLError):
                await adapter.search_batch(
                    "products",
                    [_query("q")],
                    top_k=10,
                    strict_errors=True,
                )
        finally:
            await adapter.aclose()

    async def test_top_level_400_non_strict_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="bad request")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="HTTP 400"):
                await adapter.search_batch("products", [_query("q")], top_k=10)
        finally:
            await adapter.aclose()

    async def test_5xx_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.search_batch("products", [_query("q")], top_k=10)
        finally:
            await adapter.aclose()

    async def test_401_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="Authentication"):
                await adapter.search_batch("products", [_query("q")], top_k=10)
        finally:
            await adapter.aclose()


class TestSizeDefaulting:
    async def test_top_k_applied_to_each_query(self) -> None:
        captured_body: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_body.append(req.content.decode())
            return httpx.Response(200, json={"responses": [{"hits": {"hits": []}}]})

        adapter = _build_adapter(handler)
        try:
            await adapter.search_batch("products", [_query("q")], top_k=42)
        finally:
            await adapter.aclose()
        # The NDJSON body's second line is the query body — assert size=42 is set.
        body = captured_body[0]
        assert '"size": 42' in body or '"size":42' in body
