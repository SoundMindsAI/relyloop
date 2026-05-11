"""AC-1 happy-path test for ``generate_digest`` (Story 2.1).

Seeds a completed study with a pending proposal; mocks OpenAI; runs the
worker; asserts the digest row exists with the deterministic
recommended_config, the pending proposal is UPDATED in place (id
unchanged, status still 'pending', config_diff + metric_delta
populated), and no second proposal row is created.
"""

from __future__ import annotations

import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.models import Proposal
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


async def test_happy_path_updates_pending_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1: digest row created; pending proposal UPDATED in place."""
    monkeypatch.setattr(
        get_settings(), "_openai_api_key" if False else "openai_api_key", "sk-test", raising=False
    )
    # Pydantic-settings cached_property: set the underlying via __dict__.
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    settings_redis_url = settings.redis_url
    redis_client = Redis.from_url(settings_redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()
    create_mock = patch_async_openai(monkeypatch, make_openai_response())

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        assert digest.narrative.startswith("Test digest narrative")
        # Deterministic recommendation: best-trial params filtered to declared.
        assert digest.recommended_config == {"field_boosts.title": 4.7, "tie_breaker": 0.34}
        assert digest.parameter_importance is not None
        assert len(digest.suggested_followups) >= 1
        assert digest.generated_by.startswith("openai:")

        # Pending proposal UPDATED in place — id unchanged, status still pending.
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is not None
        assert proposal.id == seeded["proposal_id"]
        assert proposal.status == "pending"
        assert proposal.config_diff == {
            "field_boosts.title": {"from": 3.0, "to": 4.7},  # midpoint of 1..5 = 3.0
            "tie_breaker": {"from": 0.5, "to": 0.34},  # midpoint of 0..1 = 0.5
        }
        assert proposal.metric_delta is not None
        assert proposal.metric_delta["ndcg@10"]["achieved"] == 0.762
        assert proposal.metric_delta["ndcg@10"]["baseline"] == 0.612

        # No second proposal row created.
        from sqlalchemy import func, select

        n = (
            await db.execute(
                select(func.count(Proposal.id)).where(Proposal.study_id == seeded["study_id"])
            )
        ).scalar_one()
        assert n == 1

    create_mock.assert_called_once()
