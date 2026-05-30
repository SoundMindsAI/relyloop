# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""SolrAdapter ↔ SearchAdapter Protocol conformance (infra_adapter_solr Story A1).

These tests assert that ``SolrAdapter`` satisfies the runtime-checkable
``SearchAdapter`` Protocol — every Protocol attribute is present and the
async/sync shape matches. The behavioural correctness of each Protocol method
lives in story-specific test files (``test_solr_capability_probe.py`` for the
probe, ``test_solr_render.py`` for render, etc.).

The Protocol is structural — adding ``isinstance(stub, SearchAdapter)`` only
checks attribute presence; ``test_async_methods_are_coroutines`` locks in the
async contract so a future refactor cannot accidentally make an I/O method
synchronous (which would compile fine but silently break the run-time event
loop).
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from backend.app.adapters.protocol import SearchAdapter
from backend.app.adapters.solr import SolrAdapter
from backend.app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _stub_credentials(tmp_path, monkeypatch):
    """Mount a minimal credentials YAML so SolrAdapter's __init__ can resolve creds."""
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


def _build_solr_adapter() -> SolrAdapter:
    """Build a SolrAdapter wired to a no-op transport — only used for shape assertions."""

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    return SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class TestProtocolShape:
    async def test_isinstance_searchadapter(self) -> None:
        """SolrAdapter satisfies the runtime-checkable SearchAdapter Protocol."""
        adapter = _build_solr_adapter()
        try:
            assert isinstance(adapter, SearchAdapter)
            assert adapter.engine_type == "solr"
        finally:
            await adapter.aclose()

    async def test_async_methods_are_coroutines(self) -> None:
        """Lock in the async contract — these methods MUST be coroutines."""
        adapter = _build_solr_adapter()
        try:
            for name in (
                "health_check",
                "list_targets",
                "get_schema",
                "search_batch",
                "explain",
                "get_document",
                "list_documents",
            ):
                method = getattr(adapter, name)
                assert inspect.iscoroutinefunction(method), f"{name} must be async"
        finally:
            await adapter.aclose()

    async def test_sync_methods_are_not_coroutines(self) -> None:
        """Pure methods (render, list_query_parsers) MUST stay sync."""
        adapter = _build_solr_adapter()
        try:
            for name in ("render", "list_query_parsers"):
                method = getattr(adapter, name)
                assert not inspect.iscoroutinefunction(method), f"{name} must be sync"
        finally:
            await adapter.aclose()


class TestStubsRaiseNotImplemented:
    """A2–A8 fill in the stubs; until then they raise NotImplementedError.

    The Protocol shape passes (isinstance is True) because runtime_checkable
    only checks attribute presence — not call behaviour. These tests assert
    the intentional stub state so a later refactor that accidentally drops a
    NotImplementedError doesn't ship undefined behaviour.
    """

    async def test_render_raises(self) -> None:
        from backend.app.adapters.protocol import QueryTemplate

        adapter = _build_solr_adapter()
        try:
            tpl = QueryTemplate(
                name="t",
                engine_type="solr",
                body="{}",
                declared_params={},
            )
            with pytest.raises(NotImplementedError, match="story A2"):
                adapter.render(tpl, {}, "")
        finally:
            await adapter.aclose()

    async def test_list_targets_raises(self) -> None:
        adapter = _build_solr_adapter()
        try:
            with pytest.raises(NotImplementedError, match="story A4"):
                await adapter.list_targets()
        finally:
            await adapter.aclose()

    async def test_search_batch_raises(self) -> None:
        adapter = _build_solr_adapter()
        try:
            with pytest.raises(NotImplementedError, match="story A3"):
                await adapter.search_batch(target="t", queries=[], top_k=10)
        finally:
            await adapter.aclose()


class TestAuthAllowlistEnforcedAtConstruction:
    """The constructor rejects engine×auth mismatches AND non-solr auth_kinds.

    The cross-product allowlist is canonically enforced in the service layer
    (``register_cluster`` consults ``ALLOWED_AUTH_PER_ENGINE``), but the
    adapter constructor is a belt-and-suspenders second gate — any code path
    that builds an adapter directly (e.g., the Optuna trial runner reading a
    persisted row) gets the same validation.
    """

    async def test_solr_basic_constructs(self) -> None:
        adapter = _build_solr_adapter()
        await adapter.aclose()

    def test_es_auth_rejected_for_solr_engine(self, tmp_path, monkeypatch) -> None:
        creds = tmp_path / "creds.yaml"
        creds.write_text("ref:\n  api_key: k\n")
        monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="valid: solr_basic, solr_apikey"):
            SolrAdapter(
                cluster_id="id",
                engine_type="solr",
                base_url="http://s:8983",
                auth_kind="es_apikey",
                credentials_ref="ref",
                engine_config=None,
            )

    def test_non_solr_engine_rejected(self, tmp_path, monkeypatch) -> None:
        creds = tmp_path / "creds.yaml"
        creds.write_text("ref:\n  username: u\n  password: p\n")
        monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="requires engine_type='solr'"):
            SolrAdapter(
                cluster_id="id",
                engine_type="elasticsearch",
                base_url="http://es:9200",
                auth_kind="solr_basic",
                credentials_ref="ref",
                engine_config=None,
            )

    def test_unknown_auth_kind_rejected(self, tmp_path, monkeypatch) -> None:
        creds = tmp_path / "creds.yaml"
        creds.write_text("ref:\n  username: u\n  password: p\n")
        monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="unknown auth_kind"):
            SolrAdapter(
                cluster_id="id",
                engine_type="solr",
                base_url="http://s:8983",
                auth_kind="ghost_basic",
                credentials_ref="ref",
                engine_config=None,
            )
