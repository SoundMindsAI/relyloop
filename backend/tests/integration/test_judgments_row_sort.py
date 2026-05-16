"""``?sort=`` on ``/api/v1/judgment-lists/{id}/judgments``
(feat_data_table_primitive Story 1.3 — per-list judgment row sort).

The per-list judgments endpoint adds a custom sort surface separate from
the generic ``<col>:<dir>`` shape used by the other sortable resources.
``JudgmentRowSortKey`` is a Literal of ``rating:asc | rating:desc |
created_at:asc | created_at:desc | source:asc | source:desc``.

Asserts the endpoint:

- Accepts the documented sort tokens and orders rows accordingly.
- Combines sort with ``?source=`` filter without losing either.
- Returns 422 ``VALIDATION_ERROR`` on out-of-Literal values.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.models import Judgment, Query
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def _seed_judgments(n_llm: int = 3, n_human: int = 3) -> str:
    """Seed a judgment list with mixed-source rows spanning the rating
    range so sort ordering is verifiable."""
    factory = get_session_factory()
    suffix = uuid.uuid4().hex[:6]
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"jrs-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"jrs-qs-{suffix}",
            cluster_id=cluster.id,
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"jrs-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"jrs-jl-{suffix}",
            description=None,
            query_set_id=qs.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        # One query for all judgments.
        query = Query(
            id=str(uuid.uuid4()),
            query_set_id=qs.id,
            query_text=f"sample query {suffix}",
            reference_answer=None,
            query_metadata=None,
        )
        db.add(query)
        await db.flush()
        for i in range(n_llm):
            db.add(
                Judgment(
                    id=str(uuid.uuid4()),
                    judgment_list_id=jl.id,
                    query_id=query.id,
                    doc_id=f"doc-llm-{i}",
                    rating=i,  # 0, 1, 2 — distinct ratings
                    source="llm",
                    # Neutral non-model fixture string per CLAUDE.md rule
                    # against hardcoded LLM model names — production code
                    # reads the model from Settings; tests don't need a real
                    # model identifier here.
                    rater_ref="test-llm-rater",
                    confidence=0.8,
                    notes=None,
                )
            )
        for i in range(n_human):
            db.add(
                Judgment(
                    id=str(uuid.uuid4()),
                    judgment_list_id=jl.id,
                    query_id=query.id,
                    doc_id=f"doc-human-{i}",
                    rating=(i + 1) % 4,  # spread across 0-3
                    source="human",
                    rater_ref="operator",
                    confidence=1.0,
                    notes=None,
                )
            )
        await db.commit()
        return jl.id


async def test_rating_desc_orders_judgments_by_rating(
    async_client: httpx.AsyncClient,
) -> None:
    jl_id = await _seed_judgments()
    resp = await async_client.get(f"/api/v1/judgment-lists/{jl_id}/judgments?sort=rating:desc")
    assert resp.status_code == 200, resp.text
    ratings = [r["rating"] for r in resp.json()["data"]]
    assert ratings == sorted(ratings, reverse=True), f"rating:desc order violated: {ratings}"


async def test_rating_asc_orders_judgments_by_rating(
    async_client: httpx.AsyncClient,
) -> None:
    jl_id = await _seed_judgments()
    resp = await async_client.get(f"/api/v1/judgment-lists/{jl_id}/judgments?sort=rating:asc")
    assert resp.status_code == 200, resp.text
    ratings = [r["rating"] for r in resp.json()["data"]]
    assert ratings == sorted(ratings), f"rating:asc order violated: {ratings}"


async def test_source_asc_orders_judgments_by_source(
    async_client: httpx.AsyncClient,
) -> None:
    jl_id = await _seed_judgments()
    resp = await async_client.get(f"/api/v1/judgment-lists/{jl_id}/judgments?sort=source:asc")
    assert resp.status_code == 200, resp.text
    sources = [r["source"] for r in resp.json()["data"]]
    # 'human' < 'llm' alphabetically; all 'human' rows precede all 'llm' rows.
    assert sources == sorted(sources), f"source:asc order violated: {sources}"


async def test_sort_combines_with_source_filter(
    async_client: httpx.AsyncClient,
) -> None:
    jl_id = await _seed_judgments()
    resp = await async_client.get(
        f"/api/v1/judgment-lists/{jl_id}/judgments?sort=rating:desc&source=llm"
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["data"]
    assert all(r["source"] == "llm" for r in rows), (
        f"source=llm filter leaked non-llm rows: {[r['source'] for r in rows]}"
    )
    ratings = [r["rating"] for r in rows]
    assert ratings == sorted(ratings, reverse=True)


async def test_sort_invalid_value_returns_validation_error(
    async_client: httpx.AsyncClient,
) -> None:
    jl_id = await _seed_judgments(n_llm=1, n_human=0)
    resp = await async_client.get(f"/api/v1/judgment-lists/{jl_id}/judgments?sort=rating:upward")
    assert resp.status_code == 422, resp.text
