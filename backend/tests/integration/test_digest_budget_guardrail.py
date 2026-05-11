"""Budget-peek-breach test for ``generate_digest``.

Pre-populates the daily budget Redis key so that the pre-call peek sees
``current + estimated_max > openai_daily_budget_usd`` and aborts. Asserts
no digest written, no proposal mutation, no OpenAI call.
"""

from __future__ import annotations

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


async def test_budget_peek_breach_returns_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPENAI_BUDGET_EXCEEDED: pre-call peek sees breach → no LLM call, no digest."""
    from datetime import UTC, datetime

    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
        # Pre-populate the daily budget at the cap to force a breach.
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
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is not None
        assert proposal.status == "pending"
        assert proposal.config_diff == {}
    create_mock.assert_not_called()

    # Cleanup the daily key so other tests start fresh.
    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await redis_client.delete(daily_key(datetime.now(UTC)))
    finally:
        await redis_client.aclose()
