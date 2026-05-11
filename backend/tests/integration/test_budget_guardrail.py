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


def _placeholder_unused_import_for_typing_only(_x: Any) -> None:
    """Suppress unused-import warning for Any (referenced in annotations)."""
    return None
