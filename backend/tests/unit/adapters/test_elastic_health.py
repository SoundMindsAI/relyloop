# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``ElasticAdapter.health_check`` unit tests via httpx.MockTransport (Story 2.2).

These run in the unit layer because ``MockTransport`` makes them hermetic and
deterministic without ES/OpenSearch containers. Live HTTP coverage of the
same surface lives in the integration layer (Epic 2 gate verification).

Cases:
* Green ES 9.4 → ``HealthStatus(status='green', version='9.4.0')``.
* Yellow OpenSearch 2.18 → ``HealthStatus(status='yellow')``.
* ES 8.10 (below minimum) → ``HealthStatus(status='unreachable')`` with a
  version-too-low message; **no exception escapes** (cycle 1 F3 fix).
* Connection error → ``HealthStatus(status='unreachable', error=...)``.
* 401 → ``HealthStatus(status='unreachable', error='Authentication ...')``.
* Version cached after first successful health_check (second call doesn't
  re-fetch ``GET /``).
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
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


def _build_adapter(
    handler, *, engine: str = "elasticsearch", auth: str = "es_basic"
) -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="id",
        engine_type=engine,  # type: ignore[arg-type]
        base_url="http://es:9200",
        auth_kind=auth,
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class TestGreenAndYellow:
    async def test_green_es_94(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/_cluster/health":
                return httpx.Response(200, json={"status": "green"})
            if req.url.path == "/":
                return httpx.Response(200, json={"version": {"number": "9.4.0"}})
            return httpx.Response(404)

        adapter = _build_adapter(handler)
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "green"
        assert status.version == "9.4.0"
        assert status.error is None

    async def test_yellow_opensearch_218(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/_cluster/health":
                return httpx.Response(200, json={"status": "yellow"})
            return httpx.Response(
                200, json={"version": {"number": "2.18.0", "distribution": "opensearch"}}
            )

        adapter = _build_adapter(handler, engine="opensearch", auth="opensearch_basic")
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "yellow"
        assert status.version == "2.18.0"


class TestVersionFloor:
    async def test_es_810_below_minimum(self) -> None:
        """ES 8.10 → unreachable + version-too-low message; NO exception escapes."""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/_cluster/health":
                return httpx.Response(200, json={"status": "green"})
            return httpx.Response(200, json={"version": {"number": "8.10.4"}})

        adapter = _build_adapter(handler)
        try:
            # The assertion is on the returned status, NOT a pytest.raises:
            # if an exception escapes, the test fails for a different reason
            # (which would surface F3 regression).
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "unreachable"
        assert status.version == "8.10.4"
        assert status.error is not None
        assert "below minimum" in status.error

    async def test_opensearch_below_minimum(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/_cluster/health":
                return httpx.Response(200, json={"status": "green"})
            return httpx.Response(200, json={"version": {"number": "1.3.0"}})

        adapter = _build_adapter(handler, engine="opensearch", auth="opensearch_basic")
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "unreachable"
        assert status.error is not None
        assert "below minimum" in status.error


class TestUnreachable:
    async def test_connection_error(self) -> None:
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

    async def test_401_unreachable(self) -> None:
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

    async def test_5xx_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="cluster down")

        adapter = _build_adapter(handler)
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "unreachable"


class TestVersionCaching:
    async def test_version_fetched_only_once(self) -> None:
        path_calls: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            path_calls.append(req.url.path)
            if req.url.path == "/_cluster/health":
                return httpx.Response(200, json={"status": "green"})
            return httpx.Response(200, json={"version": {"number": "9.4.0"}})

        adapter = _build_adapter(handler)
        try:
            await adapter.health_check()
            await adapter.health_check()
        finally:
            await adapter.aclose()
        # First call: GET /_cluster/health, GET / (2 paths).
        # Second call: only GET /_cluster/health (version cached on adapter).
        assert path_calls.count("/") == 1
        assert path_calls.count("/_cluster/health") == 2
