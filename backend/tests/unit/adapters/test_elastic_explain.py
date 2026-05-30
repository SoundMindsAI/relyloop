# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter.explain`` unit tests via httpx.MockTransport (Story 2.6).

Covers the recursive ``ExplainTree`` shape + the 404/auth/5xx error mapping.
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.errors import ClusterUnreachableError, TargetNotFoundError
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


class TestExplainTree:
    async def test_matched_doc_returns_recursive_tree(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "matched": True,
                    "explanation": {
                        "value": 1.5,
                        "description": "sum of:",
                        "details": [
                            {
                                "value": 0.8,
                                "description": "weight(title:shoes)",
                                "details": [],
                            },
                            {
                                "value": 0.7,
                                "description": "boost",
                                "details": [],
                            },
                        ],
                    },
                },
            )

        adapter = _build_adapter(handler)
        try:
            tree = await adapter.explain(
                "products",
                NativeQuery(query_id="q", body={"query": {"match": {"title": "shoes"}}}),
                "doc-1",
            )
        finally:
            await adapter.aclose()
        assert tree.doc_id == "doc-1"
        assert tree.matched is True
        assert tree.value == 1.5
        assert len(tree.details) == 2
        assert tree.details[0].value == 0.8
        assert tree.details[0].description == "weight(title:shoes)"

    async def test_unmatched_doc(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "matched": False,
                    "explanation": {"value": 0.0, "description": "no match", "details": []},
                },
            )

        adapter = _build_adapter(handler)
        try:
            tree = await adapter.explain(
                "products",
                NativeQuery(query_id="q", body={"query": {"match_none": {}}}),
                "doc-1",
            )
        finally:
            await adapter.aclose()
        assert tree.matched is False
        assert tree.value == 0.0


class TestExplainErrors:
    async def test_404_raises_target_not_found(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetNotFoundError):
                await adapter.explain(
                    "missing",
                    NativeQuery(query_id="q", body={}),
                    "doc-1",
                )
        finally:
            await adapter.aclose()

    async def test_401_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.explain(
                    "products",
                    NativeQuery(query_id="q", body={}),
                    "doc-1",
                )
        finally:
            await adapter.aclose()

    async def test_connection_error_raises_unreachable(self) -> None:
        """bug_get_schema_unhandled_connect_error (bundled): connection
        failure → translated to ClusterUnreachableError instead of leaking
        the raw httpx exception as 500 INTERNAL_ERROR.
        """

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.explain(
                    "products",
                    NativeQuery(query_id="q", body={}),
                    "doc-1",
                )
        finally:
            await adapter.aclose()
