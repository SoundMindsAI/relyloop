"""Integration test for AC-4 budget enforcement (feat_llm_judgments Story 2.1).

Pre-seeds the Redis daily counter above the configured budget and runs the
worker; expects partial judgments to persist (zero, because the very first
peek trips the gate) and the list to flip to ``status='failed'`` with
``failed_reason='OPENAI_BUDGET_EXCEEDED'``.

The worker stubs the engine adapter and OpenAI client; only Redis state is
real (test container).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.asyncio import Redis

from backend.app.adapters.protocol import NativeQuery, ScoredHit
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.llm.budget_gate import daily_key
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_chain() -> str:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"bg-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"bg-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"bg-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        for i in range(3):
            await repo.create_query(
                db,
                id=str(uuid.uuid4()),
                query_set_id=query_set.id,
                query_text=f"q{i}",
            )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"bg-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="generating",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
    return jl.id


async def test_budget_exceeded_marks_list_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    jl_id = await _seed_chain()

    from backend.app.core.settings import get_settings

    real_settings = get_settings()
    redis_url = real_settings.redis_url

    # Pre-seed the daily counter ABOVE the budget so the very first peek
    # trips the gate.
    redis = Redis.from_url(redis_url, decode_responses=False)
    key = daily_key(datetime.now(UTC))
    try:
        await redis.set(key, "99.99")  # well above the test budget
    finally:
        await redis.aclose()

    # Adapter: returns hits, but it shouldn't be called (budget trips first).
    adapter = MagicMock()
    adapter.render = lambda template, params, qt: NativeQuery(query_id="x", body={})
    adapter.search_batch = AsyncMock(
        return_value={"x": [ScoredHit(doc_id="d1", score=1.0, source={"body": "b"})]}
    )
    monkeypatch.setattr("backend.workers.judgments.build_adapter", lambda c: adapter)

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock()
    fake_client.close = AsyncMock()
    monkeypatch.setattr("backend.workers.judgments.AsyncOpenAI", lambda **kw: fake_client)

    class _FakeSettings:
        openai_api_key = "sk-test"
        openai_base_url = real_settings.openai_base_url
        openai_model = "gpt-4o-2024-08-06"
        openai_daily_budget_usd = 1.0  # well below the seeded counter
        redis_url = real_settings.redis_url

    monkeypatch.setattr("backend.workers.judgments.get_settings", lambda: _FakeSettings())

    from backend.workers.judgments import generate_judgments_llm

    await generate_judgments_llm({}, jl_id)

    # No LLM calls should have been attempted (budget tripped first).
    assert fake_client.chat.completions.create.await_count == 0

    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.get_judgment_list(db, jl_id)
        assert jl is not None
        assert jl.status == "failed"
        assert jl.failed_reason == "OPENAI_BUDGET_EXCEEDED"
        count = await repo.count_judgments_for_list(db, jl_id)
        # Zero partial judgments because the very first peek tripped.
        assert count == 0

    # Cleanup the test Redis key so subsequent tests don't trip.
    redis = Redis.from_url(redis_url, decode_responses=False)
    try:
        await redis.delete(key)
    finally:
        await redis.aclose()


async def test_budget_exceeded_mid_loop_preserves_partial_judgments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-4 partial-persist path (per GPT-5.5 final review F4).

    Seed a 3-query set, allow the first query to succeed, and ensure the
    second query's pre-call peek trips the budget. Verifies:

    * The first query's judgments persist in the DB (atomicity contract).
    * The list flips to ``status='failed'`` with
      ``failed_reason='OPENAI_BUDGET_EXCEEDED'``.
    * Only one LLM call was made (the second query was refused before
      the call could happen).
    """
    import json as _json

    jl_id = await _seed_chain()

    from backend.app.core.settings import get_settings

    real_settings = get_settings()
    await _clear_budget_for_mid_loop_test(real_settings.redis_url)

    # Pre-seed Redis with $0 so the first query passes the budget peek
    # (estimated ~$0.03 per call); then the post-call record_cost bumps the
    # counter above the budget so the second query's peek trips.
    # Set a tight budget that the FIRST call's estimated_max fits under but
    # the SECOND call's (current + estimated_max) does not.
    # gpt-4o estimated_max_call_cost is ~$0.045 (10K input * 0.0025 + 2K output * 0.01).
    # Set budget to $0.05: first call's peek (0 + 0.045) ≤ 0.05 OK; record_cost
    # adds ~$0.045; second peek (0.045 + 0.045 = 0.09) > 0.05 → trip.

    # Build adapter that returns 2 hits per query.
    adapter = MagicMock()
    adapter.render = lambda template, params, qt: NativeQuery(query_id="__placeholder__", body={})

    async def search_batch(
        *,
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[Any]]:
        return {
            q.query_id: [
                ScoredHit(doc_id=f"{q.query_id}-d1", score=1.0, source={"body": "b1"}),
                ScoredHit(doc_id=f"{q.query_id}-d2", score=0.9, source={"body": "b2"}),
            ]
            for q in queries
        }

    adapter.search_batch = AsyncMock(side_effect=search_batch)
    monkeypatch.setattr("backend.workers.judgments.build_adapter", lambda c: adapter)

    # OpenAI mock: returns canned ratings for whichever doc_ids the user prompt
    # contains. usage.prompt_tokens=10000, completion_tokens=2000 → cost matches
    # the estimated_max ceiling so the second-query peek trips deterministically.
    async def fake_create(**kwargs: Any) -> Any:
        import re

        user_msg = kwargs["messages"][1]["content"]
        doc_ids = re.findall(r'<doc id="([^"]+)">', user_msg)
        usage = MagicMock()
        usage.prompt_tokens = 10_000
        usage.completion_tokens = 2_000
        message = MagicMock()
        message.content = _json.dumps(
            {"ratings": [{"doc_id": d, "rating": 2, "rationale": "r"} for d in doc_ids]}
        )
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        response.usage = usage
        return response

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=fake_create)
    fake_client.close = AsyncMock()
    monkeypatch.setattr("backend.workers.judgments.AsyncOpenAI", lambda **kw: fake_client)

    class _FakeSettings:
        openai_api_key = "sk-test"
        openai_base_url = real_settings.openai_base_url
        openai_model = "gpt-4o-2024-08-06"
        openai_daily_budget_usd = 0.05  # tight: 1 call fits, 2 trips
        redis_url = real_settings.redis_url

    monkeypatch.setattr("backend.workers.judgments.get_settings", lambda: _FakeSettings())

    from backend.workers.judgments import generate_judgments_llm

    await generate_judgments_llm({}, jl_id)

    # Exactly one LLM call was made (the second query's peek tripped before
    # the call).
    assert fake_client.chat.completions.create.await_count == 1

    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.get_judgment_list(db, jl_id)
        assert jl is not None
        assert jl.status == "failed"
        assert jl.failed_reason == "OPENAI_BUDGET_EXCEEDED"
        # The first query's 2 judgments persisted (partial result).
        count = await repo.count_judgments_for_list(db, jl_id)
        assert count == 2

    # Cleanup the daily counter so subsequent tests start clean.
    await _clear_budget_for_mid_loop_test(real_settings.redis_url)


async def _clear_budget_for_mid_loop_test(redis_url: str) -> None:
    redis = Redis.from_url(redis_url, decode_responses=False)
    try:
        await redis.delete(daily_key(datetime.now(UTC)))
    finally:
        await redis.aclose()


def _placeholder_unused_import_for_typing_only(_x: Any) -> None:
    """Suppress unused-import warning for Any (referenced in annotations)."""
    return None
