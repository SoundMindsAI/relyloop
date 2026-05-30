# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cycle-2 C2-F3 (from feat_llm_judgments) ordering canary for ``generate_digest``.

Patches ``record_cost`` to raise after a successful LLM call. Asserts the
digest row IS persisted (we paid for the call; under-counting daily
spend is recoverable on rollover; losing the digest is not).
"""

from __future__ import annotations

import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import (
    make_openai_response,
    patch_async_openai,
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


async def test_digest_persisted_when_redis_record_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist FIRST then record cost: a Redis flap on record_cost MUST NOT lose the digest."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()
    patch_async_openai(monkeypatch, make_openai_response())

    async def _broken_record_cost(*args: object, **kwargs: object) -> float:
        raise RuntimeError("simulated Redis flap during record_cost")

    monkeypatch.setattr("backend.workers.digest.record_cost", _broken_record_cost)

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None  # The paid-for digest survived.
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is not None
        assert proposal.metric_delta is not None
