"""ToolContext — dependency bundle passed to every tool impl by the orchestrator.

Tools call into the service/repo layer using these. ``arq_pool`` is None when
the queue isn't connected; tools that enqueue work must raise
``QUEUE_UNAVAILABLE`` in that case (mirroring the open_pr proposal endpoint).
"""

from __future__ import annotations

from dataclasses import dataclass

from arq.connections import ArqRedis
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.settings import Settings


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Bundles dependencies handed to tool impls so each impl has one parameter."""

    db: AsyncSession
    redis: Redis
    arq_pool: ArqRedis | None
    settings: Settings
