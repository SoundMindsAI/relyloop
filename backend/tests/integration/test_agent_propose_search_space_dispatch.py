# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Full propose → create_study chain integration test (Story 4.2 / spec §14 + FR-6).

Verifies the end-to-end DB round-trip when the chat agent's LLM follows the
system-prompt chain: ``propose_search_space`` → consume returned
``search_space`` → ``create_study``. Asserts:

1. The starter search_space the propose tool generates against real
   ``query_templates.declared_params`` JSONB is consumable verbatim by
   ``create_study``.
2. The persisted ``studies.search_space`` JSONB matches the proposed one
   byte-for-byte.
3. Both telemetry events (``agent.search_space_proposed`` +
   ``agent.create_study.invoked``) fire INFO-level with the same
   ``conversation_id`` from the ToolContext.

Why direct impl invocation rather than mocking the OpenAI client:
- The orchestrator's dispatch loop is exhaustively unit-tested in
  ``backend/tests/unit/agent/test_*.py``.
- The unique coverage Story 4.2 adds is the DB round-trip (JSONB write +
  read) plus telemetry correlation — both of which surface here.
- Wiring a three-turn LLM mock (propose → create → text) adds significant
  fixture cost for coverage we already have.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.context import ToolContext
from backend.app.agent.tools.studies.create_study import (
    CreateStudyArgs,
    create_study_impl,
)
from backend.app.agent.tools.studies.propose_search_space import (
    ProposeSearchSpaceArgs,
    propose_search_space_impl,
)
from backend.app.db import repo

pytestmark = pytest.mark.integration


def _uuid() -> str:
    return str(uuid.uuid4())


async def _seed_cluster(db: AsyncSession) -> str:
    cluster = await repo.create_cluster(
        db,
        id=_uuid(),
        name=f"c-{_uuid()[:8]}",
        engine_type="elasticsearch",
        environment="dev",
        base_url="http://x:9200",
        auth_kind="es_basic",
        credentials_ref="ref",
    )
    return cluster.id


async def _seed_template(db: AsyncSession) -> str:
    template = await repo.create_query_template(
        db,
        id=_uuid(),
        name=f"qt-{_uuid()[:8]}",
        engine_type="elasticsearch",
        body="{}",
        declared_params={
            "title_boost": "float",
            "min_should_match": "int",
            "fuzziness": "string",
        },
        version=1,
    )
    return template.id


async def _seed_query_set(db: AsyncSession, cluster_id: str) -> str:
    qs = await repo.create_query_set(
        db,
        id=_uuid(),
        name=f"qs-{_uuid()[:8]}",
        cluster_id=cluster_id,
    )
    return qs.id


async def _seed_judgment_list(db: AsyncSession, cluster_id: str, query_set_id: str) -> str:
    jl = await repo.create_judgment_list(
        db,
        id=_uuid(),
        name=f"jl-{_uuid()[:8]}",
        query_set_id=query_set_id,
        cluster_id=cluster_id,
        target="idx",
        rubric="rubric text",
        status="complete",
    )
    return jl.id


async def test_propose_then_create_study_round_trips_search_space(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """Full chain: propose_search_space → use result in create_study → assert DB row."""
    cluster_id = await _seed_cluster(db_session)
    template_id = await _seed_template(db_session)
    qs_id = await _seed_query_set(db_session, cluster_id)
    jl_id = await _seed_judgment_list(db_session, cluster_id, qs_id)
    await db_session.commit()

    # ToolContext with a known conversation_id so we can correlate events.
    conv_id = f"conv-{_uuid()[:8]}"
    ctx = ToolContext(
        db=db_session,
        conversation_id=conv_id,
        redis=None,  # type: ignore[arg-type]  # not used by either tool
        arq_pool=None,
        settings=None,  # type: ignore[arg-type]  # neither tool reads settings
    )

    caplog.set_level(logging.INFO)

    # Step 1: propose_search_space — exercises real declared_params JSONB read.
    propose_args = ProposeSearchSpaceArgs(
        template_id=uuid.UUID(template_id), cluster_id=uuid.UUID(cluster_id)
    )
    propose_result = await propose_search_space_impl(propose_args, ctx)
    proposed_space = propose_result["search_space"]
    assert proposed_space["params"]["title_boost"]["log"] is True
    assert proposed_space["params"]["min_should_match"]["high"] == 5

    # Step 2: create_study with the proposed search_space.
    create_args = CreateStudyArgs(
        name=f"study-{_uuid()[:8]}",
        cluster_id=cluster_id,
        target="idx",
        template_id=template_id,
        query_set_id=qs_id,
        judgment_list_id=jl_id,
        search_space=proposed_space,
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config={"max_trials": 10},
    )
    create_result = await create_study_impl(create_args, ctx)
    new_study_id: str = create_result["id"]
    # create_study commits at step 5; the row is now durable.
    await db_session.commit()

    # Step 3: re-read the study from DB and assert the search_space round-tripped.
    persisted = await repo.get_study(db_session, new_study_id)
    assert persisted is not None
    assert persisted.search_space == proposed_space

    # Step 4: both telemetry events fired with the same conversation_id.
    propose_events = [r for r in caplog.records if "agent.search_space_proposed" in r.message]
    create_events = [r for r in caplog.records if "agent.create_study.invoked" in r.message]
    assert len(propose_events) >= 1
    assert len(create_events) >= 1
    for record in (propose_events[0], create_events[0]):
        assert record.levelno == logging.INFO
        assert f"conversation_id={conv_id}" in record.message
