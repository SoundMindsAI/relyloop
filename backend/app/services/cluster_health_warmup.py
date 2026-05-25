"""Startup cluster-health cache warmup (bug_demo_clusters_unreachable_in_healthz).

Fire-and-forget background task spawned from the FastAPI lifespan hook
that pages through all registered clusters and populates the
``cluster:health:{cluster_id}`` Redis cache (30s TTL) so
:func:`backend.app.api.probes.probe_registered_clusters` reports truthful
counts within ~5s of API startup instead of waiting for the first
``/api/v1/clusters`` request to lazy-warm the cache.

Pattern mirrors :func:`backend.app.llm.capability_check.run_capability_check_background`:

- Catches every exception so a broken cluster / DB / Redis cannot crash
  the API process.
- Propagates :class:`asyncio.CancelledError` so shutdown is clean.
- Emits one INFO summary log on completion (or skip).

Per CLAUDE.md Absolute Rule #11, ``/healthz`` itself must stay
cache-only (no live probes inside the 200ms request budget); this
warmup runs out-of-band at startup so the cache lands populated.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.logging import get_logger
from backend.app.db import repo
from backend.app.services import cluster as cluster_svc

logger = get_logger(__name__)


async def run_cluster_health_warmup_background(
    db_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
) -> None:
    """Warm ``cluster:health:*`` for every registered cluster at API startup.

    Fire-and-forget background task.

    Args:
        db_factory: ``async_sessionmaker[AsyncSession]`` resolved from
            :func:`backend.app.db.session.get_session_factory`. Opened via
            ``async with db_factory() as db:`` so the session is released
            on normal completion AND on ``asyncio.CancelledError``
            propagation (Python context-manager protocol guarantee).
        redis_client: Async Redis client. Pinged once at the start; if
            unreachable, the warmup logs a single WARN and proceeds
            (per-cluster ``get_or_probe_health`` cache writes will
            silently no-op, but operators still see WARN logs for any
            probe failures).

    Returns:
        ``None``. Never raises (except ``asyncio.CancelledError`` for
        clean shutdown).
    """
    start = time.monotonic()

    # FR-6 / D-9: ping Redis once. Cache helpers swallow Redis errors
    # silently per ``backend.app.adapters.health_cache:38-58``; without
    # the explicit ping, operators get zero signal that the cache is
    # unwritable. The positional message string IS the structlog ``event``
    # field — tests assert on that exact identifier (per plan cycle-1 A1).
    try:
        await redis_client.ping()
    except Exception as exc:  # noqa: BLE001 — Redis-down is non-fatal
        logger.warning(
            "cluster_health_warmup_redis_unavailable",
            error=str(exc),
        )
        # Continue — per-cluster probes still fire; their failures still log.

    # Collect cluster rows under SHORT-LIVED DB sessions, then probe
    # OUTSIDE the session so the per-cluster HTTP timeout (~5s per
    # adapter.health_check) doesn't hold an asyncpg connection. Holding
    # the session during HTTP probes triggers connection-pool contention
    # with concurrent test fixtures + production endpoints — caught by
    # CI's `test_ac7_concurrent_merges_serialize_via_row_lock` running
    # against the lifespan-spawned warmup.
    failures = 0
    clusters: list[Any] = []
    try:
        async with db_factory() as db:
            registered = await repo.count_clusters(db)
            if registered == 0:
                logger.info("cluster_health_warmup_skipped", count=0)
                return

            cursor: tuple[object, str] | None = None
            while True:
                page = await repo.list_clusters(db, cursor=cursor, limit=200)
                if not page:
                    break
                clusters.extend(page)
                if len(page) < 200:
                    break
                last = page[-1]
                cursor = (last.created_at, last.id)
        # DB session is released here. Probes that follow do not hold any
        # asyncpg connection.
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — task-level swallow
        logger.warning(
            "cluster_health_warmup_raised",
            error=str(exc),
        )
        return

    count = len(clusters)
    for c in clusters:
        try:
            await cluster_svc.get_or_probe_health(redis_client, c)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — per-cluster swallow
            failures += 1
            logger.warning(
                "cluster_health_warmup_cluster_failed",
                cluster_id=c.id,
                cluster_name=c.name,
                error=str(exc),
            )

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "cluster_health_warmup_completed",
        count=count,
        failures=failures,
        duration_ms=duration_ms,
    )
