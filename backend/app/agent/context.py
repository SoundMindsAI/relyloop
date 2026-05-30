# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""ToolContext — dependency bundle passed to every tool impl by the orchestrator.

Tools call into the service/repo layer using these. ``arq_pool`` is None when
the queue isn't connected; tools that enqueue work must raise
``QUEUE_UNAVAILABLE`` in that case (mirroring the open_pr proposal endpoint).

``conversation_id`` (added in feat_agent_propose_search_space Story 3.1) is the
stable per-conversation identifier passed from ``orchestrator.run_turn``.
Tool impls tag adherence-telemetry events (e.g. ``agent.search_space_proposed``,
``agent.create_study.invoked``) with this value so offline log correlation can
compute propose→create chain adherence per spec FR-6.
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
    conversation_id: str
    redis: Redis
    arq_pool: ArqRedis | None
    settings: Settings
