# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration test — manual clone suppresses auto_followup auto-spawn.

feat_study_clone_from_previous Story 1.3 case (g) — covers FR-15 / D-10 /
AC-12. When the operator manually clones a study with auto_followup_depth>0,
the clone B becomes a child of A via parent_study_id. When A later completes
and the auto_followup worker fires, the LAYER-2 idempotency check at
backend/workers/auto_followup.py:87 sees B in list_children_of_study(A.id)
and self-suppresses with log event auto_followup_enqueued_duplicate_dropped.

This is the intended behavior — the operator has manually started the
iteration; the worker standing down is correct. No discriminator column,
no new filter — the behavior emerges from the existing FK-equality check.

Lives in its own file (not test_studies_api.py) to keep that file under
its 50KB ceiling and to colocate auto_followup-shaped tests with worker
infrastructure (mirrors test_auto_followup.py's structure).
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import structlog

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable

pytestmark = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — integration test requires DB",
)


def _make_arq_ctx(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], MagicMock]:
    """Fake Arq ctx with a stubbed arq_pool. Mirrors test_auto_followup's helper."""
    arq_pool = MagicMock()
    arq_pool.enqueue_job = AsyncMock(return_value=None)
    ctx: dict[str, Any] = {"arq_pool": arq_pool}
    return ctx, arq_pool


async def _seed_minimum_for_clone() -> dict[str, str]:
    """Seed cluster + template + qs + jl. Returns the IDs."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"clone-af-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"clone-af-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={"bm25_k1": "float"},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"clone-af-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"clone-af-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": judgment_list.id,
    }


@pytest.fixture
def _default_overlap_probe_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the preflight overlap probe so clone POSTs aren't rejected
    by INSUFFICIENT_JUDGMENT_OVERLAP in the hermetic test DB (no real ES)."""
    from backend.app.services.study_preflight import OverlapProbeResult

    async def fake_probe(*args: object, **kwargs: object) -> OverlapProbeResult:
        # Return a probe result that always passes (overlap_size >= judged_doc_count).
        return OverlapProbeResult(
            overlap_size=3,
            probed_doc_count=3,
            judged_doc_count=3,
            representative_query_id="01990000-0000-7000-8000-000000000099",
        )

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)


async def test_clone_suppresses_auto_followup_via_layer_2_idempotency(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    _default_overlap_probe_passes: None,
) -> None:
    """FR-15 / D-10 / AC-12 — manual clone B already exists → worker drops auto-spawn.

    Follows AC-12 lifecycle precisely:
      (i)   seed parent A as 'running' with auto_followup_depth=1
      (ii)  create clone B via the POST API code path with parent_study_id=A
      (iii) transition A to 'completed' via direct DB write (mirrors the
            _seed_parent_chain pattern in test_auto_followup.py — bypasses
            the orchestrator since tests run hermetically; the state-guard
            sentinel context authorizes the ORM update)
      (iv)  invoke enqueue_followup_study(ctx, A.id) directly
      (v)   assert duplicate-drop event + unchanged child list

    Per cycle-2 finding F4 (accepted at plan time): the AC-12 lifecycle
    ordering is meaningful — clone must exist BEFORE the worker fires,
    which only happens after A reaches 'completed'. Replicating that
    sequence is the strictest test of the FR-15 invariant.
    """
    from backend.app.services.study_state import _GUARD_KEY
    from backend.workers.auto_followup import enqueue_followup_study

    ids = await _seed_minimum_for_clone()

    # Step (i): seed parent A as 'running' with auto_followup_depth=1.
    parent_a_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_study(
            db,
            id=parent_a_id,
            name=f"clone-af-parent-{uuid.uuid4().hex[:8]}",
            cluster_id=ids["cluster_id"],
            target="stub-index",
            template_id=ids["template_id"],
            query_set_id=ids["query_set_id"],
            judgment_list_id=ids["judgment_list_id"],
            search_space={"params": {"bm25_k1": {"type": "float", "low": 0.1, "high": 2.0}}},
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 20, "auto_followup_depth": 1},
            status="running",  # AC-12: parent is in-flight when clone arrives
            optuna_study_name=parent_a_id,
        )
        await db.commit()

    # Step (ii): create clone B via the NEW POST API code path
    # while A is still 'running' (AC-12 ordering).
    body = {
        "name": "clone-b",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": {"params": {"bm25_k1": {"type": "float", "low": 0.1, "high": 2.0}}},
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
        "parent_study_id": parent_a_id,
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 201, resp.text
    clone_b_id = resp.json()["id"]

    # Pre-condition: B is the sole child of A via parent_study_id FK.
    async with factory() as db:
        children_before = await repo.list_children_of_study(db, parent_a_id)
    assert len(children_before) == 1
    assert children_before[0].id == clone_b_id

    # Step (iii): transition A from 'running' to 'completed' via direct
    # DB write under the state-guard sentinel (mirrors _seed_parent_chain's
    # pattern at test_auto_followup.py:155-163). The orchestrator that
    # would normally make this transition is bypassed in tests.
    async with factory() as db:
        parent = await repo.get_study(db, parent_a_id)
        assert parent is not None
        db.sync_session.info[_GUARD_KEY] = True
        try:
            parent.status = "completed"
            await db.flush()
        finally:
            db.sync_session.info.pop(_GUARD_KEY, None)
        await db.commit()

    # Step (iv): invoke the auto_followup worker on A. The LAYER-2
    # idempotency check at auto_followup.py:87 should fire because
    # list_children_of_study(A.id) returns [B].
    ctx, arq_pool = _make_arq_ctx(monkeypatch)
    with structlog.testing.capture_logs() as cap:
        await enqueue_followup_study(ctx, parent_a_id)

    # Step (v): assert the duplicate-dropped event fired AND no new child
    # was created (length still 1 = just B).
    duplicate_events = [
        e for e in cap if e.get("event_type") == "auto_followup_enqueued_duplicate_dropped"
    ]
    assert len(duplicate_events) >= 1, (
        f"FR-15: expected auto_followup_enqueued_duplicate_dropped, got: {cap!r}"
    )
    assert duplicate_events[0]["parent_study_id"] == parent_a_id
    assert clone_b_id in duplicate_events[0]["existing_child_ids"]

    async with factory() as db:
        children_after = await repo.list_children_of_study(db, parent_a_id)
    assert len(children_after) == 1, (
        "FR-15: manual clone must suppress auto-spawn — child count unchanged"
    )
    assert children_after[0].id == clone_b_id
    # And no enqueue_job call (the worker returned before enqueueing start_study).
    assert arq_pool.enqueue_job.await_count == 0
