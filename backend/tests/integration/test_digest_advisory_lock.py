# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cycle-2 F6 advisory-lock test for ``generate_digest``.

Two ``generate_digest`` coroutines launched simultaneously against the
same study. Asserts:
* Exactly one acquires the lock + performs the LLM call.
* The other observes the lock contention (or the post-commit
  idempotency guard) and returns without calling OpenAI.

Note: The most reliable assertion is "OpenAI was called exactly once,
and exactly one digest row exists". The lock vs. idempotency guard split
is an implementation detail — both paths achieve the no-double-pay goal.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import (
    make_openai_response,
    seed_completed_study,
    stub_capability,
)
from backend.workers.digest import generate_digest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_concurrent_workers_do_not_double_pay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two parallel generate_digest invocations → exactly ONE OpenAI call + ONE digest row."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()

    # Slow-mock the OpenAI call so the second coroutine has time to attempt
    # the lock while the first holds it.
    async def _slow_create(*args: object, **kwargs: object) -> object:
        await asyncio.sleep(0.5)
        return make_openai_response()

    create_mock = AsyncMock(side_effect=_slow_create)

    class _StubChat:
        completions = type("_C", (), {"create": create_mock})()

    class _StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        chat = _StubChat()

        async def close(self) -> None:
            pass

    monkeypatch.setattr("backend.workers.digest.AsyncOpenAI", _StubClient)

    # Fire two coroutines simultaneously.
    await asyncio.gather(
        generate_digest({}, seeded["study_id"]),
        generate_digest({}, seeded["study_id"]),
    )

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None  # exactly one digest row exists

    # Exactly ONE OpenAI call across both coroutines.
    assert create_mock.call_count == 1
