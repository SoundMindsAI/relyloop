# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``UNKNOWN_MODEL_PRICING`` test for ``generate_digest``.

Sets ``Settings.openai_model`` to a value not in ``cost_model.known_models()``;
asserts the worker logs the failure code + returns without writing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
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


async def test_unknown_model_returns_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNKNOWN_MODEL_PRICING: model not in cost_model → no LLM call, no digest."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"
    settings.__dict__["openai_model"] = "gpt-future-preview-2099-01-01"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
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

    # Reset model so other tests start fresh.
    settings.__dict__["openai_model"] = "gpt-4o-2024-08-06"
