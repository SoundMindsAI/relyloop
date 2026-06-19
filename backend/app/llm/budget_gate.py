# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Redis-backed daily OpenAI budget counter (Story 1.7).

Two operations:

* :func:`peek_daily_total` — read-only ``GET`` returning the current rolling
  spend (0.0 when the key is absent).
* :func:`record_cost` — ``INCRBYFLOAT`` + 26h ``EXPIRE`` after a successful
  LLM call so the next pre-call peek reflects actual spend.

The pre-call check + post-call record split (per GPT-5.5 cycle 1 F8) is what
makes the budget gate honest: the worker peeks BEFORE making the LLM call and
raises :class:`BudgetExceededError` if the projected total would breach the
cap. The estimated max for that pre-call check lives in
:mod:`backend.app.llm.cost_model`.

The key is keyed per UTC day (``openai:budget:YYYY-MM-DD``) with a 26h TTL —
slightly longer than 24h so a clock skew or misfired rollover doesn't reset
the counter mid-day. ``INCRBYFLOAT`` is atomic in Redis so two concurrent
workers can race the check / record without corrupting the total; the worst
case (over-budget by one in-flight call) is tolerated per spec §13 cost-
guardrail tolerance.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from redis.asyncio import Redis

_TTL_SECONDS = 26 * 60 * 60


class BudgetExceededError(RuntimeError):
    """Pre-call peek + estimated max would breach the daily budget.

    Raised by the caller (worker or API preflight), not by this module —
    :mod:`backend.app.llm.budget_gate` is a pure data layer. The worker
    translates the exception to ``judgment_lists.failed_reason =
    'OPENAI_BUDGET_EXCEEDED'``; the API preflight translates to HTTP 503
    ``OPENAI_BUDGET_EXCEEDED``.
    """


def daily_key(now: datetime) -> str:
    """Return the per-UTC-day Redis key.

    Format: ``openai:budget:YYYY-MM-DD``. Tested in isolation (no Redis
    required) because the date math is the most failure-prone bit.
    """
    return f"openai:budget:{now.strftime('%Y-%m-%d')}"


async def peek_daily_total(redis: Redis, *, now: datetime | None = None) -> float:
    """Return the current daily total in USD; ``0.0`` when the key is unset.

    Read-only — does NOT touch the counter. Callers use this for the
    pre-call gate so the budget enforcement happens BEFORE the OpenAI
    request (per spec FR-2 + GPT-5.5 cycle 1 F8).
    """
    now = now or datetime.now(UTC)
    raw = await redis.get(daily_key(now))
    if raw is None:
        return 0.0
    # redis-py returns bytes by default unless decode_responses=True; cover both.
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return float(raw)


async def record_cost(
    redis: Redis,
    cost_usd: float,
    *,
    now: datetime | None = None,
) -> float:
    """Atomically increment the day's counter by ``cost_usd``; refresh TTL.

    Returns the new running total (so the caller can structured-log it).
    Uses ``INCRBYFLOAT`` (atomic) + a refresh ``EXPIRE`` so the key's TTL
    rolls forward on every recorded call — important during the late hours
    of a day when an in-flight call's record might land seconds before the
    natural 24h key would have expired.
    """
    now = now or datetime.now(UTC)
    key = daily_key(now)
    total = await redis.incrbyfloat(key, cost_usd)
    await redis.expire(key, _TTL_SECONDS)
    return float(total)


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
    paid LLM call must not propagate up and abort the caller — the caller
    persists its artifacts (judgments, digest) BEFORE calling this, so
    under-counting daily spend during a Redis outage is recoverable on
    rollover while losing the paid-for output is not. Returns ``None`` on
    failure.

    Lives here (next to :func:`record_cost`) rather than in the worker layer
    so the judgment-generation service can record cost without importing up
    into ``backend.workers``. ``log_message`` / ``event_type`` are passed by
    the caller so each caller keeps its own log voice (``judgment worker: …``
    / ``judgment_record_cost_failed`` etc.) while sharing the one defensive
    contract.
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
