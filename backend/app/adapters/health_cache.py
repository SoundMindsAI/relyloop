"""Cluster ``HealthStatus`` Redis cache (infra_adapter_elastic Story 2.2).

Decision Log 2026-05-09: cluster health checks are cached in Redis with a
30s TTL. The cache backs:

* The ``GET /api/v1/clusters/{id}`` detail endpoint (Story 3.2) — avoids
  re-probing the cluster on every page render.
* The ``/healthz`` extension (Story 3.5) — reads cached values only,
  never live-probes inside the 200ms health timeout.

Cache misses + corrupted entries return ``None`` so callers fall through to
a fresh probe (``services.cluster.get_or_probe_health`` in Story 3.1).

Key shape: ``cluster:health:{cluster_id}`` (canonical per Decision Log).
"""

from __future__ import annotations

from redis.asyncio import Redis

from backend.app.adapters.protocol import HealthStatus

_TTL_SECONDS = 30
"""Redis TTL on cluster:health:* entries (Decision Log 2026-05-09)."""


def _key(cluster_id: str) -> str:
    return f"cluster:health:{cluster_id}"


async def read_cached_health(redis: Redis, cluster_id: str) -> HealthStatus | None:
    """Return the cached ``HealthStatus`` for a cluster, or ``None`` on miss.

    Treats Redis errors and corrupted JSON as cache misses — the caller
    falls through to a fresh probe rather than failing the request.
    """
    try:
        raw = await redis.get(_key(cluster_id))
    except Exception:  # noqa: BLE001 — cache miss is non-fatal
        return None
    if raw is None:
        return None
    try:
        return HealthStatus.model_validate_json(raw)
    except Exception:  # noqa: BLE001 — corrupted cache treated as miss
        return None


async def write_cached_health(redis: Redis, cluster_id: str, status: HealthStatus) -> None:
    """Cache a fresh ``HealthStatus`` with the canonical 30s TTL.

    Best-effort — Redis errors are not raised. Cache failure here only
    means the next request re-probes; it never breaks the probe path.
    """
    try:
        await redis.set(_key(cluster_id), status.model_dump_json(), ex=_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — cache write failure is non-fatal
        return
