"""Worker round-trip with structured followups (Story 2.3).

Drives ``generate_digest`` against a real Postgres + a mocked OpenAI
client returning three items:

1. A valid ``narrow`` with a 2-float ``search_space`` (passes Pydantic).
2. A cardinality-busting ``narrow`` with 12 floats (downgrades to text).
3. A free-form ``text`` item.

Asserts the persisted JSONB:

- has 3 items (1 valid narrow + 1 downgraded text + 1 text)
- the downgraded item's rationale starts with ``[validation failed:
  search-space cardinality estimate exceeds 10^6"``
- a ``digest_followup_validation_downgraded`` WARN event was emitted.
"""

from __future__ import annotations

import logging
from typing import Any

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

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
)


_VALID_NARROW: dict[str, Any] = {
    "kind": "narrow",
    "rationale": "narrow tie_breaker around winner",
    "search_space": {
        "params": {
            "tie_breaker": {"type": "float", "low": 0.20, "high": 0.50},
        }
    },
}

# 12 floats × 100 each = 10^24 — busts the 10^6 cardinality cap.
_CARDINALITY_BUSTING_NARROW: dict[str, Any] = {
    "kind": "narrow",
    "rationale": "explore everything at once",
    "search_space": {
        "params": {f"f{i}": {"type": "float", "low": 0.0, "high": 1.0} for i in range(12)}
    },
}

_TEXT_FOLLOWUP: dict[str, Any] = {
    "kind": "text",
    "rationale": "add brand-disambiguation queries to the judgment list",
    "search_space": None,
}


@pytest.mark.integration
@pytest.mark.asyncio
class TestWorkerStructuredFollowupRoundTrip:
    async def test_validates_and_downgrades_and_persists(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Scope caplog to the followups logger so the downgrade WARN is captured.
        caplog.set_level(logging.WARNING, logger="backend.app.domain.study.followups")

        # Seed a study + pending proposal, stub capability OK + LLM response.
        seeded = await seed_completed_study()
        settings = get_settings()
        settings.__dict__["openai_api_key"] = "sk-test"
        redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
        try:
            await stub_capability(redis_client, structured_output="ok")
        finally:
            await redis_client.aclose()

        patch_async_openai(
            monkeypatch,
            make_openai_response(
                narrative="Test narrative for round-trip.",
                suggested_followups=[
                    _VALID_NARROW,
                    _CARDINALITY_BUSTING_NARROW,
                    _TEXT_FOLLOWUP,
                ],
            ),
        )

        # Drive the worker.
        from backend.workers.digest import generate_digest

        await generate_digest({}, seeded["study_id"])

        # Re-fetch the digest and assert the persisted JSONB shape.
        factory = get_session_factory()
        async with factory() as db:
            digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        followups = digest.suggested_followups
        # 3 items: valid narrow + downgraded text + text.
        assert len(followups) == 3, f"expected 3 items, got {len(followups)}: {followups}"

        kinds = [f["kind"] for f in followups]
        assert kinds.count("narrow") == 1
        assert kinds.count("text") == 2

        # The downgraded item carries the validation-failed prefix.
        downgraded = next(
            f
            for f in followups
            if f["kind"] == "text"
            and isinstance(f.get("rationale"), str)
            and f["rationale"].startswith("[validation failed: ")
        )
        assert "search-space cardinality" in downgraded["rationale"]
        assert "explore everything at once" in downgraded["rationale"]

        # The free-form text item is preserved as-is.
        free_form = next(
            f
            for f in followups
            if f["kind"] == "text"
            and f.get("rationale") == "add brand-disambiguation queries to the judgment list"
        )
        assert free_form["search_space"] is None

        # The downgrade WARN was emitted.
        event_types = [getattr(r, "event_type", None) for r in caplog.records]
        assert "digest_followup_validation_downgraded" in event_types
