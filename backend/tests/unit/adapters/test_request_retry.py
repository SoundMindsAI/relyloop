# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter._request`` retry + error-translation unit tests (Story 2.1, F4).

Verifies the spec §13 reliability contract:

* First-attempt connection error → second attempt succeeds → response returned
  (one retry).
* Two consecutive connection errors → ``ClusterUnreachableError`` when
  ``translate_errors=True``; raw ``httpx.ConnectError`` re-raised when False.
* 5xx response with translation on → ``ClusterUnreachableError``.
* 401 response with translation on → ``ClusterUnreachableError``.
* 200 response → returned cleanly with exactly one HTTP call (no spurious retry).
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.adapters.errors import ClusterUnreachableError
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


def _build_adapter(transport: httpx.MockTransport) -> ElasticAdapter:
    """Construct an adapter wired to a MockTransport-backed httpx client."""
    return ElasticAdapter(
        cluster_id="id",
        engine_type="elasticsearch",
        base_url="http://es:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=transport),
    )


class TestRetrySuccessAfterOneFailure:
    async def test_succeeds_after_one_connection_error(self) -> None:
        """First attempt raises ConnectError; second succeeds; response returned."""
        attempts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(len(attempts) + 1)
            if attempts[-1] == 1:
                raise httpx.ConnectError("first attempt fails", request=request)
            return httpx.Response(200, json={"ok": True})

        adapter = _build_adapter(httpx.MockTransport(handler))
        try:
            resp = await adapter._request("GET", "/_cluster/health")
        finally:
            await adapter.aclose()
        assert resp.status_code == 200
        assert attempts == [1, 2]


class TestRetryExhausted:
    async def test_two_failures_raises_translated(self) -> None:
        """Two ConnectErrors → ClusterUnreachableError when translate_errors=True."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("nope", request=request)

        adapter = _build_adapter(httpx.MockTransport(handler))
        try:
            with pytest.raises(ClusterUnreachableError, match="nope"):
                await adapter._request("GET", "/_cluster/health")
        finally:
            await adapter.aclose()

    async def test_two_failures_propagate_raw_when_not_translating(self) -> None:
        """Two ConnectErrors → raw httpx exception when translate_errors=False."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("raw", request=request)

        adapter = _build_adapter(httpx.MockTransport(handler))
        try:
            with pytest.raises(httpx.ConnectError, match="raw"):
                await adapter._request("GET", "/_cluster/health", translate_errors=False)
        finally:
            await adapter.aclose()


class TestStatusCodeTranslation:
    async def test_5xx_raises_unreachable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="service unavailable")

        adapter = _build_adapter(httpx.MockTransport(handler))
        try:
            with pytest.raises(ClusterUnreachableError, match="503"):
                await adapter._request("GET", "/_cluster/health")
        finally:
            await adapter.aclose()

    async def test_401_raises_unreachable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="auth required")

        adapter = _build_adapter(httpx.MockTransport(handler))
        try:
            with pytest.raises(ClusterUnreachableError, match="Authentication"):
                await adapter._request("GET", "/_cluster/health")
        finally:
            await adapter.aclose()

    async def test_5xx_returned_when_not_translating(self) -> None:
        """``translate_errors=False`` returns the response so callers can inspect."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="oh no")

        adapter = _build_adapter(httpx.MockTransport(handler))
        try:
            resp = await adapter._request("GET", "/_cluster/health", translate_errors=False)
            assert resp.status_code == 503
        finally:
            await adapter.aclose()


class TestNoSpuriousRetryOnSuccess:
    async def test_200_makes_exactly_one_call(self) -> None:
        attempts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            return httpx.Response(200, json={"ok": True})

        adapter = _build_adapter(httpx.MockTransport(handler))
        try:
            resp = await adapter._request("GET", "/_cluster/health")
        finally:
            await adapter.aclose()
        assert resp.status_code == 200
        assert len(attempts) == 1


class TestRequestIdHeader:
    async def test_x_opaque_id_propagates(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["x_opaque"] = request.headers.get("X-Opaque-Id", "")
            return httpx.Response(200, json={})

        adapter = _build_adapter(httpx.MockTransport(handler))
        try:
            await adapter._request("GET", "/_cluster/health", request_id="req-42")
        finally:
            await adapter.aclose()
        assert captured["x_opaque"] == "req-42"
