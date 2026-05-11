"""Cycle-2 F7 all-dropped sub-case test for ``generate_digest``.

Best trial used 4 params; template now declares 0 of them; assert:
* recommended_config = {}
* pending proposal is DELETED (unshippable empty config_diff artifact)
* digest IS persisted with a strong follow-up flagging the drift
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


async def test_all_dropped_writes_empty_recommendation_and_deletes_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle-2 F7: best-trial params all drift out → empty recommendation + DELETE proposal."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    # Best trial used 4 params; template now declares NONE of them.
    seeded = await seed_completed_study(
        best_trial_params={
            "old_param_a": 1.0,
            "old_param_b": 2.0,
            "old_param_c": "x",
            "old_param_d": True,
        },
        declared_params={
            "new_param_x": {"type": "float", "min": 0.0, "max": 1.0},
        },
    )
    patch_async_openai(monkeypatch, make_openai_response())

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        assert digest.recommended_config == {}
        # First follow-up flags the drift with the count.
        assert digest.suggested_followups[0].startswith("Best trial used 4 params no longer")
        for dropped in ("old_param_a", "old_param_b"):
            assert dropped in digest.suggested_followups[0]

        # Pending proposal DELETED (unshippable artifact).
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is None
