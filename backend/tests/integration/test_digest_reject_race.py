# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cycle-3 F4 reject-race test for ``generate_digest``.

The worker reads the pending proposal, makes a long-running LLM call,
then UPDATEs the proposal post-LLM. If the operator rejects the proposal
mid-LLM-call, the post-LLM UPDATE must NOT silently overwrite the
rejection.

The cycle-3 F4 fix made ``update_proposal_for_digest`` conditional on
``WHERE status='pending'``. This test simulates the race by mocking the
LLM call with a slow callback that rejects the proposal before returning.
"""

from __future__ import annotations

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


async def test_proposal_rejected_during_llm_call_does_not_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle-3 F4: post-LLM UPDATE no-ops when the operator rejected mid-flight."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()

    # Inject a side-effect into the LLM call: reject the proposal before
    # returning the response.
    factory = get_session_factory()

    async def _reject_then_respond(*args: object, **kwargs: object) -> object:
        # Use a separate session/transaction to commit the rejection while
        # the worker's outer tx is still in progress.
        async with factory() as db_inner:
            await repo.reject_proposal(db_inner, seeded["proposal_id"], reason="changed my mind")
            await db_inner.commit()
        return make_openai_response()

    create_mock = AsyncMock(side_effect=_reject_then_respond)

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

    async with factory() as db:
        # Digest IS persisted (digest is per-study, not per-proposal).
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        # Proposal STAYS rejected; the conditional UPDATE no-opped.
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is not None
        assert proposal.status == "rejected"
        assert proposal.rejected_reason == "changed my mind"
        # The rejection's empty config_diff is preserved (NOT overwritten).
        assert proposal.config_diff == {}
        assert proposal.metric_delta is None
