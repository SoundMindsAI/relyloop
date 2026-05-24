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

feat_digest_executable_followups_swap_template Story 2.3: extends with a
swap_template happy-path case (a second template seeded into the
catalogue + an LLM payload containing one valid ``swap_template`` item)
and an AC-13 case (single-template install → the worker omits the
``<available_templates>`` block AND the LLM payload omits swap_template
items entirely).
"""

from __future__ import annotations

import logging
import uuid
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


@pytest.mark.integration
@pytest.mark.asyncio
class TestWorkerSwapTemplateRoundTrip:
    """Worker round-trip covering the swap_template happy path + AC-13."""

    async def test_swap_template_happy_path_remaps_and_persists(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """LLM emits one swap_template item against a seeded catalogue.

        Worker fetches the catalogue, runs the remap helper, and persists
        the merged search_space (intersection bounds from LLM + heuristic
        defaults for the disjoint phrase_slop param).
        """
        # Seed parent study against template A (title_boost + tie_breaker).
        # best_trial_params MUST be a subset of declared_params — otherwise
        # the worker computes a non-empty `dropped` set and pre-pends a
        # "params no longer declared" text item, producing 2 followups
        # instead of 1 (the assertion at line 227 catches this regression).
        seeded = await seed_completed_study(
            declared_params={
                "title_boost": "float",
                "tie_breaker": "float",
            },
            best_trial_params={"title_boost": 0.8, "tie_breaker": 0.34},
        )
        # Seed an alternative template B (same engine_type, sharing title_boost
        # + adding phrase_slop) so the worker's catalogue fetch finds it.
        factory = get_session_factory()
        async with factory() as db:
            swap_target = await repo.create_query_template(
                db,
                id=str(uuid.uuid4()),
                name=f"swap-{uuid.uuid4().hex[:8]}",
                engine_type="elasticsearch",
                body='{"query": {"match_all": {}}}',
                declared_params={
                    "title_boost": "float",
                    "phrase_slop": "int",
                },
                version=1,
            )
            await db.commit()
            swap_target_id = swap_target.id

        settings = get_settings()
        settings.__dict__["openai_api_key"] = "sk-test"
        redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
        try:
            await stub_capability(redis_client, structured_output="ok")
        finally:
            await redis_client.aclose()

        swap_followup: dict[str, Any] = {
            "kind": "swap_template",
            "rationale": "swap to template B for phrase_slop coverage",
            "template_id": swap_target_id,
            "search_space": {
                "params": {
                    "title_boost": {"type": "float", "low": 0.5, "high": 2.0},
                }
            },
        }
        patch_async_openai(
            monkeypatch,
            make_openai_response(
                narrative="Swap-template happy path.",
                suggested_followups=[swap_followup],
            ),
        )
        from backend.workers.digest import generate_digest

        await generate_digest({}, seeded["study_id"])

        async with factory() as db:
            digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        followups = digest.suggested_followups
        assert len(followups) == 1
        f = followups[0]
        assert f["kind"] == "swap_template"
        assert f["template_id"] == swap_target_id
        # Worker's remap step merged: intersection (title_boost from LLM) +
        # heuristic phrase_slop defaults.
        assert "title_boost" in f["search_space"]["params"]
        assert "phrase_slop" in f["search_space"]["params"]
        # LLM-emitted title_boost bounds preserved verbatim.
        assert f["search_space"]["params"]["title_boost"]["low"] == 0.5
        assert f["search_space"]["params"]["title_boost"]["high"] == 2.0

    async def test_single_template_install_no_swap_template_persisted(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-13: when the catalogue is empty (only the parent template is
        registered), the worker omits ``<available_templates>`` from the
        prompt and the LLM should not emit swap_template items. If the LLM
        misbehaves, the persisted swap_template would be downgraded to
        ``text`` with reason=not_found — assert no swap_template lands.
        """
        seeded = await seed_completed_study()
        settings = get_settings()
        settings.__dict__["openai_api_key"] = "sk-test"
        redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
        try:
            await stub_capability(redis_client, structured_output="ok")
        finally:
            await redis_client.aclose()
        # LLM emits two harmless text items — no swap_template in this case.
        patch_async_openai(
            monkeypatch,
            make_openai_response(
                narrative="Single template install.",
                suggested_followups=[
                    "Add brand-disambiguation queries",
                    "Consider adding a category facet",
                ],
            ),
        )
        from backend.workers.digest import generate_digest

        await generate_digest({}, seeded["study_id"])

        factory = get_session_factory()
        async with factory() as db:
            digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        kinds = {f["kind"] for f in digest.suggested_followups}
        assert "swap_template" not in kinds
