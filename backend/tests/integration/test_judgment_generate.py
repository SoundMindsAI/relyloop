"""Integration tests for :func:`backend.workers.judgments.generate_judgments_llm`
(feat_llm_judgments Story 2.1).

Covers AC-1 (small-scale happy path) and AC-6 (exactly one LLM call per
query) without a live OpenAI endpoint. The OpenAI ``AsyncOpenAI`` client and
the engine ``ElasticAdapter`` are monkeypatched at module level so the worker
exercises the real DB + real repo + real prompt loader + real budget gate
against a Postgres test container and a Redis test container.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.adapters.protocol import NativeQuery, ScoredHit
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.qrels_loader import load_qrels
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_full_chain(num_queries: int = 5, num_docs_per_query: int = 5) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"jg-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"jg-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match": {"title": "{{ query_text }}"}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"jg-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        query_ids: list[str] = []
        for i in range(num_queries):
            q = await repo.create_query(
                db,
                id=str(uuid.uuid4()),
                query_set_id=query_set.id,
                query_text=f"query text {i}",
            )
            query_ids.append(q.id)
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"jg-jl-{uuid.uuid4().hex[:8]}",
            description="AC-1 small-scale",
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
    return {
        "judgment_list_id": jl.id,
        "query_ids": query_ids,
        "num_docs": num_docs_per_query,
    }


def _build_adapter_stub(query_ids: list[str], num_docs_per_query: int) -> Any:
    """Build a mock adapter whose ``search_batch`` returns canned hits per query."""

    def render(template: Any, params: dict[str, Any], query_text: str) -> NativeQuery:
        return NativeQuery(query_id="__placeholder__", body={"query": {"match_all": {}}})

    async def search_batch(
        *,
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]:
        del target, top_k, request_id, strict_errors, timeout
        result: dict[str, list[ScoredHit]] = {}
        for q in queries:
            result[q.query_id] = [
                ScoredHit(
                    doc_id=f"{q.query_id}-doc{i}",
                    score=1.0 - i * 0.05,
                    source={"body": f"document body {i} for query {q.query_id}"},
                )
                for i in range(num_docs_per_query)
            ]
        return result

    adapter = MagicMock()
    adapter.render = render
    adapter.search_batch = AsyncMock(side_effect=search_batch)
    return adapter


def _build_openai_stub_response(doc_ids: list[str]) -> Any:
    """Build a ChatCompletion-shaped mock response rating each doc 0..3."""
    ratings_payload = {
        "ratings": [
            {
                "doc_id": did,
                "rating": (i % 4),
                "rationale": f"rationale for {did}",
            }
            for i, did in enumerate(doc_ids)
        ]
    }
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50

    message = MagicMock()
    message.content = json.dumps(ratings_payload)

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


async def test_happy_path_ac1_ac6(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker walks 5 queries × 5 docs, exactly 5 LLM calls, list → complete."""
    seeded = await _seed_full_chain(num_queries=5, num_docs_per_query=5)
    jl_id = seeded["judgment_list_id"]
    query_ids = seeded["query_ids"]

    adapter = _build_adapter_stub(query_ids, num_docs_per_query=5)

    monkeypatch.setattr("backend.workers.judgments.build_adapter", lambda cluster: adapter)

    # Build the OpenAI mock: track call count, return a different rating
    # payload per call (one per query).
    mock_create = AsyncMock()

    async def fake_create(**kwargs: Any) -> Any:
        # Derive the doc_ids the worker expected from the user prompt — the
        # worker passes them in the user prompt under <doc id="..."> tags.
        user_msg = kwargs["messages"][1]["content"]
        import re

        doc_ids = re.findall(r'<doc id="([^"]+)">', user_msg)
        return _build_openai_stub_response(doc_ids)

    mock_create.side_effect = fake_create

    fake_client = MagicMock()
    fake_client.chat.completions.create = mock_create
    fake_client.close = AsyncMock()

    def fake_async_openai(*args: Any, **kwargs: Any) -> Any:
        return fake_client

    monkeypatch.setattr("backend.workers.judgments.AsyncOpenAI", fake_async_openai)

    # Make sure OPENAI_API_KEY is present in the test settings — bypass the
    # cached_property by setting an env var that the secret-file resolver
    # would NOT pick up; easier to just patch get_settings.
    from backend.app.core.settings import get_settings

    real_settings = get_settings()

    class _FakeSettings:
        openai_api_key = "sk-test"
        openai_base_url = real_settings.openai_base_url
        openai_model = "gpt-4o-2024-08-06"
        openai_daily_budget_usd = 10.0
        redis_url = real_settings.redis_url

    monkeypatch.setattr("backend.workers.judgments.get_settings", lambda: _FakeSettings())

    from backend.workers.judgments import generate_judgments_llm

    await generate_judgments_llm({}, jl_id)

    # Assert: exactly one LLM call per query (AC-6).
    assert mock_create.await_count == 5

    # Assert: 25 judgments persisted (AC-1 small scale).
    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.get_judgment_list(db, jl_id)
        assert jl is not None
        assert jl.status == "complete"
        assert jl.failed_reason is None
        count = await repo.count_judgments_for_list(db, jl_id)
        assert count == 25  # 5 queries × 5 docs

        # AC-6 — every judgment has source='llm' + rater_ref starting with 'openai:'.
        breakdown = await repo.source_breakdown_for_list(db, jl_id)
        assert breakdown == {"llm": 25, "human": 0}

        # qrels round-trip via the real loader — confirm the worker output
        # is shaped right for downstream run_trial consumption.
        qrels = await load_qrels(db, jl_id)
        assert len(qrels) == 5
        for q_id in query_ids:
            assert q_id in qrels
            assert len(qrels[q_id]) == 5


async def test_openai_not_configured_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker bails to ``failed_reason='OPENAI_NOT_CONFIGURED'`` when key missing."""
    seeded = await _seed_full_chain(num_queries=2, num_docs_per_query=2)
    jl_id = seeded["judgment_list_id"]

    from backend.app.core.settings import get_settings

    real_settings = get_settings()

    class _FakeSettings:
        openai_api_key = None
        openai_base_url = real_settings.openai_base_url
        openai_model = "gpt-4o-2024-08-06"
        openai_daily_budget_usd = 10.0
        redis_url = real_settings.redis_url

    monkeypatch.setattr("backend.workers.judgments.get_settings", lambda: _FakeSettings())

    from backend.workers.judgments import generate_judgments_llm

    await generate_judgments_llm({}, jl_id)

    factory = get_session_factory()
    async with factory() as db:
        jl = await repo.get_judgment_list(db, jl_id)
        assert jl is not None
        assert jl.status == "failed"
        assert jl.failed_reason == "OPENAI_NOT_CONFIGURED"
