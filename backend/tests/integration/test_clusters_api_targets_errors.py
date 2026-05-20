"""feat_create_study_target_autocomplete Story B2: error-path integration tests
for ``GET /api/v1/clusters/{cluster_id}/targets``.

The local ES stack runs with security disabled per
``docs/01_architecture/deployment.md``, so 401/403 cannot be produced against
the real engine. Instead, we monkeypatch ``cluster_svc.acquire_adapter`` to
yield a stub adapter that raises the specific exception each case needs. The
real DB + real FastAPI app still run; only the adapter call is mocked.

Pairs with ``test_clusters_api.py::TestTargetsEndpoint`` (happy path against
real engines) for full FR-1 / AC-1 → AC-4 coverage.

Covers:
* AC-2 — missing cluster → 404 CLUSTER_NOT_FOUND
* AC-3 — adapter raises TargetsForbiddenError → 403 TARGETS_FORBIDDEN
* AC-4 — adapter raises ClusterUnreachableError → 503 CLUSTER_UNREACHABLE
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.app.adapters.errors import ClusterUnreachableError, TargetsForbiddenError
from backend.app.core.settings import get_settings
from backend.app.services import cluster as cluster_svc


def _stack_reachable() -> bool:
    """Skip predicate: requires Postgres reachable from this process.

    Unlike the sibling ``test_clusters_api.py`` we do NOT require Elasticsearch
    here — these tests bypass the adapter via monkeypatch. Only the DB and
    FastAPI app need to be live.
    """
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
            return True
    except (TimeoutError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _stack_reachable(),
    reason="Stack not fully reachable — needs Postgres from this process.",
)


@pytest_asyncio.fixture(autouse=True)
async def _stub_credentials_yaml(tmp_path, monkeypatch):
    """Provide a credentials YAML so registration probes pass (the adapter
    is still constructed normally during registration; the mock only kicks
    in for the targets-endpoint test path below)."""
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
    """Truncate clusters before each test so the fixture stack starts blank."""
    from sqlalchemy import text

    from backend.app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        await db.execute(text("TRUNCATE TABLE clusters RESTART IDENTITY CASCADE"))
        await db.commit()
    yield


def _cluster_body() -> dict[str, object]:
    return {
        "name": "targets-errors-test",
        "engine_type": "elasticsearch",
        "environment": "dev",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": "test-es-ref",
    }


def _assert_envelope(detail: dict[str, object], code: str, *, retryable: bool) -> None:
    """Spec §7.5 envelope shape."""
    assert detail.get("error_code") == code, detail
    assert isinstance(detail.get("message"), str)
    assert detail.get("retryable") is retryable


class _StubAdapter:
    """Minimal adapter stub that raises the exception the test cares about.

    Only ``list_targets`` is exercised here, but ``aclose`` is required by
    the ``acquire_adapter`` async-context-manager finally clause.
    """

    def __init__(self, raise_with: Exception) -> None:
        self._raise = raise_with

    async def list_targets(
        self,
        *,
        request_id: str | None = None,
        target_filter: str | None = None,
    ) -> list[Any]:
        del target_filter  # accepted to match Protocol; unused in error-injection stub
        raise self._raise

    async def aclose(self) -> None:
        return None


@pytest.mark.integration
class TestTargetsEndpointErrors:
    async def test_missing_cluster_returns_404(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        """AC-2: GET /clusters/<missing>/targets → 404 CLUSTER_NOT_FOUND."""
        resp = await app_client.get("/api/v1/clusters/00000000-0000-0000-0000-000000000000/targets")
        assert resp.status_code == 404
        _assert_envelope(resp.json()["detail"], "CLUSTER_NOT_FOUND", retryable=False)

    async def test_targets_forbidden_returns_403(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-3: adapter raises TargetsForbiddenError → 403 TARGETS_FORBIDDEN
        (retryable=false)."""
        # Register a real cluster first so the route fetches a non-None row;
        # then swap the adapter for our stub.
        post_resp = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post_resp.status_code != 201:
            pytest.skip("Could not register cluster — ES likely unreachable from this env")
        cluster_id = post_resp.json()["id"]

        @asynccontextmanager
        async def _stub_acquire(cluster):
            stub = _StubAdapter(TargetsForbiddenError("ACL denied"))
            try:
                yield stub
            finally:
                await stub.aclose()

        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire)

        resp = await app_client.get(f"/api/v1/clusters/{cluster_id}/targets")
        assert resp.status_code == 403
        _assert_envelope(resp.json()["detail"], "TARGETS_FORBIDDEN", retryable=False)

    async def test_cluster_unreachable_returns_503(
        self,
        app_client: httpx.AsyncClient,
        clean_clusters: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-4: adapter raises ClusterUnreachableError → 503 CLUSTER_UNREACHABLE
        (retryable=true)."""
        post_resp = await app_client.post("/api/v1/clusters", json=_cluster_body())
        if post_resp.status_code != 201:
            pytest.skip("Could not register cluster — ES likely unreachable from this env")
        cluster_id = post_resp.json()["id"]

        @asynccontextmanager
        async def _stub_acquire(cluster):
            stub = _StubAdapter(ClusterUnreachableError("HTTP 503"))
            try:
                yield stub
            finally:
                await stub.aclose()

        monkeypatch.setattr(cluster_svc, "acquire_adapter", _stub_acquire)

        resp = await app_client.get(f"/api/v1/clusters/{cluster_id}/targets")
        assert resp.status_code == 503
        _assert_envelope(resp.json()["detail"], "CLUSTER_UNREACHABLE", retryable=True)
