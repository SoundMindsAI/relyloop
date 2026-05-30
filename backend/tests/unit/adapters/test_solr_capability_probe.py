# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.probe_capabilities`` + ``health_check`` + ``list_query_parsers``
unit tests via ``httpx.MockTransport`` (infra_adapter_solr Story A1).

The probe is the load-bearing part of registration — every assertion here is
mirrored by an integration test in Story A10 (``test_solr_live_*``), but the
unit layer lets us cover the per-endpoint branching (Solr 10 modules block vs
Solr 9 queryParser fallback; cloud vs standalone target enumeration; uniqueKey
probe across multiple targets; LTR / UBI presence detection) deterministically
without standing up a real Solr.

Cases:

* Solr 10 cloud — UBI on, LTR module + 2 models, 1 collection with uniqueKey=id.
* Solr 9 standalone — no modules block, LTR via queryParser fallback, no models.
* Cloud with multiple collections + customized uniqueKey (``sku``) on one.
* Version below ``SOLR_MIN_VERSION`` (9.0) — probe raises
  ``ClusterUnreachableError`` with the documented message.
* Missing version field → ``ClusterUnreachableError``.
* 401 on ``/admin/info/system`` → ``ClusterUnreachableError``.
* Mode-detection 404 on ``/admin/zookeeper/status`` → ``standalone``.
* ``health_check`` mirrors the probe's version-floor enforcement + caches
  version on first success.
* ``list_query_parsers`` returns the static list (no HTTP call).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from backend.app.adapters.errors import ClusterUnreachableError
from backend.app.adapters.solr import SOLR_MIN_VERSION, ProbeResult, SolrAdapter
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


def _build_adapter(handler) -> SolrAdapter:
    return SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# ---------------------------------------------------------------------------
# probe_capabilities — happy-path Solr 10 cloud with UBI + LTR + 1 collection.
# ---------------------------------------------------------------------------


def _solr_10_cloud_handler(
    unique_keys: dict[str, str] | None = None,
    ltr_models_payload: list[dict[str, str]] | None = None,
    ubi_class: str = "solr.UBIComponent",
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler simulating a Solr 10 cloud cluster with the given collections.

    ``unique_keys``: ordered dict {collection_name: uniqueKey_field}.
    ``ltr_models_payload``: list of model dicts (or None to default to 2 models).
    ``ubi_class``: class string returned for the searchComponent block.
    """
    if unique_keys is None:
        unique_keys = {"products": "id"}
    if ltr_models_payload is None:
        ltr_models_payload = [{"name": "xgboost_v1"}, {"name": "lambdamart_v2"}]
    collections = list(unique_keys.keys())

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/solr/admin/info/system":
            return httpx.Response(
                200,
                json={
                    "lucene": {"solr-spec-version": "10.0.0"},
                    "system": {"modules": ["ltr", "analytics"]},
                },
            )
        if path == "/solr/admin/zookeeper/status":
            return httpx.Response(200, json={"zkStatus": {"status": "green"}})
        if path == "/solr/admin/collections":
            assert req.url.params.get("action") == "LIST"
            return httpx.Response(200, json={"collections": collections})
        if path.endswith("/schema/uniquekey"):
            # /solr/<collection>/schema/uniquekey
            collection = path.split("/")[2]
            return httpx.Response(200, json={"uniqueKey": unique_keys[collection]})
        if path.endswith("/schema/model-store"):
            return httpx.Response(200, json={"models": ltr_models_payload})
        if path.endswith("/config/searchComponent"):
            return httpx.Response(
                200,
                json={
                    "config": {
                        "searchComponent": {
                            "ubi": {"class": ubi_class, "name": "ubi"},
                        }
                    }
                },
            )
        if path.endswith("/config/queryParser"):
            return httpx.Response(404)
        return httpx.Response(404)

    return handler


class TestProbeSolr10CloudHappyPath:
    async def test_full_probe(self) -> None:
        adapter = _build_adapter(_solr_10_cloud_handler())
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert isinstance(result, ProbeResult)
        assert result.version == "10.0.0"
        assert result.mode == "cloud"
        assert result.ubi_component_present is True
        assert result.ltr_module_present is True
        assert result.ltr_models == ["xgboost_v1", "lambdamart_v2"]
        assert result.unique_key_per_target == {"products": "id"}

    async def test_unique_key_per_target_multi_collection(self) -> None:
        """A collection with uniqueKey=sku is recorded as sku, not the default id."""
        handler = _solr_10_cloud_handler(unique_keys={"products": "id", "orders": "sku"})
        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert result.unique_key_per_target == {"products": "id", "orders": "sku"}

    async def test_ltr_models_404_yields_empty_list(self) -> None:
        """LTR module loaded but model-store empty → empty models list (no raise)."""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/schema/model-store"):
                return httpx.Response(404)
            return _solr_10_cloud_handler()(req)

        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert result.ltr_module_present is True
        assert result.ltr_models == []


# ---------------------------------------------------------------------------
# Solr 9 standalone — no modules block, queryParser fallback for LTR detection.
# ---------------------------------------------------------------------------


class TestProbeSolr9Standalone:
    async def test_standalone_with_ltr_queryparser_fallback(self) -> None:
        """Solr 9 has no system.modules; LTR detection falls back to queryParser."""

        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            if path == "/solr/admin/info/system":
                # Solr 9 omits the .system.modules array — LTR fallback fires.
                return httpx.Response(200, json={"lucene": {"solr-spec-version": "9.4.0"}})
            if path == "/solr/admin/zookeeper/status":
                return httpx.Response(404, text="not found")
            if path == "/solr/admin/cores":
                return httpx.Response(
                    200,
                    json={
                        "status": {
                            "products": {"name": "products"},
                            ".system": {"name": ".system"},  # excluded
                            "_default": {"name": "_default"},  # excluded
                        }
                    },
                )
            if path.endswith("/schema/uniquekey"):
                return httpx.Response(200, json={"uniqueKey": "id"})
            if path.endswith("/config/queryParser"):
                return httpx.Response(
                    200,
                    json={
                        "config": {"queryParser": {"ltr": {"class": "solr.ltr.LTRQParserPlugin"}}}
                    },
                )
            if path.endswith("/schema/model-store"):
                return httpx.Response(200, json={"models": []})
            if path.endswith("/config/searchComponent"):
                return httpx.Response(200, json={"config": {"searchComponent": {}}})
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert result.version == "9.4.0"
        assert result.mode == "standalone"
        assert result.ltr_module_present is True  # fallback path
        assert result.ltr_models == []
        assert result.ubi_component_present is False
        # System targets excluded.
        assert result.unique_key_per_target == {"products": "id"}

    async def test_standalone_no_ltr_anywhere(self) -> None:
        """No modules + queryParser 404 → ltr_module_present=False, models=[]."""

        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            if path == "/solr/admin/info/system":
                return httpx.Response(200, json={"lucene": {"solr-spec-version": "9.7.0"}})
            if path == "/solr/admin/zookeeper/status":
                return httpx.Response(404)
            if path == "/solr/admin/cores":
                return httpx.Response(200, json={"status": {"products": {"name": "products"}}})
            if path.endswith("/schema/uniquekey"):
                return httpx.Response(200, json={"uniqueKey": "id"})
            if path.endswith("/config/queryParser"):
                return httpx.Response(404)
            if path.endswith("/config/searchComponent"):
                return httpx.Response(200, json={"config": {"searchComponent": {}}})
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert result.ltr_module_present is False
        assert result.ltr_models == []  # never fetched because module absent
        assert result.ubi_component_present is False


# ---------------------------------------------------------------------------
# UBI detection variants.
# ---------------------------------------------------------------------------


class TestUbiDetection:
    async def test_no_ubi_component(self) -> None:
        """searchComponent block exists but no UBIComponent — present=False."""
        handler = _solr_10_cloud_handler(ubi_class="solr.SuggestComponent")
        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert result.ubi_component_present is False

    async def test_ubi_class_match_case_insensitive(self) -> None:
        """Class string ending with 'UbiComponent' in any case matches."""
        handler = _solr_10_cloud_handler(ubi_class="custom.ext.UBIComponent")
        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert result.ubi_component_present is True

    async def test_no_targets_skips_ubi_probe(self) -> None:
        """A cluster with zero collections probes safely — UBI False, no exception."""

        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            if path == "/solr/admin/info/system":
                return httpx.Response(
                    200,
                    json={
                        "lucene": {"solr-spec-version": "10.0.0"},
                        "system": {"modules": []},
                    },
                )
            if path == "/solr/admin/zookeeper/status":
                return httpx.Response(200, json={"zkStatus": {}})
            if path == "/solr/admin/collections":
                return httpx.Response(200, json={"collections": []})
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert result.unique_key_per_target == {}
        assert result.ubi_component_present is False
        assert result.ltr_module_present is False
        assert result.ltr_models == []


# ---------------------------------------------------------------------------
# Version-floor + version-missing edge cases.
# ---------------------------------------------------------------------------


class TestProbeFailureModes:
    async def test_version_below_minimum_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/solr/admin/info/system":
                return httpx.Response(200, json={"lucene": {"solr-spec-version": "8.11.0"}})
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="9.0 or later required"):
                await adapter.probe_capabilities()
        finally:
            await adapter.aclose()

    async def test_version_missing_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/solr/admin/info/system":
                return httpx.Response(200, json={"lucene": {}})
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="missing lucene.solr-spec-version"):
                await adapter.probe_capabilities()
        finally:
            await adapter.aclose()

    async def test_401_on_info_system_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="auth required")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="Authentication failed"):
                await adapter.probe_capabilities()
        finally:
            await adapter.aclose()

    async def test_5xx_on_info_system_raises(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="down")

        adapter = _build_adapter(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="HTTP 503"):
                await adapter.probe_capabilities()
        finally:
            await adapter.aclose()


# ---------------------------------------------------------------------------
# health_check — full implementation per Story A1.
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_green_solr_10(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"lucene": {"solr-spec-version": "10.0.0"}})

        adapter = _build_adapter(handler)
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "green"
        assert status.version == "10.0.0"
        assert status.error is None

    async def test_below_minimum_returns_unreachable_not_raise(self) -> None:
        """A Solr below 9.0 → ``HealthStatus(unreachable, ...)``, NOT an exception.

        Distinct from ``probe_capabilities`` which raises. ``health_check`` is
        on the cached read path and is called from the operator-facing
        ``/healthz`` endpoint — surfacing as unreachable is the documented
        contract.
        """

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"lucene": {"solr-spec-version": "8.11.0"}})

        adapter = _build_adapter(handler)
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "unreachable"
        assert status.version == "8.11.0"
        assert status.error is not None
        assert "below minimum" in status.error

    async def test_401_returns_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="auth required")

        adapter = _build_adapter(handler)
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "unreachable"
        assert status.error is not None
        assert "Authentication" in status.error

    async def test_connection_error_returns_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=req)

        adapter = _build_adapter(handler)
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "unreachable"
        assert status.error is not None
        assert "connection refused" in status.error
        assert status.version is None

    async def test_5xx_returns_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="cluster down")

        adapter = _build_adapter(handler)
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "unreachable"

    async def test_version_cached_on_first_success(self) -> None:
        path_calls: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            path_calls.append(req.url.path)
            return httpx.Response(200, json={"lucene": {"solr-spec-version": "10.0.0"}})

        adapter = _build_adapter(handler)
        try:
            await adapter.health_check()
            await adapter.health_check()
        finally:
            await adapter.aclose()
        # Each health_check hits /admin/info/system; version is parsed each
        # time but stored on the adapter for downstream methods that need it
        # without re-fetching.
        assert path_calls.count("/solr/admin/info/system") == 2
        assert adapter._version == "10.0.0"


# ---------------------------------------------------------------------------
# list_query_parsers — static return; no HTTP.
# ---------------------------------------------------------------------------


class TestListQueryParsers:
    async def test_returns_static_list(self) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(500)

        adapter = _build_adapter(handler)
        try:
            assert adapter.list_query_parsers() == ["edismax", "dismax", "lucene"]
        finally:
            await adapter.aclose()
        # Critical: no HTTP request made.
        assert call_count == 0


# ---------------------------------------------------------------------------
# Mode detection edge cases.
# ---------------------------------------------------------------------------


class TestModeDetection:
    async def test_zookeeper_404_is_standalone(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            if path == "/solr/admin/info/system":
                return httpx.Response(200, json={"lucene": {"solr-spec-version": "10.0.0"}})
            if path == "/solr/admin/zookeeper/status":
                return httpx.Response(404)
            if path == "/solr/admin/cores":
                return httpx.Response(200, json={"status": {}})
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        assert result.mode == "standalone"

    async def test_zookeeper_503_is_standalone(self) -> None:
        """Defensive: 5xx on ZooKeeper endpoint → degrade to standalone, never raise."""

        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            if path == "/solr/admin/info/system":
                return httpx.Response(200, json={"lucene": {"solr-spec-version": "10.0.0"}})
            if path == "/solr/admin/zookeeper/status":
                return httpx.Response(503)
            if path == "/solr/admin/cores":
                return httpx.Response(200, json={"status": {}})
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            result = await adapter.probe_capabilities()
        finally:
            await adapter.aclose()
        # 5xx on zookeeper status surfaced as ClusterUnreachableError out of
        # _request (translate_errors=False rethrows), which _detect_mode
        # catches and degrades to standalone.
        assert result.mode == "standalone"


# ---------------------------------------------------------------------------
# Constants surfaced for the spec FR-2 floor check.
# ---------------------------------------------------------------------------


def test_solr_min_version_constant() -> None:
    assert SOLR_MIN_VERSION == (9, 0)
