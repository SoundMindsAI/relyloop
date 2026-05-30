# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter.get_document`` unit tests (Story 1.2, feat_index_document_browser FR-2).

Covers the 6 paths the plan locks for the get_document contract:

* Happy path (200 with _source) → ``Document(doc_id, source)``.
* Engine ``found: false`` (404) → returns ``None`` (not an exception).
* Index missing (404 with ``error.type == "index_not_found_exception"``) →
  ``TargetNotFoundError``.
* Engine has ``_source: false`` mapping → ``Document(doc_id, source=None)``.
* 401 / 403 → ``TargetsForbiddenError`` (matches list_targets pattern; spec FR-1
  cycle-1 F6).
* 5xx → ``ClusterUnreachableError``.

Plus the URL-encoding assertion (spec D-25 + AC-16): an id containing ``/`` is
url-encoded before path interpolation so the engine receives ``%2F``.
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    TargetNotFoundError,
    TargetsForbiddenError,
)
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


class TestGetDocument:
    """ElasticAdapter.get_document — six error paths + URL encoding."""

    @pytest.mark.asyncio
    async def test_success_returns_document(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            assert req.method == "GET"
            assert req.url.path == "/products/_doc/prod-001"
            return httpx.Response(
                200,
                json={
                    "_index": "products",
                    "_id": "prod-001",
                    "found": True,
                    "_source": {"title": "Apple Watch", "price": 199.0},
                },
            )

        adapter = _build_adapter(handler)
        try:
            doc = await adapter.get_document("products", "prod-001")
        finally:
            await adapter.aclose()
        assert doc is not None
        assert doc.doc_id == "prod-001"
        assert doc.source == {"title": "Apple Watch", "price": 199.0}

    @pytest.mark.asyncio
    async def test_doc_missing_returns_none(self) -> None:
        """Engine ``found: false`` is not an error — returns None."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={"_index": "products", "_id": "prod-9999", "found": False},
            )

        adapter = _build_adapter(handler)
        try:
            doc = await adapter.get_document("products", "prod-9999")
        finally:
            await adapter.aclose()
        assert doc is None

    @pytest.mark.asyncio
    async def test_index_missing_raises_target_not_found(self) -> None:
        """404 with ``index_not_found_exception`` → TargetNotFoundError (not None)."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={
                    "error": {
                        "type": "index_not_found_exception",
                        "reason": "no such index [nope]",
                    },
                    "status": 404,
                },
            )

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetNotFoundError) as exc_info:
                await adapter.get_document("nope", "any-id")
        finally:
            await adapter.aclose()
        assert exc_info.value.target == "nope"

    @pytest.mark.asyncio
    async def test_source_false_index_returns_document_with_none_source(self) -> None:
        """Engine returns 200 without ``_source`` (e.g. mapping has ``_source: false``)."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "_index": "products",
                    "_id": "prod-001",
                    "found": True,
                    # No _source field — index is configured with _source: false.
                },
            )

        adapter = _build_adapter(handler)
        try:
            doc = await adapter.get_document("products", "prod-001")
        finally:
            await adapter.aclose()
        assert doc is not None
        assert doc.doc_id == "prod-001"
        assert doc.source is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_acl_denial_raises_targets_forbidden(self, status: int) -> None:
        """401/403 → TargetsForbiddenError (NOT ClusterUnreachable — distinct router path)."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text="forbidden")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetsForbiddenError):
                await adapter.get_document("products", "prod-001")
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_5xx_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="cluster down")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.get_document("products", "prod-001")
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_connection_error_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.get_document("products", "prod-001")
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_doc_id_with_slash_url_encoded(self) -> None:
        """AC-16 — doc IDs containing ``/`` are URL-encoded as ``%2F`` on the wire.

        Note: ``req.url.path`` returns the percent-decoded path; ``req.url.raw_path``
        returns the wire-form bytes. We assert on raw_path so a regression that
        skips ``urllib.parse.quote`` would surface here.
        """
        captured_raw_paths: list[bytes] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_raw_paths.append(req.url.raw_path)
            return httpx.Response(
                200,
                json={"_id": "https://example.com/p/123", "_source": {"x": 1}},
            )

        adapter = _build_adapter(handler)
        try:
            await adapter.get_document("products", "https://example.com/p/123")
        finally:
            await adapter.aclose()
        # urllib.parse.quote(_, safe="") encodes "/" → %2F and ":" → %3A.
        raw = captured_raw_paths[0]
        assert b"%2F" in raw
        assert b"%3A" in raw
        assert raw.startswith(b"/products/_doc/")

    @pytest.mark.asyncio
    async def test_target_with_special_chars_url_encoded(self) -> None:
        """Target names containing special chars are also URL-encoded (spec D-25).

        Asserts on ``raw_path`` (encoded wire form) — ``req.url.path`` decodes back.
        """
        captured_raw_paths: list[bytes] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_raw_paths.append(req.url.raw_path)
            return httpx.Response(404, json={"found": False})

        adapter = _build_adapter(handler)
        try:
            await adapter.get_document("ns/index", "id-001")
        finally:
            await adapter.aclose()
        assert captured_raw_paths[0] == b"/ns%2Findex/_doc/id-001"
