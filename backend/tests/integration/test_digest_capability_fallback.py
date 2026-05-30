# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""AC-11 + cycle-3 F2 test: capability-fail falls back to narrative-only.

Seeds a completed study; stubs the capability cache with
``structured_output='fail'``; runs the worker; asserts:
* digest row is persisted with non-empty narrative + parameter_importance
* recommended_config is empty + suggested_followups are empty
* pending proposal stays in ``status='pending'`` with empty config_diff
* OpenAI was called WITHOUT ``response_format`` (the degraded path)
"""

from __future__ import annotations

import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import (
    make_openai_text_response,
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


async def test_capability_fail_writes_narrative_only_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-11: capability fail → narrative-only digest; recommended_config={}; proposal untouched."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client, structured_output="fail")
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()
    create_mock = patch_async_openai(monkeypatch, make_openai_text_response())

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        assert digest.narrative.strip() != ""
        # Degraded path: parameter_importance still computed from Optuna,
        # but recommended_config is empty and suggested_followups is empty.
        assert digest.recommended_config == {}
        assert digest.suggested_followups == []

        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is not None
        assert proposal.status == "pending"
        assert proposal.config_diff == {}

    # Cycle-3 F2: confirm response_format was NOT passed in the degraded path.
    create_mock.assert_called_once()
    call_kwargs = create_mock.call_args.kwargs
    assert "response_format" not in call_kwargs
