# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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
# Engine-selection-aware /healthz (bug_healthz_degraded_blocks_ui_engine_subset)
#
# An engine the operator excluded via RELYLOOP_ENGINES (→ COMPOSE_PROFILES →
# settings.selected_engines) reports "not_selected" — a NON-blocking state —
# instead of "unreachable". Without this, a Solr-only stack's /healthz is 503
# (api unhealthy → ui/worker never start).
# ---------------------------------------------------------------------------


class TestEngineSelectionAware:
    def _app_with_selection(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, compose_profiles: str
    ) -> FastAPI:
        # COMPOSE_PROFILES must be set BEFORE Settings() is constructed, so we
        # build the app inline rather than reuse the module `app` fixture.
        monkeypatch.setenv("COMPOSE_PROFILES", compose_profiles)
        test_app = FastAPI()
        install_exception_handlers(test_app)
        test_app.add_middleware(RequestIDMiddleware)
        test_app.include_router(health.router)
        settings = _make_settings(tmp_path, monkeypatch)
        test_app.dependency_overrides[get_settings] = lambda: settings
        return test_app

    async def _get_healthz(self, app: FastAPI) -> httpx.Response:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.get("/healthz")

    async def test_excluded_engines_report_not_selected_and_return_200(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Solr-only selection: ES + OS excluded → not_selected, status 200.

        This is the core regression: on `main` (pre-fix) es/os would be
        'unreachable' → degraded → 503. With the fix they're 'not_selected'
        (non-blocking) → 200.
        """
        app = self._app_with_selection(tmp_path, monkeypatch, "solr")
        # Even though the (skipped) probes are wired to "unreachable", the
        # excluded engines must report not_selected, not unreachable.
        _override_probes(app, monkeypatch, es_status="unreachable", os_status="unreachable")
        resp = await self._get_healthz(app)
        assert resp.status_code == 200, resp.text
        subs = resp.json()["subsystems"]
        assert subs["elasticsearch"] == "not_selected"
        assert subs["opensearch"] == "not_selected"

    async def test_excluded_engine_probe_is_actually_skipped(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stronger guard: the excluded engine's probe is never CALLED.

        Make probe_elasticsearch / probe_opensearch raise. If /healthz still
        returns 200 + not_selected, the probe was skipped (not merely
        reinterpreted) — proving the no-wasted-200ms-timeout property too.
        """
        app = self._app_with_selection(tmp_path, monkeypatch, "solr")
        _override_probes(app, monkeypatch)

        async def _boom(*_a: object, **_k: object) -> str:
            raise AssertionError("excluded-engine probe must not be called")

        monkeypatch.setattr(probes, "probe_elasticsearch", _boom)
        monkeypatch.setattr(probes, "probe_opensearch", _boom)
        resp = await self._get_healthz(app)
        assert resp.status_code == 200, resp.text
        subs = resp.json()["subsystems"]
        assert subs["elasticsearch"] == "not_selected"
        assert subs["opensearch"] == "not_selected"

    async def test_selected_but_down_engine_still_blocks_while_excluded_is_not_selected(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Selection awareness must NOT mask a genuinely-down SELECTED engine.

        Selection 'es,solr': ES is selected + unreachable → still 503. OS is
        excluded → not_selected (non-blocking) in the same response.
        """
        app = self._app_with_selection(tmp_path, monkeypatch, "es,solr")
        _override_probes(app, monkeypatch, es_status="unreachable")
        resp = await self._get_healthz(app)
        assert resp.status_code == 503, resp.text
        subs = resp.json()["subsystems"]
        assert subs["elasticsearch"] == "unreachable"  # selected + down → blocking
        assert subs["opensearch"] == "not_selected"  # excluded → non-blocking


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
            "solr",
            "elasticsearch_clusters",
        }
        # Aggregate field is informational; registered=0 when no clusters seeded.
        assert set(body["subsystems"]["elasticsearch_clusters"].keys()) == {
            "registered",
            "healthy",
            "unreachable",
        }
        # Five keys per bug_openai_capability_check_incapable_on_valid_key spec
        # §8.2 — models_endpoint added in front so step-1 outcome is visible;
        # models_endpoint_status_code is required-but-nullable.
        assert set(body["openai_capabilities"].keys()) == {
            "models_endpoint",
            "models_endpoint_status_code",
            "chat",
            "function_calling",
            "structured_output",
        }
        # Cache miss default — key present even when status_code is null.
        assert body["openai_capabilities"]["models_endpoint_status_code"] is None

    async def test_default_capabilities_are_untested_when_no_cache(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_probes(app, monkeypatch)
        body = (await client.get("/healthz")).json()
        # All five sub-capabilities default to "untested" on cache miss.
        # models_endpoint joined the family per bug_openai_capability_check
        # spec §19 D-1; status_code defaults to null (D-3/D-8).
        assert body["openai_capabilities"]["models_endpoint"] == "untested"
        assert body["openai_capabilities"]["models_endpoint_status_code"] is None
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


# ---------------------------------------------------------------------------
# models_endpoint surfacing in /healthz openai_capabilities response
# (bug_openai_capability_check_incapable_on_valid_key, Story 1.3 / AC-1/2/5/6/10)
#
# These tests do NOT monkeypatch probe_openai_state — they exercise the REAL
# probes.probe_openai_state mapping against a seeded CapabilityResult cache.
# That's the point: AC-1 verifies the chain (cache row with models_endpoint
# == "fail") → real mapping → subsystems.openai == "incapable" still works
# post-fix.
# ---------------------------------------------------------------------------


import hashlib  # noqa: E402  (intentional late import — local to the new tests)

from backend.app.llm.capability_models import CapabilityResult  # noqa: E402


def _override_probes_real_openai_state(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cached_capability: CapabilityResult | None,
    api_key_present: bool,
) -> None:
    """Same as ``_override_probes`` but keeps the REAL ``probe_openai_state`` mapping.

    Seeds a cached ``CapabilityResult`` (or no cache) into the Redis mock so
    the handler's ``_read_capability_cache`` call returns the seeded value
    via the same cache-key sha256(base_url) lookup the production code does.
    """

    async def _ok(*_):
        return "ok"

    async def _reachable(*_):
        return "reachable"

    async def _probe_clusters(_db, _redis):
        return probes.ClusterAggregateHealth(registered=0, healthy=0, unreachable=0)

    monkeypatch.setattr(probes, "probe_db", _ok)
    monkeypatch.setattr(probes, "probe_redis", _ok)
    monkeypatch.setattr(probes, "probe_elasticsearch", _reachable)
    monkeypatch.setattr(probes, "probe_opensearch", _reachable)
    monkeypatch.setattr(probes, "probe_registered_clusters", _probe_clusters)
    # IMPORTANT: probe_openai_state is NOT monkeypatched here — we want the real
    # mapping logic (probes.py:151-159) to run against the cached value.

    # Build a Redis mock whose .get() returns the JSON-serialized
    # CapabilityResult for the configured base_url key (or None for cache miss).
    settings = app.dependency_overrides[get_settings]()
    base_url = settings.openai_base_url
    cache_key = f"openai:capabilities:{hashlib.sha256(base_url.encode('utf-8')).hexdigest()}"
    raw = cached_capability.model_dump_json() if cached_capability is not None else None

    client = MagicMock(spec=Redis)
    client.ping = AsyncMock(return_value=True)

    async def _get(key: str) -> bytes | None:
        return raw.encode("utf-8") if (raw is not None and key == cache_key) else None

    client.get = _get

    # The handler needs an OpenAI API key in Settings for probe_openai_state to
    # consider the cached value (otherwise it short-circuits to "missing_key").
    if api_key_present:

        def _fake_key(self) -> str:
            return "sk-test-fixture"

        monkeypatch.setattr(
            "backend.app.core.settings.Settings.openai_api_key",
            property(_fake_key),
        )

    app.dependency_overrides[health.get_redis_client] = lambda: client
    app.dependency_overrides[health.get_es_client] = lambda: _mock_httpx_client()

    from backend.app.db.session import get_db as _real_get_db

    async def _stub_db():
        yield None

    app.dependency_overrides[_real_get_db] = _stub_db


def _build_cap(
    *,
    models_endpoint: Literal["ok", "fail"],
    models_endpoint_status_code: int | None,
    chat: Literal["ok", "fail", "untested"] = "ok",
    fc: Literal["ok", "fail", "untested"] = "ok",
    struct: Literal["ok", "fail", "untested"] = "ok",
) -> CapabilityResult:
    from datetime import UTC, datetime

    return CapabilityResult(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-2024-08-06",
        models_endpoint=models_endpoint,
        chat_completion=chat,
        function_calling=fc,
        structured_output=struct,
        models_endpoint_status_code=models_endpoint_status_code,
        tested_at=datetime.now(UTC),
    )


class TestModelsEndpointInHealthzResponse:
    async def test_ac1_cache_hit_http_failure_exercises_real_incapable_mapping(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-1: cached CapabilityResult with models_endpoint='fail' + 401 →
        /healthz reports openai='incapable' (real probe_openai_state mapping)
        AND surfaces models_endpoint='fail' + status_code=401.
        """
        cached = _build_cap(
            models_endpoint="fail",
            models_endpoint_status_code=401,
            chat="untested",
            fc="untested",
            struct="untested",
        )
        _override_probes_real_openai_state(
            app, monkeypatch, cached_capability=cached, api_key_present=True
        )
        resp = await client.get("/healthz")
        body = resp.json()
        # Real mapping still maps any field == "fail" → "incapable"
        assert body["subsystems"]["openai"] == "incapable"
        # New diagnostic surface
        caps = body["openai_capabilities"]
        assert caps["models_endpoint"] == "fail"
        assert caps["models_endpoint_status_code"] == 401
        # Downstream probes correctly reported as untested per cascade.
        assert caps["chat"] == "untested"
        assert caps["function_calling"] == "untested"
        assert caps["structured_output"] == "untested"

    async def test_ac2_cache_hit_network_failure_reports_null_status_code(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-2: network-class failure cached with status_code=None →
        /healthz reports models_endpoint='fail' + status_code: null (key
        always present, value explicit null, not omitted).
        """
        cached = _build_cap(
            models_endpoint="fail",
            models_endpoint_status_code=None,
            chat="untested",
            fc="untested",
            struct="untested",
        )
        _override_probes_real_openai_state(
            app, monkeypatch, cached_capability=cached, api_key_present=True
        )
        resp = await client.get("/healthz")
        body = resp.json()
        caps = body["openai_capabilities"]
        assert caps["models_endpoint"] == "fail"
        # Key MUST be present even when value is null (FR-2: required-but-nullable).
        assert "models_endpoint_status_code" in caps
        assert caps["models_endpoint_status_code"] is None

    async def test_ac5_cache_hit_success_reports_null_status_code(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-5 (health-layer): success path cached with models_endpoint='ok'
        → /healthz reports models_endpoint='ok' + status_code: null
        explicitly (no 200 leak; key always present).
        """
        cached = _build_cap(
            models_endpoint="ok",
            models_endpoint_status_code=None,
            chat="ok",
            fc="ok",
            struct="ok",
        )
        _override_probes_real_openai_state(
            app, monkeypatch, cached_capability=cached, api_key_present=True
        )
        resp = await client.get("/healthz")
        body = resp.json()
        caps = body["openai_capabilities"]
        assert caps["models_endpoint"] == "ok"
        assert "models_endpoint_status_code" in caps
        assert caps["models_endpoint_status_code"] is None
        assert body["subsystems"]["openai"] == "configured"

    async def test_ac6_cache_miss_reports_untested(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-6: cache miss (no CapabilityResult row) → /healthz reports
        models_endpoint='untested' + status_code: null. subsystems.openai
        stays 'configured' because probe_openai_state's cache-miss branch
        intentionally does NOT block (probes.py:150-151).
        """
        _override_probes_real_openai_state(
            app, monkeypatch, cached_capability=None, api_key_present=True
        )
        resp = await client.get("/healthz")
        body = resp.json()
        caps = body["openai_capabilities"]
        assert caps["models_endpoint"] == "untested"
        assert caps["models_endpoint_status_code"] is None
        assert body["subsystems"]["openai"] == "configured"

    async def test_ac10_endpoint_layer_no_body_leak_through_real_check_capabilities(
        self, app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-10 endpoint-layer: chain a real mocked 401 (with body containing
        a token-like substring) through ``check_capabilities`` → Redis JSON
        round-trip → ``/healthz`` projection. The raw response text MUST NOT
        contain any portion of the OpenAI response body.
        """
        from unittest.mock import AsyncMock as _AsyncMock
        from unittest.mock import MagicMock as _MagicMock

        import structlog
        from redis.asyncio import Redis as _Redis

        from backend.app.llm.capability_check import check_capabilities

        BASE_URL = "https://api.openai.com/v1"
        MODEL = "gpt-4o-2024-08-06"
        FORBIDDEN_FRAGMENT = "sk-redacted-token-abc"
        FORBIDDEN_FULL = "Invalid Bearer token: sk-redacted-token-abc"

        # 1) Run check_capabilities against an httpx mock returning 401 + body.
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/models"):
                return httpx.Response(
                    401,
                    json={"error": {"message": FORBIDDEN_FULL}},
                    request=request,
                )
            return httpx.Response(500, request=request)

        # Mock Redis that records the value written by check_capabilities.
        ckecap_redis = _MagicMock(spec=_Redis)
        ckecap_redis.set = _AsyncMock(return_value=True)

        with structlog.testing.capture_logs() as captured:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                result = await check_capabilities(
                    BASE_URL, "sk-test-fixture", MODEL, ckecap_redis, http_client=http
                )

        # 2) Round-trip the cached JSON through Pydantic deserialization
        cached_json: bytes = ckecap_redis.set.call_args.args[1].encode("utf-8")
        roundtripped = CapabilityResult.model_validate_json(cached_json)
        assert roundtripped.models_endpoint == "fail"
        assert roundtripped.models_endpoint_status_code == 401

        # 3) Now hook the roundtripped result into /healthz's cache and call
        _override_probes_real_openai_state(
            app, monkeypatch, cached_capability=roundtripped, api_key_present=True
        )
        resp = await client.get("/healthz")

        # 4) Assert ALL three surfaces are body-free.
        # Cache layer (the JSON that went into Redis).
        cached_str = cached_json.decode("utf-8")
        assert "Invalid Bearer token" not in cached_str, cached_str
        assert FORBIDDEN_FRAGMENT not in cached_str, cached_str

        # Structlog WARN events captured during check_capabilities.
        log_blob = "".join(repr(e) for e in captured)
        assert "Invalid Bearer token" not in log_blob, log_blob
        assert FORBIDDEN_FRAGMENT not in log_blob, log_blob

        # WARN at step=models_endpoint with status_code=401 MUST exist (pinning
        # the structured fields, not just text-searching log_blob). Per
        # phase-gate review F1: the endpoint-layer AC-10 test should mirror
        # the cache-layer test's WARN assertion so the regression guard is
        # symmetric across both surfaces.
        from backend.tests._log_helpers import assert_log_level

        step_events = [e for e in captured if e.get("step") == "models_endpoint"]
        assert step_events, captured
        for entry in step_events:
            assert_log_level(entry, "warning")
        assert any(e.get("status_code") == 401 for e in step_events), step_events

        # /healthz response raw text (NOT just the parsed JSON — checks the
        # full serialized body including any field).
        assert "Invalid Bearer token" not in resp.text, resp.text
        assert FORBIDDEN_FRAGMENT not in resp.text, resp.text

        # Positive case: integer 401 IS exposed (operator's diagnostic).
        body = resp.json()
        assert body["openai_capabilities"]["models_endpoint_status_code"] == 401
        assert body["subsystems"]["openai"] == "incapable"

        # Sanity: result and roundtripped CapabilityResult are identical.
        assert result.model_dump() == roundtripped.model_dump()
