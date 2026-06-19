# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for Arq worker functions."""

from __future__ import annotations

import structlog
from redis.asyncio import Redis

from backend.app.llm.budget_gate import record_cost


async def safe_record_cost(
    redis: Redis,
    cost_usd: float,
    *,
    logger: structlog.stdlib.BoundLogger,
    log_message: str,
    event_type: str,
) -> float | None:
    """Record an LLM cost, swallowing transient Redis failures.

    Per GPT-5.5 cycle-2 C2-F3 (feat_llm_judgments): a Redis hiccup AFTER a
    paid LLM call must not propagate up and abort the worker — the worker
    persists its artifacts (judgments, digest) BEFORE calling this, so
    under-counting daily spend during a Redis outage is recoverable on
    rollover while losing the paid-for output is not. Returns ``None`` on
    failure.

    ``log_message`` / ``event_type`` are passed by the caller so each worker
    keeps its own log voice (``judgment worker: …`` /
    ``judgment_record_cost_failed`` etc.) while sharing the one defensive
    record-cost contract.
    """
    try:
        return await record_cost(redis, cost_usd)
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            log_message,
            event_type=event_type,
            cost_usd=cost_usd,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None
