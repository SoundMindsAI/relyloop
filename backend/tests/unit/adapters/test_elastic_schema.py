"""``ElasticAdapter`` schema + targets unit tests (Story 2.3, AC-2 / FR-4).

Cassette-replay tests live in the integration layer (Epic 2 gate); these
unit-level tests use ``httpx.MockTransport`` so the analyzer-resolution
contract is exercised hermetically.

Cases:
* AC-2: ``_mapping`` for a 4-field ``products`` index → 4 ``FieldSpec`` entries.
* Text field with no explicit analyzer → derived from ``_settings`` default
  (or "standard" when missing); cycle 1 F6 fix verification.
* Text field with explicit analyzer → preserved verbatim.
* Non-text field (``keyword``, ``float``) → ``analyzer = None``.
* ``_field_caps`` is **not** consulted (cycle 2 F5 — track interaction count).
* 404 mapping → ``TargetNotFoundError``.
* Auth/5xx mapping → ``ClusterUnreachableError``.
* ``list_targets`` filters out system indices (names starting with ``.``).
* ``list_query_parsers`` returns the expected static set.
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


PRODUCTS_MAPPING = {
    "products": {
        "mappings": {
            "properties": {
                "title": {"type": "text"},
                "category": {"type": "keyword"},
                "price": {"type": "float"},
                "released_at": {"type": "date"},
            }
        }
    }
}

PRODUCTS_SETTINGS_DEFAULT_STANDARD = {
    "products": {
        "settings": {"index": {"analysis": {"analyzer": {"default": {"type": "standard"}}}}}
    }
}


class TestGetSchemaAC2:
    async def test_four_fields_with_correct_types(self) -> None:
        """AC-2: products index → 4 FieldSpec entries with correct types."""
        paths_called: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            paths_called.append(req.url.path)
            if req.url.path == "/products/_mapping":
                return httpx.Response(200, json=PRODUCTS_MAPPING)
            if req.url.path == "/products/_settings":
                return httpx.Response(200, json=PRODUCTS_SETTINGS_DEFAULT_STANDARD)
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            schema = await adapter.get_schema("products")
        finally:
            await adapter.aclose()
        assert schema.name == "products"
        assert len(schema.fields) == 4
        by_name = {f.name: f for f in schema.fields}
        assert by_name["title"].type == "text"
        assert by_name["title"].analyzer == "standard"
        assert by_name["category"].type == "keyword"
        assert by_name["category"].analyzer is None
        assert by_name["price"].type == "float"
        assert by_name["released_at"].type == "date"
        # cycle 2 F5: _field_caps must NOT be consulted.
        assert "/products/_field_caps" not in paths_called
        # The cassette inventory is just _mapping + _settings.
        assert sorted(paths_called) == ["/products/_mapping", "/products/_settings"]

    async def test_explicit_analyzer_preserved(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/products/_mapping":
                return httpx.Response(
                    200,
                    json={
                        "products": {
                            "mappings": {
                                "properties": {
                                    "title": {
                                        "type": "text",
                                        "analyzer": "english",
                                    }
                                }
                            }
                        }
                    },
                )
            return httpx.Response(200, json=PRODUCTS_SETTINGS_DEFAULT_STANDARD)

        adapter = _build_adapter(handler)
        try:
            schema = await adapter.get_schema("products")
        finally:
            await adapter.aclose()
        title = schema.fields[0]
        assert title.analyzer == "english"

    async def test_settings_failure_falls_back_to_standard(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/products/_mapping":
                return httpx.Response(200, json=PRODUCTS_MAPPING)
            # _settings returns 500 — implementation degrades to "standard".
            return httpx.Response(500, text="boom")

        adapter = _build_adapter(handler)
        try:
            schema = await adapter.get_schema("products")
        finally:
            await adapter.aclose()
        title = next(f for f in schema.fields if f.name == "title")
        assert title.analyzer == "standard"


class TestGetSchemaErrors:
    async def test_404_raises_target_not_found(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetNotFoundError) as exc_info:
                await adapter.get_schema("missing")
        finally:
            await adapter.aclose()
        assert exc_info.value.target == "missing"

    async def test_401_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="auth required")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.get_schema("products")
        finally:
            await adapter.aclose()

    async def test_5xx_raises_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="cluster down")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.get_schema("products")
        finally:
            await adapter.aclose()

    async def test_connection_error_raises_unreachable(self) -> None:
        """bug_get_schema_unhandled_connect_error (bundled with
        feat_create_study_target_autocomplete): connection failure → translated
        to ClusterUnreachableError instead of leaking the raw httpx exception
        as 500 INTERNAL_ERROR. Mirrors the list_targets pattern from B1.
        """

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.get_schema("products")
        finally:
            await adapter.aclose()


class TestListTargets:
    async def test_filters_system_indices(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {"index": ".internal-system", "docs.count": "100"},
                    {"index": "products", "docs.count": "42"},
                    {"index": "orders", "docs.count": ""},
                ],
            )

        adapter = _build_adapter(handler)
        try:
            targets = await adapter.list_targets()
        finally:
            await adapter.aclose()
        names = [t.name for t in targets]
        assert names == ["products", "orders"]
        by_name = {t.name: t for t in targets}
        assert by_name["products"].doc_count == 42
        assert by_name["orders"].doc_count is None

    # ------------------------------------------------------------------
    # feat_create_study_target_autocomplete Story B1 — error mapping
    # ------------------------------------------------------------------

    async def test_401_raises_targets_forbidden(self) -> None:
        """FR-2 / AC-5: 401 from _cat/indices → TargetsForbiddenError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="auth required")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetsForbiddenError):
                await adapter.list_targets()
        finally:
            await adapter.aclose()

    async def test_403_raises_targets_forbidden(self) -> None:
        """FR-2 / AC-5: 403 from _cat/indices → TargetsForbiddenError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(TargetsForbiddenError):
                await adapter.list_targets()
        finally:
            await adapter.aclose()

    async def test_500_raises_unreachable(self) -> None:
        """FR-2 / AC-5: 5xx from _cat/indices → ClusterUnreachableError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal error")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.list_targets()
        finally:
            await adapter.aclose()

    async def test_503_raises_unreachable(self) -> None:
        """FR-2 / AC-5: 503 from _cat/indices → ClusterUnreachableError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="service unavailable")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.list_targets()
        finally:
            await adapter.aclose()

    async def test_connection_error_raises_unreachable(self) -> None:
        """FR-2 / AC-5: connection failure → ClusterUnreachableError (not raw httpx).

        Without the explicit try/except httpx.HTTPError in list_targets(),
        translate_errors=False would let the raw httpx.ConnectError propagate
        and surface as 500 INTERNAL_ERROR at the router instead of 503
        CLUSTER_UNREACHABLE. This test locks that defensive translation.
        """

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError):
                await adapter.list_targets()
        finally:
            await adapter.aclose()


class TestListQueryParsers:
    async def test_returns_static_set(self) -> None:
        adapter = _build_adapter(lambda req: httpx.Response(200))
        try:
            parsers = adapter.list_query_parsers()
        finally:
            await adapter.aclose()
        assert set(parsers) == {
            "match",
            "multi_match",
            "match_phrase",
            "bool",
            "function_score",
        }
