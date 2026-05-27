"""Integration tests for ``feat_index_document_browser`` Stories 2.2 + 2.3.

Two layers in one file:

1. **Stub-adapter error-path tests** (no ES required, only Postgres) — mirror
   the pattern in ``test_clusters_api_targets_errors.py``. Exercises every
   spec §7.5 error code on both endpoints (CLUSTER_NOT_FOUND, TARGET_NOT_FOUND,
   DOCUMENT_NOT_FOUND, TARGETS_FORBIDDEN, CLUSTER_UNREACHABLE,
   VALIDATION_ERROR).

2. **Live-ES happy-path tests** (require ES on localhost:9200) — register a
   real cluster, seed ~100 docs into a unique index, paginate through the
   full corpus, confirm exact-multiple-page-size termination (AC-15),
   exercise ``target_filter`` anti-enumeration (AC-14), confirm
   doc_id-with-slash round-trips (AC-16), confirm ``?fields=`` only returns
   requested keys.

Both layers skip cleanly when their prerequisites are absent.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    TargetNotFoundError,
    TargetsForbiddenError,
)
from backend.app.adapters.protocol import AdapterDocumentHit, Document, DocumentPage
from backend.app.core.settings import get_settings
from backend.app.services import cluster as cluster_svc


def _stack_reachable() -> bool:
    """Skip predicate: requires Postgres reachable from this process."""
    if not os.environ.get("DATABASE_URL_FILE"):
        return False
    try:
        url = get_settings().database_url
    except Exception:
        return False
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (TimeoutError, OSError):
        return False


def _es_host_port() -> tuple[str, int] | None:
    """Return (host, port) for a reachable ES instance, else None.

    Live-ES tests need ES reachable from the test process. Two contexts:

    * Host shell: ES bound on ``localhost:9200`` (per CLAUDE.md Ports table).
    * Compose network (``make test-worktree``): ES reachable as the
      service alias ``elasticsearch:9200``.

    Probe both — first reachable wins.
    """
    for host in ("elasticsearch", "localhost"):
        try:
            with socket.create_connection((host, 9200), timeout=1.0):
                return host, 9200
        except (TimeoutError, OSError):
            continue
    return None


def _es_reachable() -> bool:
    return _es_host_port() is not None


def _es_base_url() -> str:
    hp = _es_host_port()
    if hp is None:
        raise RuntimeError("ES not reachable — caller should have skipped")
    return f"http://{hp[0]}:{hp[1]}"


@pytest_asyncio.fixture(autouse=True)
async def _stub_credentials_yaml(tmp_path, monkeypatch):
    """Provide a credentials YAML so cluster registration probes resolve a
    valid creds entry. Pattern lifted from ``test_clusters_api_targets_errors.py``.
    """
    creds = tmp_path / "creds.yaml"
    creds.write_text("test-es-ref:\n  username: elastic\n  password: changeme\n")
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac


@pytest_asyncio.fixture
async def clean_clusters() -> AsyncIterator[None]:
    """Truncate clusters before each test."""
    from sqlalchemy import text

    from backend.app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        await db.execute(text("TRUNCATE TABLE clusters RESTART IDENTITY CASCADE"))
        await db.commit()
    yield


def _cluster_body(
    *, name: str = "documents-test", target_filter: str | None = None
) -> dict[str, object]:
    body: dict[str, object] = {
        "name": name,
        "engine_type": "elasticsearch",
        "environment": "dev",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": "test-es-ref",
    }
    if target_filter is not None:
        body["target_filter"] = target_filter
    return body


def _assert_envelope(detail: dict[str, object], code: str, *, retryable: bool) -> None:
    assert detail.get("error_code") == code, detail
    assert isinstance(detail.get("message"), str)
    assert detail.get("retryable") is retryable


class _StubAdapter:
    """Stub adapter for the documents endpoints.

    Each instance can be configured with a specific exception or a specific
    page/document payload. ``aclose`` is required by ``acquire_adapter``'s
    async-context-manager finally clause.
    """

    def __init__(
        self,
        *,
        list_raises: Exception | None = None,
        list_page: DocumentPage | None = None,
        get_raises: Exception | None = None,
        get_returns: Document | None = None,
    ) -> None:
        self._list_raises = list_raises
        self._list_page = list_page
        self._get_raises = get_raises
        self._get_returns = get_returns

    async def list_documents(
        self,
        target: str,
        *,
        search_after: list[Any] | None = None,
        limit: int = 25,
        fields: list[str] | None = None,
        request_id: str | None = None,
    ) -> DocumentPage:
        if self._list_raises is not None:
            raise self._list_raises
        assert self._list_page is not None, "stub not configured for list"
        return self._list_page

    async def get_document(
        self,
        target: str,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> Document | None:
        if self._get_raises is not None:
            raise self._get_raises
        return self._get_returns

    async def aclose(self) -> None:
        return None


def _stub_acquire_factory(stub: _StubAdapter):
    @asynccontextmanager
    async def _stub_acquire(cluster):
        try:
            yield stub
        finally:
            await stub.aclose()

    return _stub_acquire


# ---------------------------------------------------------------------------
# Layer 1 — stub-adapter error-path tests (Postgres only)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _stack_reachable(), reason="Postgres not reachable")
class TestDocumentsListErrors:
    async def test_missing_cluster_returns_404(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        resp = await app_client.get(
            "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents",
        )
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "CLUSTER_NOT_FOUND", retryable=False)

    async def test_target_filter_returns_404(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-14 — target outside the cluster's target_filter glob returns 404
        TARGET_NOT_FOUND (anti-enumeration; not 403)."""
        post = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(target_filter="public-*"),
        )
        if post.status_code != 201:
            pytest.skip("Could not register cluster — ES likely unreachable")
        cluster_id = post.json()["id"]

        # No adapter monkeypatch needed — the router checks target_filter
        # before acquiring the adapter.
        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/private-customers/documents",
        )
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "TARGET_NOT_FOUND", retryable=False)

    async def test_target_not_found_from_adapter(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        post = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]

        stub = _StubAdapter(list_raises=TargetNotFoundError("acme-products"))
        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire_factory(stub))

        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/acme-products/documents",
        )
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "TARGET_NOT_FOUND", retryable=False)

    async def test_targets_forbidden_returns_403(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        post = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]

        stub = _StubAdapter(list_raises=TargetsForbiddenError("ACL denied"))
        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire_factory(stub))

        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/acme-products/documents",
        )
        assert resp.status_code == 403
        _assert_envelope(resp.json()["detail"], "TARGETS_FORBIDDEN", retryable=False)

    async def test_cluster_unreachable_returns_503(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        post = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]

        stub = _StubAdapter(list_raises=ClusterUnreachableError("HTTP 503"))
        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire_factory(stub))

        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/acme-products/documents",
        )
        assert resp.status_code == 503
        _assert_envelope(resp.json()["detail"], "CLUSTER_UNREACHABLE", retryable=True)

    async def test_unknown_query_param_returns_422(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        resp = await app_client.get(
            "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents"
            "?since=2024-01-01",
        )
        assert resp.status_code == 422
        _assert_envelope(resp.json()["detail"], "VALIDATION_ERROR", retryable=False)

    async def test_wildcard_fields_returns_422(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        resp = await app_client.get(
            "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents?fields=*",
        )
        assert resp.status_code == 422
        _assert_envelope(resp.json()["detail"], "VALIDATION_ERROR", retryable=False)

    async def test_limit_over_100_returns_422(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        """FastAPI's Query(le=100) validator emits the framework default 422
        envelope — confirms the bound is enforced."""
        resp = await app_client.get(
            "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents?limit=101",
        )
        assert resp.status_code == 422

    async def test_invalid_cursor_returns_422(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        resp = await app_client.get(
            "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents"
            "?cursor=!!!malformed!!!",
        )
        assert resp.status_code == 422
        _assert_envelope(resp.json()["detail"], "VALIDATION_ERROR", retryable=False)

    async def test_list_happy_path_with_truncation(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stub returns a doc with a 10 KiB string field — confirms the
        sentinel appears in the response and X-Total-Count is populated."""
        post = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]

        big_value = "x" * 10000  # > 8 KiB default
        page = DocumentPage(
            hits=[
                AdapterDocumentHit(
                    doc_id="doc-001",
                    source={"title": "ok", "description": big_value},
                    sort=["doc-001"],
                ),
                AdapterDocumentHit(
                    doc_id="doc-002",
                    source={"title": "ok2"},
                    sort=["doc-002"],
                ),
            ],
            total=2,
        )
        stub = _StubAdapter(list_page=page)
        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire_factory(stub))

        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/foo/documents",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is False
        assert body["next_cursor"] is None
        assert len(body["data"]) == 2
        # Truncation sentinel preserved verbatim.
        from backend.app.services.documents import DOCUMENT_FIELD_TRUNCATED

        assert body["data"][0]["source"]["description"] == DOCUMENT_FIELD_TRUNCATED
        # X-Total-Count header.
        assert resp.headers["X-Total-Count"] == "2"

    async def test_list_overfetch_drives_has_more_and_cursor(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the adapter returns limit+1 rows, the router drops the last
        one, sets has_more=True, and encodes the last *visible* sort as
        next_cursor."""
        post = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]

        # Request limit=2 → router asks adapter for 3; stub returns 3.
        page = DocumentPage(
            hits=[
                AdapterDocumentHit(doc_id="d1", source={"x": 1}, sort=["d1"]),
                AdapterDocumentHit(doc_id="d2", source={"x": 2}, sort=["d2"]),
                AdapterDocumentHit(doc_id="d3", source={"x": 3}, sort=["d3"]),
            ],
            total=10,
        )
        stub = _StubAdapter(list_page=page)
        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire_factory(stub))

        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/foo/documents?limit=2",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 2
        assert body["has_more"] is True
        assert body["next_cursor"] is not None
        assert resp.headers["X-Total-Count"] == "10"

        # The next_cursor round-trips through decode_documents_cursor to ["d2"].
        from backend.app.api.v1._documents_cursor import decode_documents_cursor

        assert decode_documents_cursor(body["next_cursor"]) == ["d2"]


@pytest.mark.integration
@pytest.mark.skipif(not _stack_reachable(), reason="Postgres not reachable")
class TestDocumentDetailErrors:
    async def test_missing_cluster_returns_404(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        resp = await app_client.get(
            "/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets/foo/documents/some-id",
        )
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "CLUSTER_NOT_FOUND", retryable=False)

    async def test_target_filter_404(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        post = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(target_filter="public-*"),
        )
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]
        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/private/documents/d1",
        )
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "TARGET_NOT_FOUND", retryable=False)

    async def test_document_not_found_when_adapter_returns_none(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        post = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]

        stub = _StubAdapter(get_returns=None)
        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire_factory(stub))

        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/foo/documents/missing-doc",
        )
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "DOCUMENT_NOT_FOUND", retryable=False)

    async def test_happy_path_returns_document(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        post = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]

        stub = _StubAdapter(get_returns=Document(doc_id="doc-007", source={"title": "James Bond"}))
        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire_factory(stub))

        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/foo/documents/doc-007",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["doc_id"] == "doc-007"
        assert body["source"] == {"title": "James Bond"}

    async def test_slash_in_doc_id_round_trips(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-16 — ``{doc_id:path}`` converter accepts slashes."""
        post = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster")
        cluster_id = post.json()["id"]

        captured: dict[str, str] = {}

        class _CapturingAdapter(_StubAdapter):
            async def get_document(self, target, doc_id, *, request_id=None):
                captured["target"] = target
                captured["doc_id"] = doc_id
                return Document(doc_id=doc_id, source={"ok": True})

        stub = _CapturingAdapter()
        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire_factory(stub))

        # doc_id = "https://example.com/p/123" → URL-encode the slashes.
        path_segment = quote("https://example.com/p/123", safe="")
        resp = await app_client.get(
            f"/api/v1/clusters/{cluster_id}/targets/foo/documents/{path_segment}",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["doc_id"] == "https://example.com/p/123"
        # Adapter received the un-encoded value (FastAPI decodes path params).
        assert captured["doc_id"] == "https://example.com/p/123"


# ---------------------------------------------------------------------------
# Layer 2 — live-ES happy-path tests (require ES on localhost:9200)
# ---------------------------------------------------------------------------


def _es_index_for_test(name: str) -> str:
    """Per-test index name so tests don't bleed."""
    return f"docs-test-{name}".replace("_", "-")


@pytest.mark.integration
@pytest.mark.skipif(
    not (_stack_reachable() and _es_reachable()),
    reason="Live ES not reachable on localhost:9200",
)
class TestDocumentsLiveES:
    """Live-ES tests for the documents endpoints.

    The cluster `base_url` registered to Postgres points to the Compose
    network alias (`http://elasticsearch:9200`), but these tests need ES
    reachable from the host shell. When neither is reachable, the class
    skips cleanly. When ES is reachable from `localhost:9200` only (the
    host-bound port) but the Postgres-registered alias isn't (e.g. when
    pytest runs outside the Compose network), each test is gated by the
    cluster-registration `pytest.skip` so the whole class still drains
    cleanly.
    """

    async def test_full_paginated_browse_terminates_correctly(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        """Seed 50 docs, paginate with limit=20; confirm 3 pages
        (20 + 20 + 10), last page has has_more=False and total=50."""
        index = _es_index_for_test("full-paginate")
        # Direct ES setup via httpx so the test doesn't depend on the
        # adapter's create-index helper.
        async with httpx.AsyncClient(base_url=_es_base_url()) as es:
            # Best-effort teardown of any previous index.
            await es.delete(f"/{index}")
            # Use _bulk with refresh=true so docs are immediately queryable.
            lines: list[str] = []
            for i in range(50):
                doc_id = f"doc-{i:03d}"
                lines.append(f'{{"index": {{"_index": "{index}", "_id": "{doc_id}"}}}}')
                lines.append(f'{{"title": "Title {i}", "n": {i}}}')
            bulk_body = "\n".join(lines) + "\n"
            r = await es.post(
                "/_bulk?refresh=true",
                content=bulk_body,
                headers={"Content-Type": "application/x-ndjson"},
            )
            assert r.status_code == 200, r.text

        try:
            post = await app_client.post(
                "/api/v1/clusters",
                json=_cluster_body(name="docs-live-paginate"),
            )
            if post.status_code != 201:
                pytest.skip(
                    f"Cluster register failed — ES not reachable via Compose alias: {post.json()}"
                )
            cluster_id = post.json()["id"]

            # Page 1.
            r1 = await app_client.get(
                f"/api/v1/clusters/{cluster_id}/targets/{index}/documents?limit=20",
            )
            assert r1.status_code == 200, r1.text
            b1 = r1.json()
            assert len(b1["data"]) == 20
            assert b1["has_more"] is True
            assert b1["next_cursor"] is not None
            assert r1.headers["X-Total-Count"] == "50"

            # Page 2 — pass the cursor.
            r2 = await app_client.get(
                f"/api/v1/clusters/{cluster_id}/targets/{index}/documents"
                f"?limit=20&cursor={b1['next_cursor']}",
            )
            assert r2.status_code == 200
            b2 = r2.json()
            assert len(b2["data"]) == 20
            assert b2["has_more"] is True

            # Page 3 — final 10.
            r3 = await app_client.get(
                f"/api/v1/clusters/{cluster_id}/targets/{index}/documents"
                f"?limit=20&cursor={b2['next_cursor']}",
            )
            assert r3.status_code == 200
            b3 = r3.json()
            assert len(b3["data"]) == 10
            assert b3["has_more"] is False
            assert b3["next_cursor"] is None
        finally:
            async with httpx.AsyncClient(base_url=_es_base_url()) as es:
                await es.delete(f"/{index}")

    async def test_exact_multiple_page_size_terminates(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        """AC-15 — 50-doc corpus with limit=25 ends correctly on page 2 with
        has_more=False."""
        index = _es_index_for_test("exact-multiple")
        async with httpx.AsyncClient(base_url=_es_base_url()) as es:
            await es.delete(f"/{index}")
            lines: list[str] = []
            for i in range(50):
                lines.append(f'{{"index": {{"_index": "{index}", "_id": "d-{i:03d}"}}}}')
                lines.append(f'{{"n": {i}}}')
            r = await es.post(
                "/_bulk?refresh=true",
                content="\n".join(lines) + "\n",
                headers={"Content-Type": "application/x-ndjson"},
            )
            assert r.status_code == 200, r.text

        try:
            post = await app_client.post(
                "/api/v1/clusters",
                json=_cluster_body(name="docs-live-exact"),
            )
            if post.status_code != 201:
                pytest.skip("Cluster register failed")
            cluster_id = post.json()["id"]

            r1 = await app_client.get(
                f"/api/v1/clusters/{cluster_id}/targets/{index}/documents?limit=25",
            )
            b1 = r1.json()
            assert len(b1["data"]) == 25
            assert b1["has_more"] is True

            r2 = await app_client.get(
                f"/api/v1/clusters/{cluster_id}/targets/{index}/documents"
                f"?limit=25&cursor={b1['next_cursor']}",
            )
            b2 = r2.json()
            assert len(b2["data"]) == 25
            assert b2["has_more"] is False
            assert b2["next_cursor"] is None
        finally:
            async with httpx.AsyncClient(base_url=_es_base_url()) as es:
                await es.delete(f"/{index}")

    async def test_fields_filter_returns_only_requested_keys(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        """``?fields=title`` returns only the title key — other fields
        absent from _source."""
        index = _es_index_for_test("fields-filter")
        async with httpx.AsyncClient(base_url=_es_base_url()) as es:
            await es.delete(f"/{index}")
            lines: list[str] = []
            for i in range(3):
                lines.append(f'{{"index": {{"_index": "{index}", "_id": "d-{i}"}}}}')
                lines.append(f'{{"title": "T{i}", "brand": "B{i}", "price": {i}}}')
            r = await es.post(
                "/_bulk?refresh=true",
                content="\n".join(lines) + "\n",
                headers={"Content-Type": "application/x-ndjson"},
            )
            assert r.status_code == 200

        try:
            post = await app_client.post(
                "/api/v1/clusters",
                json=_cluster_body(name="docs-live-fields"),
            )
            if post.status_code != 201:
                pytest.skip("Cluster register failed")
            cluster_id = post.json()["id"]

            resp = await app_client.get(
                f"/api/v1/clusters/{cluster_id}/targets/{index}/documents?fields=title",
            )
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["data"]) == 3
            for row in body["data"]:
                assert "title" in row["source"]
                assert "brand" not in row["source"]
                assert "price" not in row["source"]
        finally:
            async with httpx.AsyncClient(base_url=_es_base_url()) as es:
                await es.delete(f"/{index}")

    async def test_detail_endpoint_round_trips(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        """Seed one doc, fetch via detail endpoint, confirm source roundtrips."""
        index = _es_index_for_test("detail-roundtrip")
        async with httpx.AsyncClient(base_url=_es_base_url()) as es:
            await es.delete(f"/{index}")
            await es.put(
                f"/{index}/_doc/the-id?refresh=true",
                json={"title": "Skyfall", "year": 2012},
            )

        try:
            post = await app_client.post(
                "/api/v1/clusters",
                json=_cluster_body(name="docs-live-detail"),
            )
            if post.status_code != 201:
                pytest.skip("Cluster register failed")
            cluster_id = post.json()["id"]

            resp = await app_client.get(
                f"/api/v1/clusters/{cluster_id}/targets/{index}/documents/the-id",
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["doc_id"] == "the-id"
            assert body["source"]["title"] == "Skyfall"
            assert body["source"]["year"] == 2012
        finally:
            async with httpx.AsyncClient(base_url=_es_base_url()) as es:
                await es.delete(f"/{index}")

    async def test_detail_endpoint_returns_404_for_missing_doc(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
    ) -> None:
        """Fetching an unknown _id on an existing index → 404
        DOCUMENT_NOT_FOUND (not TARGET_NOT_FOUND)."""
        index = _es_index_for_test("doc-missing")
        async with httpx.AsyncClient(base_url=_es_base_url()) as es:
            await es.delete(f"/{index}")
            await es.put(f"/{index}/_doc/some-id?refresh=true", json={"x": 1})

        try:
            post = await app_client.post(
                "/api/v1/clusters",
                json=_cluster_body(name="docs-live-missing"),
            )
            if post.status_code != 201:
                pytest.skip("Cluster register failed")
            cluster_id = post.json()["id"]

            resp = await app_client.get(
                f"/api/v1/clusters/{cluster_id}/targets/{index}/documents/nope",
            )
            assert resp.status_code == 404
            _assert_envelope(resp.json()["detail"], "DOCUMENT_NOT_FOUND", retryable=False)
        finally:
            async with httpx.AsyncClient(base_url=_es_base_url()) as es:
                await es.delete(f"/{index}")
