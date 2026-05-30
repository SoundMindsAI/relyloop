# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Health-cache unit tests (Story 2.2).

Uses a tiny in-memory stub for ``redis.asyncio.Redis`` so the cache write/
read round-trip is exercised hermetically — no real Redis needed.
"""

from __future__ import annotations

import pytest

from backend.app.adapters.health_cache import read_cached_health, write_cached_health
from backend.app.adapters.protocol import HealthStatus


class _StubRedis:
    """Minimal Redis stub: get/set with TTL noop."""

    def __init__(self, *, raise_on_get: bool = False) -> None:
        self._store: dict[str, str] = {}
        self._raise_on_get = raise_on_get

    async def get(self, key: str) -> str | None:
        if self._raise_on_get:
            raise RuntimeError("redis down")
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value


@pytest.fixture
def redis() -> _StubRedis:
    return _StubRedis()


class TestRoundTrip:
    async def test_write_then_read_round_trip(self, redis: _StubRedis) -> None:
        status = HealthStatus(
            status="green", version="9.4.0", checked_at="2026-05-09T00:00:00+00:00"
        )
        await write_cached_health(redis, "id-1", status)  # type: ignore[arg-type]
        got = await read_cached_health(redis, "id-1")  # type: ignore[arg-type]
        assert got is not None
        assert got.status == "green"
        assert got.version == "9.4.0"


class TestMiss:
    async def test_unknown_cluster_returns_none(self, redis: _StubRedis) -> None:
        assert await read_cached_health(redis, "id-missing") is None  # type: ignore[arg-type]

    async def test_redis_error_returns_none(self) -> None:
        redis = _StubRedis(raise_on_get=True)
        assert await read_cached_health(redis, "id-1") is None  # type: ignore[arg-type]


class TestCorrupted:
    async def test_corrupted_payload_returns_none(self, redis: _StubRedis) -> None:
        # Store something that isn't valid JSON for a HealthStatus
        redis._store["cluster:health:id-1"] = "not-json"
        assert await read_cached_health(redis, "id-1") is None  # type: ignore[arg-type]
