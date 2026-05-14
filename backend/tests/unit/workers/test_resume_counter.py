"""Unit tests for the Redis daily-counter helpers in ``judgments_resume``.

Covers:

* :func:`resume_counter_key` — key shape + UTC normalisation across a
  non-UTC tz that crosses the date boundary (defensive coding GPT-5.5
  flagged in plan review).
* :func:`increment_and_check_cap` — INCR semantics + cap-boundary +
  TTL refresh on every INCR (mirrors budget_gate.record_cost precedent
  at backend/app/llm/budget_gate.py:86-87).

The tests use a hand-rolled :class:`_FakeRedis` so they stay pure-unit
(no Redis service required). The integration test
``test_judgments_resume_sweep.py`` uses the real Redis service container
to verify the wire-level behavior.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone

from backend.workers.judgments_resume import (
    _TTL_SECONDS,
    increment_and_check_cap,
    resume_counter_key,
)


class _FakeRedis:
    """Minimal in-memory async stand-in for ``redis.asyncio.Redis``.

    Implements only the methods this module touches (``incr``, ``expire``).
    Each call's TTL value is recorded on ``self.expire_calls`` so tests can
    assert TTL refresh cadence without a live Redis.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self.expire_calls: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expire_calls.append((key, seconds))
        return True

    def seed(self, key: str, value: int) -> None:
        """Test helper: pre-seed a counter (used for the at-cap boundary case)."""
        self._counts[key] = value


def test_resume_counter_key_format() -> None:
    """Key shape is ``judgments:resume:YYYY-MM-DD:<jid>`` with UTC date."""
    now = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    assert resume_counter_key(now, "ABC123") == "judgments:resume:2026-05-14:ABC123"


def test_resume_counter_key_normalizes_non_utc_datetime() -> None:
    """Non-UTC aware datetime crossing the date boundary normalizes to UTC.

    2026-05-14 23:30 PDT (UTC-07:00) == 2026-05-15 06:30 UTC. The key MUST
    use 2026-05-15, not 2026-05-14. Spec §9 "Required invariants": Redis
    key MUST use UTC date. GPT-5.5 plan-review cycle-1 F2 (Accept).
    """
    pdt = timezone(timedelta(hours=-7))
    now_pdt = datetime(2026, 5, 14, 23, 30, tzinfo=pdt)
    assert resume_counter_key(now_pdt, "ABC123") == "judgments:resume:2026-05-15:ABC123"


def test_increment_returns_count_and_capped_below_cap() -> None:
    """First INCR returns ``(1, False)`` when cap is 24."""
    fake = _FakeRedis()

    async def _run() -> tuple[int, bool]:
        return await increment_and_check_cap(fake, "ABC", cap=24)  # type: ignore[arg-type]

    count, capped = asyncio.run(_run())
    assert count == 1
    assert capped is False


def test_increment_returns_capped_when_post_incr_exceeds_cap() -> None:
    """Counter starts at 24; INCR → 25; capped=True (post-INCR value > cap)."""
    fake = _FakeRedis()
    # Pre-seed the key the helper will use.
    key = resume_counter_key(datetime.now(UTC), "ABC")
    fake.seed(key, 24)

    async def _run() -> tuple[int, bool]:
        return await increment_and_check_cap(fake, "ABC", cap=24)  # type: ignore[arg-type]

    count, capped = asyncio.run(_run())
    assert count == 25
    assert capped is True


def test_ttl_refreshed_on_every_incr() -> None:
    """Two consecutive INCRs both call ``redis.expire(key, _TTL_SECONDS)``.

    Mirrors backend/app/llm/budget_gate.py:86-87 — the "refresh TTL on every
    record" cadence prevents key expiry mid-day during the late hours of
    a day if a calling pattern keeps the row alive past 23:30 UTC.
    """
    fake = _FakeRedis()

    async def _run_twice() -> None:
        await increment_and_check_cap(fake, "ABC", cap=24)  # type: ignore[arg-type]
        await increment_and_check_cap(fake, "ABC", cap=24)  # type: ignore[arg-type]

    asyncio.run(_run_twice())

    assert len(fake.expire_calls) == 2
    for _key, ttl in fake.expire_calls:
        assert ttl == _TTL_SECONDS
