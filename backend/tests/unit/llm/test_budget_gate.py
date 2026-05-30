# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Redis-backed daily budget gate (Story 1.7).

Mock-Redis tests via :class:`unittest.mock.AsyncMock`. No live Redis dep —
the module's surface is small enough that a method-level mock is sufficient.

Covers:

* :func:`daily_key` produces the YYYY-MM-DD format.
* :func:`peek_daily_total` returns 0.0 on missing key.
* :func:`peek_daily_total` returns the float on hit (with bytes-decoded path).
* :func:`record_cost` calls INCRBYFLOAT + EXPIRE.
* Day rollover (different ``now`` → different key → 0.0 on peek).
* Round-trip via paired peek/record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from backend.app.llm.budget_gate import (
    BudgetExceededError,
    daily_key,
    peek_daily_total,
    record_cost,
)


def test_daily_key_format() -> None:
    assert daily_key(datetime(2026, 5, 11, 12, 0, tzinfo=UTC)) == "openai:budget:2026-05-11"
    # New day's key is different.
    assert daily_key(datetime(2026, 5, 12, 0, 1, tzinfo=UTC)) == "openai:budget:2026-05-12"


async def test_peek_empty_returns_zero() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    now = datetime(2026, 5, 11, tzinfo=UTC)

    total = await peek_daily_total(redis, now=now)
    assert total == 0.0
    redis.get.assert_awaited_once_with("openai:budget:2026-05-11")


async def test_peek_returns_float_on_str_hit() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="2.50")
    total = await peek_daily_total(redis, now=datetime(2026, 5, 11, tzinfo=UTC))
    assert total == 2.50


async def test_peek_returns_float_on_bytes_hit() -> None:
    """redis-py default returns bytes; ensure decode path works."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=b"3.75")
    total = await peek_daily_total(redis, now=datetime(2026, 5, 11, tzinfo=UTC))
    assert total == 3.75


async def test_record_cost_calls_incrbyfloat_and_expire() -> None:
    redis = AsyncMock()
    redis.incrbyfloat = AsyncMock(return_value=4.25)
    redis.expire = AsyncMock(return_value=True)

    new_total = await record_cost(redis, 0.25, now=datetime(2026, 5, 11, tzinfo=UTC))
    assert new_total == 4.25
    redis.incrbyfloat.assert_awaited_once_with("openai:budget:2026-05-11", 0.25)
    # 26h TTL roll-forward.
    redis.expire.assert_awaited_once_with("openai:budget:2026-05-11", 26 * 60 * 60)


async def test_day_rollover_uses_different_key_returns_zero() -> None:
    """Same Redis state but rolling over to a new day reads an empty key."""
    redis = AsyncMock()

    # GET returns a value for day-1's key only.
    async def fake_get(key: str) -> bytes | None:
        return b"7.00" if key == "openai:budget:2026-05-11" else None

    redis.get = AsyncMock(side_effect=fake_get)

    day1 = datetime(2026, 5, 11, 23, 59, tzinfo=UTC)
    day2 = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
    assert await peek_daily_total(redis, now=day1) == 7.00
    assert await peek_daily_total(redis, now=day2) == 0.0


async def test_record_then_peek_uses_same_key() -> None:
    """Verify the record + peek round-trip targets the same key."""
    state: dict[str, float] = {}

    async def fake_incrbyfloat(key: str, amount: float) -> float:
        state[key] = state.get(key, 0.0) + amount
        return state[key]

    async def fake_get(key: str) -> str | None:
        return str(state[key]) if key in state else None

    redis = AsyncMock()
    redis.incrbyfloat = AsyncMock(side_effect=fake_incrbyfloat)
    redis.expire = AsyncMock(return_value=True)
    redis.get = AsyncMock(side_effect=fake_get)

    now = datetime(2026, 5, 11, 10, 0, tzinfo=UTC)
    await record_cost(redis, 0.30, now=now)
    await record_cost(redis, 0.20, now=now)

    total = await peek_daily_total(redis, now=now)
    assert total == 0.50


def test_budget_exceeded_error_inherits_from_runtime_error() -> None:
    """Type-only check — caller code uses ``except RuntimeError`` paths."""
    assert issubclass(BudgetExceededError, RuntimeError)
