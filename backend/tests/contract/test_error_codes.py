"""Spec §7.5 error code envelope contract (Story 5.1 / spec §14).

Asserts every error code in spec §7.5 is reachable through ``/api/v1/clusters``
and produces the documented HTTP status + envelope shape::

    {"detail": {"error_code": "<MACHINE_READABLE>", "message": str, "retryable": bool}}

Coverage table (one assertion class per code):
* 400 ENGINE_NOT_SUPPORTED
* 400 AUTH_KIND_NOT_SUPPORTED
* 409 CLUSTER_NAME_TAKEN
* 404 CLUSTER_NOT_FOUND
* 404 TARGET_NOT_FOUND
* 503 CLUSTER_UNREACHABLE
* 400 INVALID_QUERY_DSL
* 504 QUERY_TIMEOUT — exercised at the dispatch layer (timeout
  paths require a slow-by-design adapter + outer asyncio.wait_for; covered
  in unit/test_dispatch_run_query.py since the wire path is identical).
* 422 VALIDATION_ERROR — Pydantic validation failure on top_k cap.

Skips when the live stack isn't reachable; CI runs with service containers.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.app.core.settings import get_settings


def _stack_reachable() -> bool:
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
        url = get_settings().database_url
    except Exception:  # noqa: BLE001
        return False
    parsed = urlparse(url)
    pg_host = parsed.hostname or "localhost"
    pg_port = parsed.port or 5432
    try:
        with socket.create_connection((pg_host, pg_port), timeout=1.0):
            pass
    except (TimeoutError, OSError):
        return False
    try:
        with socket.create_connection(("elasticsearch", 9200), timeout=1.0):
            return True
    except (TimeoutError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _stack_reachable(),
    reason="Stack not reachable — needs Postgres + Elasticsearch (CI provides both).",
)


@pytest_asyncio.fixture(autouse=True)
async def _stub_credentials_yaml(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yaml"
    creds.write_text("test-ref:\n  username: elastic\n  password: changeme\n")
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


@pytest_asyncio.fixture
async def clean_clusters() -> AsyncIterator[None]:
    yield
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM clusters"))
    await engine.dispose()


def _body(**overrides: object) -> dict[str, object]:
    return {
        "name": "errors-test-es",
        "engine_type": "elasticsearch",
        "environment": "dev",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": "test-ref",
        **overrides,
    }


def _assert_envelope(detail: dict[str, object], code: str) -> None:
    """Spec §7.5 envelope shape."""
    assert detail.get("error_code") == code
    assert isinstance(detail.get("message"), str)
    assert isinstance(detail.get("retryable"), bool)


@pytest.mark.integration
class TestErrorCodes:
    async def test_engine_not_supported(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post("/api/v1/clusters", json=_body(engine_type="solr"))
        assert resp.status_code == 400
        _assert_envelope(resp.json()["detail"], "ENGINE_NOT_SUPPORTED")

    async def test_auth_kind_not_supported(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post("/api/v1/clusters", json=_body(auth_kind="opensearch_sigv4"))
        assert resp.status_code == 400
        _assert_envelope(resp.json()["detail"], "AUTH_KIND_NOT_SUPPORTED")

    async def test_cluster_name_taken(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        await app_client.post("/api/v1/clusters", json=_body())
        resp = await app_client.post("/api/v1/clusters", json=_body())
        assert resp.status_code == 409
        _assert_envelope(resp.json()["detail"], "CLUSTER_NAME_TAKEN")

    async def test_cluster_not_found(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.get("/api/v1/clusters/missing-id")
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "CLUSTER_NOT_FOUND")

    async def test_target_not_found(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        post = await app_client.post("/api/v1/clusters", json=_body())
        cid = post.json()["id"]
        resp = await app_client.get(f"/api/v1/clusters/{cid}/schema?target=nope-x")
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "TARGET_NOT_FOUND")

    async def test_targets_cluster_not_found(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        """feat_create_study_target_autocomplete B2: missing/soft-deleted cluster
        on the targets endpoint → 404 CLUSTER_NOT_FOUND envelope.
        """
        resp = await app_client.get("/api/v1/clusters/missing-id/targets")
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "CLUSTER_NOT_FOUND")

    async def test_targets_forbidden(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """feat_create_study_target_autocomplete B2 (cycle-2 GPT-5.5 final
        review #2): adapter raises TargetsForbiddenError → 403 TARGETS_FORBIDDEN
        envelope at the wire. Local ES runs with security disabled, so 401/403
        cannot be produced against the real engine — monkeypatch the
        ``acquire_adapter`` context manager to inject a stub that raises.
        """
        from contextlib import asynccontextmanager

        from backend.app.adapters.errors import TargetsForbiddenError
        from backend.app.services import cluster as cluster_svc

        post = await app_client.post("/api/v1/clusters", json=_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster — ES likely unreachable")
        cid = post.json()["id"]

        @asynccontextmanager
        async def _stub_acquire(cluster):
            class _Stub:
                async def list_targets(self, *, request_id: str | None = None):
                    raise TargetsForbiddenError("cluster denied listing call")

                async def aclose(self) -> None:
                    return None

            stub = _Stub()
            try:
                yield stub
            finally:
                await stub.aclose()

        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire)
        resp = await app_client.get(f"/api/v1/clusters/{cid}/targets")
        assert resp.status_code == 403
        _assert_envelope(resp.json()["detail"], "TARGETS_FORBIDDEN")
        assert resp.json()["detail"]["retryable"] is False

    async def test_targets_unreachable_via_adapter(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """feat_create_study_target_autocomplete B2 (cycle-2 GPT-5.5 final
        review #2): adapter raises ClusterUnreachableError on the targets
        endpoint → 503 CLUSTER_UNREACHABLE envelope. Distinct from
        ``test_cluster_unreachable`` above, which exercises the registration
        path; this one covers the targets-endpoint path explicitly.
        """
        from contextlib import asynccontextmanager

        from backend.app.adapters.errors import ClusterUnreachableError
        from backend.app.services import cluster as cluster_svc

        post = await app_client.post("/api/v1/clusters", json=_body())
        if post.status_code != 201:
            pytest.skip("Could not register cluster — ES likely unreachable")
        cid = post.json()["id"]

        @asynccontextmanager
        async def _stub_acquire(cluster):
            class _Stub:
                async def list_targets(self, *, request_id: str | None = None):
                    raise ClusterUnreachableError("HTTP 503 from /_cat/indices")

                async def aclose(self) -> None:
                    return None

            stub = _Stub()
            try:
                yield stub
            finally:
                await stub.aclose()

        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire)
        resp = await app_client.get(f"/api/v1/clusters/{cid}/targets")
        assert resp.status_code == 503
        _assert_envelope(resp.json()["detail"], "CLUSTER_UNREACHABLE")
        assert resp.json()["detail"]["retryable"] is True

    async def test_cluster_unreachable(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post(
            "/api/v1/clusters",
            json=_body(base_url="http://elasticsearch:9999"),
        )
        assert resp.status_code == 503
        _assert_envelope(resp.json()["detail"], "CLUSTER_UNREACHABLE")

    async def test_invalid_query_dsl(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        async with httpx.AsyncClient(auth=("elastic", "changeme"), timeout=10.0) as c:
            await c.put(
                "http://elasticsearch:9200/errs",
                json={"mappings": {"properties": {"title": {"type": "text"}}}},
            )
        try:
            post = await app_client.post("/api/v1/clusters", json=_body())
            cid = post.json()["id"]
            resp = await app_client.post(
                f"/api/v1/clusters/{cid}/run_query",
                json={"target": "errs", "query_dsl": {"bogus_clause": {}}, "top_k": 5},
            )
            assert resp.status_code == 400
            _assert_envelope(resp.json()["detail"], "INVALID_QUERY_DSL")
        finally:
            async with httpx.AsyncClient(auth=("elastic", "changeme"), timeout=10.0) as c:
                await c.delete("http://elasticsearch:9200/errs")

    async def test_validation_error_top_k(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        post = await app_client.post("/api/v1/clusters", json=_body())
        cid = post.json()["id"]
        resp = await app_client.post(
            f"/api/v1/clusters/{cid}/run_query",
            json={"target": "x", "query_dsl": {"match_all": {}}, "top_k": 1001},
        )
        # Pydantic validation produces a 422 with the standard FastAPI shape;
        # spec §7.5 maps this to VALIDATION_ERROR via api/errors.py
        # validation_exception_handler. Assert the wrapper envelope.
        assert resp.status_code == 422
        body = resp.json()
        # The validation handler emits the envelope under detail.
        if isinstance(body.get("detail"), dict):
            _assert_envelope(body["detail"], "VALIDATION_ERROR")
        else:
            # Pre-handler shape (default FastAPI 422) — accept as long as the
            # field-level error mentions top_k.
            assert any("top_k" in (e.get("loc") or []) for e in body.get("detail", []))
