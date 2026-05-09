"""Subsystem health probes (infra_foundation Story 3.2 / FR-2).

Each probe is a small async function that returns a Literal status string.
The probes are wrapped by ``backend.app.api.health.healthz()`` in
``asyncio.wait_for(..., timeout=0.2)`` and run concurrently via
``asyncio.gather()`` so total endpoint latency stays under 500ms p99.

Each probe must:

- Be idempotent and side-effect-free
- Catch its own connection-class errors (handler catches ``TimeoutError``
  via ``return_exceptions=True``)
- Return a Literal — never None
- Avoid blocking I/O — use the project's async clients (asyncpg, aioredis,
  httpx async)
"""

from __future__ import annotations

from typing import Literal

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.app.llm.capability_models import CapabilityResult


async def probe_db(engine: AsyncEngine) -> Literal["ok", "down"]:
    """Issue ``SELECT 1`` against the engine. Returns 'ok' or 'down'."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001 — health probe must not raise
        return "down"


async def probe_redis(client: Redis) -> Literal["ok", "down"]:
    """PING the Redis client. Returns 'ok' or 'down'."""
    try:
        pong = await client.ping()
        return "ok" if pong else "down"
    except Exception:  # noqa: BLE001
        return "down"


async def probe_elasticsearch(
    client: httpx.AsyncClient, base_url: str
) -> Literal["reachable", "unreachable"]:
    """GET {base_url}/_cluster/health (or just /). Returns 'reachable'/'unreachable'."""
    try:
        resp = await client.get(f"{base_url.rstrip('/')}/_cluster/health")
        return "reachable" if resp.status_code < 500 else "unreachable"
    except Exception:  # noqa: BLE001
        return "unreachable"


async def probe_opensearch(
    client: httpx.AsyncClient, base_url: str
) -> Literal["reachable", "unreachable"]:
    """GET {base_url}/_cluster/health for OpenSearch. Same shape as ES."""
    try:
        resp = await client.get(f"{base_url.rstrip('/')}/_cluster/health")
        return "reachable" if resp.status_code < 500 else "unreachable"
    except Exception:  # noqa: BLE001
        return "unreachable"


def probe_openai_state(
    api_key: str | None, capability_cache: CapabilityResult | None
) -> Literal["configured", "missing_key", "incapable"]:
    """Synchronous probe — reads cached capability state, no network I/O.

    Mapping per spec FR-2:
        - api_key None or empty   → 'missing_key'
        - api_key set + cache hit + all 4 fields ok   → 'configured'
        - api_key set + cache hit + any field 'fail'  → 'incapable'
        - api_key set + cache miss                    → 'configured' (don't block;
            capability check runs at startup non-blockingly per Story 3.3)
    """
    if not api_key:
        return "missing_key"
    if capability_cache is None:
        return "configured"
    fields = (
        capability_cache.models_endpoint,
        capability_cache.chat_completion,
        capability_cache.function_calling,
        capability_cache.structured_output,
    )
    if any(f == "fail" for f in fields):
        return "incapable"
    return "configured"
