"""Concurrent DELETE vs judgment-INSERT race test (feat_query_inline_crud §10 Threat 4).

Spec §10 Threat 4 says: even if our application-level pre-DELETE count
shows zero judgments, a concurrent INSERT could land between the count
and the DELETE. The contract is that Postgres's FK check during the
DELETE statement is the single source of truth — so the post-condition
is deterministic:

* EITHER the DELETE response is 204 AND no judgments exist for this
  query, OR
* the DELETE response is 409 ``QUERY_HAS_JUDGMENTS`` AND judgments exist
  for this query.

Never both, never neither. Race driven against the live ASGI router
(per GPT-5.5 phase-1 F4 — the test must exercise the HTTP contract, not
just the repo function).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import uuid_utils
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.db import repo
from backend.app.db.models import Judgment
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


async def _seed_scenario() -> tuple[str, str, str]:
    """Seed cluster + query_set + query + judgment_list.

    Returns ``(set_id, query_id, jl_id)``.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"qdr-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qdr-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        q = await repo.create_query(
            db,
            id=str(uuid_utils.uuid7()),
            query_set_id=qs.id,
            query_text="race-target",
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid_utils.uuid7()),
            name=f"qdr-jl-{uuid.uuid4().hex[:8]}",
            query_set_id=qs.id,
            cluster_id=cluster.id,
            target="t",
            rubric="r",
            status="complete",
        )
        await db.commit()
        return qs.id, q.id, jl.id


async def _attempt_delete_via_router(
    async_client: httpx.AsyncClient, set_id: str, query_id: str
) -> int:
    """Attempt the DELETE via the live ASGI router. Returns HTTP status."""
    resp = await async_client.delete(f"/api/v1/query-sets/{set_id}/queries/{query_id}")
    return resp.status_code


async def _attempt_insert(judgment_list_id: str, query_id: str) -> str:
    """Attempt the judgment insert in its own session. Returns 'inserted' or 'rejected'."""
    factory = get_session_factory()
    async with factory() as db:
        try:
            await repo.create_judgment(
                db,
                id=str(uuid_utils.uuid7()),
                judgment_list_id=judgment_list_id,
                query_id=query_id,
                doc_id="race-doc",
                rating=2,
                source="llm",
                rater_ref="openai:test",
            )
            await db.commit()
            return "inserted"
        except IntegrityError:
            await db.rollback()
            return "rejected"


async def test_race_post_condition_deterministic(async_client: httpx.AsyncClient) -> None:
    """Run the race 20× to surface any non-deterministic outcomes.

    Each iteration: seed fresh scenario → race DELETE-via-router and
    judgment-INSERT concurrently → assert the post-condition holds.
    """
    factory = get_session_factory()
    for _ in range(20):
        set_id, query_id, jl_id = await _seed_scenario()

        delete_status, insert_result = await asyncio.gather(
            _attempt_delete_via_router(async_client, set_id, query_id),
            _attempt_insert(jl_id, query_id),
        )

        async with factory() as db:
            judgment_stmt = select(Judgment).where(Judgment.query_id == query_id).limit(1)
            existing_judgment = (await db.execute(judgment_stmt)).scalar_one_or_none()
            existing_query = await repo.get_query(db, query_id)

        # Post-condition: exactly one of these two scenarios holds.
        scenario_a = delete_status == 204 and existing_query is None and existing_judgment is None
        scenario_b = (
            delete_status == 409 and existing_query is not None and existing_judgment is not None
        )

        assert scenario_a or scenario_b, (
            f"Race produced inconsistent state: delete_status={delete_status}, "
            f"insert_result={insert_result!r}, "
            f"query_exists={existing_query is not None}, "
            f"judgment_exists={existing_judgment is not None}"
        )
