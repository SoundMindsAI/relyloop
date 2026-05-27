"""``ElasticAdapter.list_documents`` unit tests (Story 1.3, feat_index_document_browser FR-2).

Locked behaviors:

* Request body includes ``"track_total_hits": true`` so the engine returns
  exact totals beyond 10000 (spec D-24).
* ``search_after`` round-trips into the body when present.
* ``fields=[...]`` becomes ``"_source": {"includes": [...]}`` in the body.
* Response shape extracts ``hits.hits[*]._id / _source / sort`` into
  ``AdapterDocumentHit`` and ``hits.total.value`` into ``DocumentPage.total``.
* 401 / 403 → ``TargetsForbiddenError`` (cycle-1 F6).
* 404 ``index_not_found_exception`` → ``TargetNotFoundError``.
* 5xx → ``ClusterUnreachableError``.
* Per-hit ``sort`` is the engine's literal value (cycle-2 F10 — failure mode
  is loud KeyError if engine omits sort under a sort: [...] query).
* URL encoding on the target path segment (spec D-25).
"""

from __future__ import annotations

import json
from typing import Any

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


def _ok_response(hits: list[dict[str, Any]], total: int) -> httpx.Response:
    """Build a minimal _search response body matching ES/OpenSearch shape."""
    return httpx.Response(
        200,
        json={
            "took": 1,
            "timed_out": False,
            "hits": {
                "total": {"value": total, "relation": "eq"},
                "max_score": None,
                "hits": hits,
            },
        },
    )


class TestListDocuments:
    """ElasticAdapter.list_documents — paginated browse contract."""

    @pytest.mark.asyncio
    async def test_happy_path_extracts_hits_total_sort(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            assert req.method == "POST"
            assert req.url.path == "/products/_search"
            return _ok_response(
                hits=[
                    {"_id": "a", "_source": {"title": "Alpha"}, "sort": ["a"]},
                    {"_id": "b", "_source": {"title": "Beta"}, "sort": ["b"]},
                    {"_id": "c", "_source": {"title": "Gamma"}, "sort": ["c"]},
                ],
                total=1847,
            )

        adapter = _build_adapter(handler)
        try:
            page = await adapter.list_documents("products", limit=3)
        finally:
            await adapter.aclose()
        assert len(page.hits) == 3
        assert page.total == 1847
        assert page.hits[0].doc_id == "a"
        assert page.hits[0].sort == ["a"]
        assert page.hits[2].sort == ["c"]

    @pytest.mark.asyncio
    async def test_request_body_track_total_hits_true(self) -> None:
        """Cycle-3 F2 / D-24 — request body MUST include track_total_hits: true."""
        captured_bodies: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(req.content))
            return _ok_response(hits=[], total=0)

        adapter = _build_adapter(handler)
        try:
            await adapter.list_documents("products", limit=25)
        finally:
            await adapter.aclose()
        body = captured_bodies[0]
        assert body["track_total_hits"] is True
        assert body["query"] == {"match_all": {}}
        assert body["sort"] == [{"_id": "asc"}]
        assert body["size"] == 25

    @pytest.mark.asyncio
    async def test_search_after_round_trips_into_body(self) -> None:
        captured_bodies: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(req.content))
            return _ok_response(hits=[], total=0)

        adapter = _build_adapter(handler)
        try:
            await adapter.list_documents("products", search_after=["prod-050"], limit=10)
        finally:
            await adapter.aclose()
        assert captured_bodies[0]["search_after"] == ["prod-050"]
        assert captured_bodies[0]["size"] == 10

    @pytest.mark.asyncio
    async def test_search_after_absent_when_not_provided(self) -> None:
        captured_bodies: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(req.content))
            return _ok_response(hits=[], total=0)

        adapter = _build_adapter(handler)
        try:
            await adapter.list_documents("products", limit=10)
        finally:
            await adapter.aclose()
        assert "search_after" not in captured_bodies[0]

    @pytest.mark.asyncio
    async def test_fields_become_source_includes(self) -> None:
        captured_bodies: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(req.content))
            return _ok_response(hits=[], total=0)

        adapter = _build_adapter(handler)
        try:
            await adapter.list_documents("products", fields=["title", "brand"])
        finally:
            await adapter.aclose()
        assert captured_bodies[0]["_source"] == {"includes": ["title", "brand"]}

    @pytest.mark.asyncio
    async def test_no_source_includes_when_fields_none(self) -> None:
        captured_bodies: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(req.content))
            return _ok_response(hits=[], total=0)

        adapter = _build_adapter(handler)
        try:
            await adapter.list_documents("products")
        finally:
            await adapter.aclose()
        assert "_source" not in captured_bodies[0]

    @pytest.mark.asyncio
    async def test_empty_hits_returns_empty_page(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return _ok_response(hits=[], total=0)

        adapter = _build_adapter(handler)
        try:
            page = await adapter.list_documents("products")
        finally:
            await adapter.aclose()
        assert page.hits == []
        assert page.total == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 403])
    async def test_acl_denial_raises_targets_forbidden(self, status: int) -> None:
        """Cycle-1 F6 — 401/403 → TargetsForbiddenError (NOT ClusterUnreachable)."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text="forbidden")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetsForbiddenError):
                await adapter.list_documents("products")
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_index_missing_raises_target_not_found(self) -> None:
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
                await adapter.list_documents("nope")
        finally:
            await adapter.aclose()
        assert exc_info.value.target == "nope"

    @pytest.mark.asyncio
    async def test_5xx_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="cluster down")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.list_documents("products")
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_connection_error_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.list_documents("products")
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_missing_sort_field_fails_loud(self) -> None:
        """Cycle-2 F10 — if engine omits ``sort`` (e.g., refactor regression), the
        adapter MUST fail loud (KeyError) rather than silently default to []."""

        def handler(req: httpx.Request) -> httpx.Response:
            return _ok_response(
                hits=[{"_id": "a", "_source": {"x": 1}}],  # NO sort field
                total=1,
            )

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(KeyError):
                await adapter.list_documents("products")
        finally:
            await adapter.aclose()

    @pytest.mark.asyncio
    async def test_target_url_encoded_on_wire(self) -> None:
        """Spec D-25 — target segment is URL-encoded before path interpolation."""
        captured_raw_paths: list[bytes] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_raw_paths.append(req.url.raw_path)
            return _ok_response(hits=[], total=0)

        adapter = _build_adapter(handler)
        try:
            await adapter.list_documents("ns/index")
        finally:
            await adapter.aclose()
        assert captured_raw_paths[0] == b"/ns%2Findex/_search"
