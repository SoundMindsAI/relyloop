"""Per-probe unit tests (infra_foundation Story 3.2).

Each probe in ``backend/app/api/probes.py`` is exercised in isolation with
mocked clients. Verifies the Literal return values + the safe-fallback
behavior on raised exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.api.probes import (
    probe_db,
    probe_elasticsearch,
    probe_openai_state,
    probe_opensearch,
    probe_redis,
)
from backend.app.llm.capability_models import CapabilityResult

# ---------------------------------------------------------------------------
# probe_db
# ---------------------------------------------------------------------------


class TestProbeDb:
    async def test_returns_ok_when_select_succeeds(self) -> None:
        """A live engine that returns a row → 'ok'."""
        engine = MagicMock(spec=AsyncEngine)

        # Build an async context manager that yields a connection that returns
        # a value from execute().
        conn = MagicMock()
        conn.execute = AsyncMock(return_value=None)
        conn_ctx = MagicMock()
        conn_ctx.__aenter__ = AsyncMock(return_value=conn)
        conn_ctx.__aexit__ = AsyncMock(return_value=None)
        engine.connect = MagicMock(return_value=conn_ctx)

        assert await probe_db(engine) == "ok"

    async def test_returns_down_on_exception(self) -> None:
        engine = MagicMock(spec=AsyncEngine)
        engine.connect = MagicMock(side_effect=RuntimeError("conn refused"))
        assert await probe_db(engine) == "down"


# ---------------------------------------------------------------------------
# probe_redis
# ---------------------------------------------------------------------------


class TestProbeRedis:
    async def test_returns_ok_on_pong(self) -> None:
        client = MagicMock(spec=Redis)
        client.ping = AsyncMock(return_value=True)
        assert await probe_redis(client) == "ok"

    async def test_returns_down_on_falsy_ping(self) -> None:
        client = MagicMock(spec=Redis)
        client.ping = AsyncMock(return_value=False)
        assert await probe_redis(client) == "down"

    async def test_returns_down_on_exception(self) -> None:
        client = MagicMock(spec=Redis)
        client.ping = AsyncMock(side_effect=ConnectionError("Redis unreachable"))
        assert await probe_redis(client) == "down"


# ---------------------------------------------------------------------------
# probe_elasticsearch / probe_opensearch
# ---------------------------------------------------------------------------


class TestProbeElasticsearch:
    async def test_returns_reachable_on_2xx(self) -> None:
        client = MagicMock(spec=httpx.AsyncClient)

        async def _get(_url: str) -> httpx.Response:
            return httpx.Response(200, request=httpx.Request("GET", _url))

        client.get = _get
        result = await probe_elasticsearch(client, "http://elasticsearch:9200")
        assert result == "reachable"

    async def test_returns_unreachable_on_5xx(self) -> None:
        client = MagicMock(spec=httpx.AsyncClient)

        async def _get(_url: str) -> httpx.Response:
            return httpx.Response(503, request=httpx.Request("GET", _url))

        client.get = _get
        assert await probe_elasticsearch(client, "http://x") == "unreachable"

    async def test_returns_unreachable_on_exception(self) -> None:
        client = MagicMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        assert await probe_elasticsearch(client, "http://x") == "unreachable"


class TestProbeOpensearch:
    async def test_returns_reachable_on_2xx(self) -> None:
        client = MagicMock(spec=httpx.AsyncClient)

        async def _get(_url: str) -> httpx.Response:
            return httpx.Response(200, request=httpx.Request("GET", _url))

        client.get = _get
        assert await probe_opensearch(client, "http://opensearch:9200") == "reachable"

    async def test_returns_unreachable_on_exception(self) -> None:
        client = MagicMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        assert await probe_opensearch(client, "http://x") == "unreachable"


# ---------------------------------------------------------------------------
# probe_openai_state — synchronous; exhaustive matrix over (key, cache state)
# ---------------------------------------------------------------------------


def _make_cap(
    *,
    models: str = "ok",
    chat: str = "ok",
    fc: str = "ok",
    structured: str = "ok",
) -> CapabilityResult:
    return CapabilityResult(
        base_url="http://x",
        model="gpt-test",
        models_endpoint=models,
        chat_completion=chat,
        function_calling=fc,
        structured_output=structured,
        tested_at=datetime.now(UTC),
    )


class TestProbeOpenaiState:
    def test_no_key_returns_missing_key(self) -> None:
        assert probe_openai_state(None, _make_cap()) == "missing_key"
        assert probe_openai_state("", _make_cap()) == "missing_key"

    def test_key_set_no_cache_returns_configured(self) -> None:
        # Cache miss is non-blocking (Story 3.3 capability check runs in
        # background; until it lands, we report `configured`).
        assert probe_openai_state("sk-test", None) == "configured"

    def test_key_set_all_ok_returns_configured(self) -> None:
        assert probe_openai_state("sk-test", _make_cap()) == "configured"

    @pytest.mark.parametrize("field", ["models", "chat", "fc", "structured"])
    def test_key_set_any_fail_returns_incapable(self, field: str) -> None:
        kwargs: dict[str, str] = {field: "fail"}
        cap = _make_cap(**kwargs)
        assert probe_openai_state("sk-test", cap) == "incapable"

    def test_untested_fields_count_as_configured(self) -> None:
        """`untested` (i.e. cache populated but probe skipped) is not a fail."""
        cap = _make_cap(chat="untested", fc="untested", structured="untested")
        assert probe_openai_state("sk-test", cap) == "configured"
