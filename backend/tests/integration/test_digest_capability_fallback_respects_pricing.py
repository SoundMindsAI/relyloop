# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cycle-3 F2 test: capability fallback STILL gates on pricing.

Pre-cycle-3 design short-circuited on capability fail. That meant the
narrative-only fallback path bypassed the pricing + budget gates — but
the narrative-only call STILL hits OpenAI and STILL costs money. Cycle-3
F2 made capability a mode flag, so pricing + budget MUST still apply.

This test sets ``structured_output='fail'`` AND
``Settings.openai_model`` to a value not in ``known_models()``. Asserts
no OpenAI call is made (UNKNOWN_MODEL_PRICING preflight wins).
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


async def test_capability_fail_with_unknown_pricing_returns_without_paid_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle-3 F2: structured_output=fail + unknown pricing → still aborts pre-call."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"
    settings.__dict__["openai_model"] = "gpt-future-preview-2099-01-01"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client, structured_output="fail")
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

    settings.__dict__["openai_model"] = "gpt-4o-2024-08-06"
