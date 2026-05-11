"""Cycle-1 F5/F9 partial-drift test for ``generate_digest``.

Best trial used 4 params; template now declares only 2 of them; assert:
* recommended_config has 2 keys (only the still-declared ones)
* config_diff has 2 keys
* suggested_followups[0] mentions the dropped keys
* digest IS persisted; pending proposal is UPDATED in place (not deleted)
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


async def test_dropped_param_excluded_from_recommended_config_and_flagged_in_followups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle-1 F5/F9: partial drift → filter recommended_config + prepend follow-up."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    # Best trial used 4 params; template declares only 2 of them.
    seeded = await seed_completed_study(
        best_trial_params={
            "field_boosts.title": 4.7,
            "tie_breaker": 0.34,
            "fuzziness": "AUTO",
            "operator": "AND",
        },
        declared_params={
            "field_boosts.title": {"type": "float", "min": 1.0, "max": 5.0},
            "tie_breaker": {"type": "float", "min": 0.0, "max": 1.0},
        },
    )
    patch_async_openai(monkeypatch, make_openai_response(suggested_followups=["LLM-followup"]))

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        # recommended_config filtered to declared.
        assert set(digest.recommended_config.keys()) == {"field_boosts.title", "tie_breaker"}
        # First follow-up mentions the dropped keys.
        assert digest.suggested_followups[0].startswith("Best trial used params no longer")
        for dropped_key in ("fuzziness", "operator"):
            assert dropped_key in digest.suggested_followups[0]
        # LLM-supplied follow-up is preserved (after the deterministic prefix).
        assert "LLM-followup" in digest.suggested_followups

        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is not None
        assert proposal.status == "pending"
        assert set(proposal.config_diff.keys()) == {"field_boosts.title", "tie_breaker"}
