"""Cycle-3 F2 test: capability fallback STILL gates on daily budget.

Companion to ``test_digest_capability_fallback_respects_pricing.py``.
Sets ``structured_output='fail'`` AND pre-populates the daily budget
Redis key at the cap. Asserts the worker aborts at the budget peek with
no OpenAI call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.llm.budget_gate import daily_key
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import seed_completed_study, stub_capability
from backend.workers.digest import generate_digest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_capability_fail_with_budget_exhausted_returns_without_paid_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle-3 F2: structured_output=fail + budget exhausted → still aborts pre-call."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client, structured_output="fail")
        await redis_client.set(
            daily_key(datetime.now(UTC)),
            str(settings.openai_daily_budget_usd + 1),
            ex=86_400,
        )
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()

    create_mock = AsyncMock(side_effect=AssertionError("OpenAI must not be called"))

    class _StubChat:
        completions = type("_C", (), {"create": create_mock})()

    class _StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        chat = _StubChat()

        async def close(self) -> None:
            pass

    monkeypatch.setattr("backend.workers.digest.AsyncOpenAI", _StubClient)

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        assert await repo.get_digest_for_study(db, seeded["study_id"]) is None
    create_mock.assert_not_called()

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await redis_client.delete(daily_key(datetime.now(UTC)))
    finally:
        await redis_client.aclose()
