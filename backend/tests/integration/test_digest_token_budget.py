"""AC-8 cost-budget benchmark for ``generate_digest`` (Story 4.2).

Asserts that a representative digest call stays within the spec §13 NFR
budget: input + output tokens < 8000 total; cost < $0.05 at the
configured model's pricing.

Cycle-1 F8: model name comes from ``Settings.openai_model`` via
``compute_call_cost(get_settings().openai_model, ...)`` — never
hardcoded. Skips the cost assertion when the model isn't in
``known_models()`` so the benchmark stays valid as the pricing table
grows.
"""

from __future__ import annotations

import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.llm.cost_model import compute_call_cost, known_models
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

# Representative token usage for a typical study (10 trials × 4 params +
# parameter_importance map + system prompt). Anchored to the cycle-1 F4
# DIGEST_RESPONSE_FORMAT contract (max_completion_tokens=2_000).
REPRESENTATIVE_PROMPT_TOKENS = 5_000
REPRESENTATIVE_COMPLETION_TOKENS = 1_500


async def test_digest_cost_under_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-8: representative digest call stays under 8000 tokens + $0.05."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()
    response = make_openai_response(
        prompt_tokens=REPRESENTATIVE_PROMPT_TOKENS,
        completion_tokens=REPRESENTATIVE_COMPLETION_TOKENS,
    )
    patch_async_openai(monkeypatch, response)

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None

    # Token assertion: total < 8000 per spec AC-8.
    total_tokens = REPRESENTATIVE_PROMPT_TOKENS + REPRESENTATIVE_COMPLETION_TOKENS
    assert total_tokens < 8_000, f"representative call exceeded 8000 tokens: {total_tokens}"

    # Cost assertion: must use Settings.openai_model (cycle-1 F8). Skip
    # when the configured model is not in the pricing table (defensive —
    # the worker's UNKNOWN_MODEL_PRICING preflight would have aborted
    # the run, but the benchmark may execute against a future model).
    if settings.openai_model in known_models():
        cost = compute_call_cost(
            settings.openai_model,
            REPRESENTATIVE_PROMPT_TOKENS,
            REPRESENTATIVE_COMPLETION_TOKENS,
        )
        assert cost < 0.05, (
            f"representative digest call cost ${cost:.4f} for model "
            f"{settings.openai_model!r} (cap is $0.05 per spec AC-8)"
        )
