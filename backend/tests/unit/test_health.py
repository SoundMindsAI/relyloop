"""Health endpoint handler tests (infra_foundation Story 3.2).

Tests the /healthz handler with mocked probes — verifies the status mapping,
parallel-probe orchestration, and timeout behavior. Targets 100% coverage of
``backend/app/api/health.py`` per spec §14.

Tests do NOT need a real DB / Redis / ES / OpenSearch — all probes are
overridden via FastAPI's ``app.dependency_overrides`` mechanism.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from backend.app.api import health, probes
from backend.app.api.errors import install_exception_handlers
from backend.app.api.middleware import RequestIDMiddleware
from backend.app.core.settings import Settings, get_settings


def _make_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Build a Settings instance with stubbed required-secret files.

    Uses ``monkeypatch.setenv`` so the env vars are restored after the test —
    direct ``os.environ`` mutation would persist across tests and pollute
    the Alembic subprocess in ``test_migrations.py`` (CalledProcessError:
    password authentication failed for user "x").
    """
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    return Settings()


@pytest.fixture
def app(tmp_path, monkeypatch) -> FastAPI:
    """Build a test FastAPI app with the /healthz router + middleware + handlers."""
    test_app = FastAPI()
    install_exception_handlers(test_app)
    test_app.add_middleware(RequestIDMiddleware)
    test_app.include_router(health.router)

    settings = _make_settings(tmp_path, monkeypatch)
    test_app.dependency_overrides[get_settings] = lambda: settings
    return test_app


def _mock_redis(*, ping_returns: object = True) -> Redis:
    """Return a mocked Redis client with controllable .ping() and .get() behavior."""
    client = MagicMock(spec=Redis)
    client.ping = AsyncMock(return_value=ping_returns)
    client.get = AsyncMock(return_value=None)  # cache miss by default
    return client


def _mock_httpx_client(*, status_code: int = 200) -> httpx.AsyncClient:
    """Mocked httpx.AsyncClient whose .get() returns a Response with the given code."""
    client = MagicMock(spec=httpx.AsyncClient)

    async def _get(url: str) -> httpx.Response:
        return httpx.Response(status_code=status_code, request=httpx.Request("GET", url))

    client.get = _get
    return client


def _override_probes(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    *,
    db_status: Literal["ok", "down"] = "ok",
    redis_status: Literal["ok", "down"] = "ok",
    es_status: Literal["reachable", "unreachable"] = "reachable",
    os_status: Literal["reachable", "unreachable"] = "reachable",
    openai_state: Literal["configured", "missing_key", "incapable"] = "missing_key",
) -> None:
    """Patch the probe functions to return the requested fixed states."""

    async def _probe_db(_engine):
        return db_status

    async def _probe_redis(_client):
        return redis_status

    async def _probe_es(_client, _url):
        return es_status

    async def _probe_os(_client, _url):
        return os_status

    def _probe_openai(_key, _cap):
        return openai_state

    async def _probe_clusters(_db, _redis):
        return probes.ClusterAggregateHealth(registered=0, healthy=0, unreachable=0)

    monkeypatch.setattr(probes, "probe_db", _probe_db)
    monkeypatch.setattr(probes, "probe_redis", _probe_redis)
    monkeypatch.setattr(probes, "probe_elasticsearch", _probe_es)
    monkeypatch.setattr(probes, "probe_opensearch", _probe_os)
    monkeypatch.setattr(probes, "probe_openai_state", _probe_openai)
    monkeypatch.setattr(probes, "probe_registered_clusters", _probe_clusters)

    # Override the FastAPI deps so the handler uses our mocks (not real Redis / httpx).
    app.dependency_overrides[health.get_redis_client] = lambda: _mock_redis()
    app.dependency_overrides[health.get_es_client] = lambda: _mock_httpx_client()
    # /healthz now takes a db: AsyncSession dep (Story 3.5). Stub the dep so
    # tests don't need a live DB; the handler hands `db` straight to the
    # `probe_registered_clusters` override above (which doesn't read it).
    from backend.app.db.session import get_db as _real_get_db

    async def _stub_db():
        yield None

    app.dependency_overrides[_real_get_db] = _stub_db


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


class TestStatusMapping:
    async def test_all_subsystems_healthy_returns_200_ok(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch)
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["subsystems"]["db"] == "ok"
        assert body["subsystems"]["redis"] == "ok"
        assert body["subsystems"]["elasticsearch"] == "reachable"
        assert body["subsystems"]["opensearch"] == "reachable"

    async def test_db_down_returns_503_degraded(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch, db_status="down")
        resp = await client.get("/healthz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["subsystems"]["db"] == "down"
        # Other subsystems still reflect their actual state per spec AC-3
        assert body["subsystems"]["redis"] == "ok"

    async def test_redis_down_returns_503(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch, redis_status="down")
        resp = await client.get("/healthz")
        assert resp.status_code == 503
        assert resp.json()["subsystems"]["redis"] == "down"

    async def test_elasticsearch_unreachable_returns_503(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch, es_status="unreachable")
        resp = await client.get("/healthz")
        assert resp.status_code == 503
        assert resp.json()["subsystems"]["elasticsearch"] == "unreachable"

    async def test_opensearch_unreachable_returns_503(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch, os_status="unreachable")
        resp = await client.get("/healthz")
        assert resp.status_code == 503
        assert resp.json()["subsystems"]["opensearch"] == "unreachable"


# ---------------------------------------------------------------------------
# OpenAI degraded states do NOT trigger 503 (spec FR-2 / AC-4)
# ---------------------------------------------------------------------------


class TestOpenAIDoesNotBlock:
    async def test_missing_key_still_returns_200(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch, openai_state="missing_key")
        resp = await client.get("/healthz")
        # AC-4: empty/missing OpenAI key → 200, status: ok, openai: missing_key
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["subsystems"]["openai"] == "missing_key"

    async def test_incapable_still_returns_200(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # FR-2: 'incapable' is non-blocking too
        _override_probes(app, monkeypatch, openai_state="incapable")
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["subsystems"]["openai"] == "incapable"


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


class TestResponseShape:
    async def test_response_includes_all_required_fields(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch)
        resp = await client.get("/healthz")
        body = resp.json()
        assert set(body.keys()) >= {
            "status",
            "subsystems",
            "openai_endpoint",
            "openai_capabilities",
            "version",
            "uptime_seconds",
        }
        assert set(body["subsystems"].keys()) == {
            "db",
            "redis",
            "openai",
            "elasticsearch",
            "opensearch",
            "elasticsearch_clusters",
        }
        # Aggregate field is informational; registered=0 when no clusters seeded.
        assert set(body["subsystems"]["elasticsearch_clusters"].keys()) == {
            "registered",
            "healthy",
            "unreachable",
        }
        assert set(body["openai_capabilities"].keys()) == {
            "chat",
            "function_calling",
            "structured_output",
        }

    async def test_default_capabilities_are_untested_when_no_cache(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch)
        body = (await client.get("/healthz")).json()
        assert body["openai_capabilities"]["chat"] == "untested"
        assert body["openai_capabilities"]["function_calling"] == "untested"
        assert body["openai_capabilities"]["structured_output"] == "untested"

    async def test_uptime_seconds_is_non_negative(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch)
        body = (await client.get("/healthz")).json()
        assert isinstance(body["uptime_seconds"], int)
        assert body["uptime_seconds"] >= 0


# ---------------------------------------------------------------------------
# Slow-probe handling — TimeoutError is treated as the safe-down fallback
# ---------------------------------------------------------------------------


class TestSlowProbeHandling:
    async def test_slow_db_probe_reported_as_down(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _slow_db(_engine):
            await asyncio.sleep(1.0)  # 1s > 200ms timeout
            return "ok"

        # Override only the db probe; others succeed quickly.
        async def _ok(*_):
            return "ok"

        async def _reachable(*_):
            return "reachable"

        def _missing_key(*_):
            return "missing_key"

        monkeypatch.setattr(probes, "probe_db", _slow_db)
        monkeypatch.setattr(probes, "probe_redis", _ok)
        monkeypatch.setattr(probes, "probe_elasticsearch", _reachable)
        monkeypatch.setattr(probes, "probe_opensearch", _reachable)
        monkeypatch.setattr(probes, "probe_openai_state", _missing_key)
        app.dependency_overrides[health.get_redis_client] = lambda: _mock_redis()
        app.dependency_overrides[health.get_es_client] = lambda: _mock_httpx_client()

        resp = await client.get("/healthz")
        # The slow db probe should TimeoutError → 'down' fallback → 503.
        assert resp.status_code == 503
        assert resp.json()["subsystems"]["db"] == "down"
