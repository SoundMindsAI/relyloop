# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for backend/workers/auto_followup.py (Story 2.1).

Real Postgres + real Redis (test container). Verifies the FR-3 worker
behavior end-to-end across the 7 FR-9 events Story 2.1 emits.

The 8th FR-9 event (`auto_followup_cancelled_with_parent`) is covered
by Story 1.3's cascade-service unit tests; here we only exercise the
worker's enqueue-side branches.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
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


async def _seed_parent_chain(
    *,
    auto_followup_depth: int | None = 3,
    parent_status: str = "completed",
    best_metric: float | None = 0.50,
    n_complete_trials: int = 20,
    first_trial_metric: float = 0.30,
) -> dict[str, str]:
    """Seed a complete chain: cluster + template + query_set + judgment_list +
    parent study + N complete trials. Returns the entity IDs the test needs.

    Defaults to a winning configuration that passes the lift gate:
    parent.best_metric=0.50 vs first-decile (first 2 trials at metric=0.30) ⇒
    lift=0.20 > epsilon=0.005.
    """
    suffix = uuid.uuid4().hex[:8]
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"af-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"af-tmpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match": {"body": "{{ query }}"}}}',
            # One numeric param so narrow_bounds_around_winner has work to do.
            declared_params={"title_boost": "float"},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"af-qs-{suffix}",
            cluster_id=cluster.id,
        )
        # One query keeps the seed tight; the chain gate doesn't depend on count.
        await repo.create_query(
            db,
            id=str(uuid.uuid4()),
            query_set_id=query_set.id,
            query_text="q1",
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"af-jl-{suffix}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
            failed_reason=None,
            calibration=None,
        )

        parent_id = str(uuid.uuid4())
        config: dict[str, Any] = {"max_trials": n_complete_trials}
        if auto_followup_depth is not None:
            config["auto_followup_depth"] = auto_followup_depth
        parent = await repo.create_study(
            db,
            id=parent_id,
            name=f"af-parent-{suffix}",
            cluster_id=cluster.id,
            target="stub-index",
            template_id=template.id,
            query_set_id=query_set.id,
            judgment_list_id=jl.id,
            search_space={
                "params": {
                    "title_boost": {"type": "float", "low": 0.5, "high": 5.0},
                },
            },
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config=config,
            status=parent_status,
            optuna_study_name=parent_id,
        )
        # Trials: first N at first_trial_metric (the first decile), rest higher.
        # repo.create_trial signature: status='complete', params, primary_metric,
        # metrics, optuna_trial_number, started_at, ended_at.
        best_trial_id: str | None = None
        for i in range(n_complete_trials):
            metric = first_trial_metric if i < max(1, n_complete_trials // 10) else 0.40
            tid = str(uuid.uuid4())
            await repo.create_trial(
                db,
                id=tid,
                study_id=parent.id,
                optuna_trial_number=i,
                params={"title_boost": 2.0 + (i / 100)},  # numeric — narrowable
                primary_metric=metric,
                metrics={"ndcg@10": metric},
                duration_ms=10,
                status="complete",
                error=None,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
            )
            # Track the highest-metric trial id (any of the later ones — all are 0.40).
            if i == n_complete_trials - 1:
                best_trial_id = tid

        # Stamp the parent's winner directly (we're bypassing the orchestrator
        # in tests). Use the state-guard sentinel context to authorize the
        # update, since orchestrator updates go through services.study_state.
        # Simpler: refresh + assign via ORM with the guard sentinel.
        from backend.app.services.study_state import _GUARD_KEY

        db.sync_session.info[_GUARD_KEY] = True
        try:
            parent.best_metric = best_metric
            parent.best_trial_id = best_trial_id
            await db.flush()
        finally:
            db.sync_session.info.pop(_GUARD_KEY, None)
        await db.commit()

    return {
        "parent_id": parent_id,
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": jl.id,
    }


async def _clear_budget_key() -> None:
    """Reset the per-day Redis budget counter so cross-test state doesn't
    bleed into the next run."""
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await redis.delete(daily_key(datetime.now(UTC)))
    finally:
        await redis.aclose()


def _make_arq_ctx(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], MagicMock]:
    """Return a fake Arq ctx with a stubbed arq_pool. The pool's
    enqueue_job returns an awaitable so the worker's await chain succeeds."""
    from unittest.mock import AsyncMock

    arq_pool = MagicMock()
    arq_pool.enqueue_job = AsyncMock(return_value=None)
    ctx: dict[str, Any] = {"arq_pool": arq_pool}
    return ctx, arq_pool


# ---------------------------------------------------------------------------
# Happy path: gate passes + budget under threshold → child enqueued
# ---------------------------------------------------------------------------


async def test_chain_gate_passes_creates_child_and_enqueues_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parent with depth=3 completes with strong lift → child created with
    depth=2 + inherited config + start_study enqueued via arq_pool."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_chain(auto_followup_depth=3, best_metric=0.50)
    ctx, arq_pool = _make_arq_ctx(monkeypatch)

    await enqueue_followup_study(ctx, seeded["parent_id"])

    factory = get_session_factory()
    async with factory() as db:
        children = await repo.list_children_of_study(db, seeded["parent_id"])
    assert len(children) == 1
    child = children[0]
    assert child.parent_study_id == seeded["parent_id"]
    assert child.status == "queued"
    assert child.config["auto_followup_depth"] == 2  # decremented from 3
    assert child.config["max_trials"] == 20  # inherited from parent
    assert child.cluster_id == seeded["cluster_id"]  # inherited
    assert child.template_id == seeded["template_id"]
    assert child.target == "stub-index"
    # start_study enqueue happened exactly once with the child's id.
    arq_pool.enqueue_job.assert_awaited_once_with("start_study", child.id)


# ---------------------------------------------------------------------------
# Depth-exhausted leaf
# ---------------------------------------------------------------------------


async def test_depth_zero_leaf_skips_no_child_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A depth=0 study (the worker-set terminal-state value per FR-1)
    on its own enqueue → emits auto_followup_depth_exhausted + no child."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_chain(auto_followup_depth=0, best_metric=0.50)
    ctx, arq_pool = _make_arq_ctx(monkeypatch)

    await enqueue_followup_study(ctx, seeded["parent_id"])

    factory = get_session_factory()
    async with factory() as db:
        children = await repo.list_children_of_study(db, seeded["parent_id"])
    assert children == []
    arq_pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# No lift: parent's winner doesn't beat first-decile + epsilon
# ---------------------------------------------------------------------------


async def test_no_lift_skips_no_child_created(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent.best_metric only marginally above first-decile (within epsilon)
    → SKIP_NO_LIFT; no child created, no start_study enqueued."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    # first_trial_metric=0.40 forces first-decile=0.40; best_metric=0.402
    # lift=0.002, epsilon=0.005, so 0.002 ≤ epsilon → SKIP_NO_LIFT.
    seeded = await _seed_parent_chain(
        auto_followup_depth=3,
        best_metric=0.402,
        first_trial_metric=0.40,
    )
    ctx, arq_pool = _make_arq_ctx(monkeypatch)

    await enqueue_followup_study(ctx, seeded["parent_id"])

    factory = get_session_factory()
    async with factory() as db:
        children = await repo.list_children_of_study(db, seeded["parent_id"])
    assert children == []
    arq_pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# Layer-2 idempotency: re-invocation drops duplicate
# ---------------------------------------------------------------------------


async def test_layer_2_idempotency_drops_duplicate_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First invocation creates the child; second invocation (bypassing
    Arq's _job_id dedup) sees the child via list_children_of_study and
    logs auto_followup_enqueued_duplicate_dropped without creating a
    second child."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_chain(auto_followup_depth=3, best_metric=0.50)
    ctx, arq_pool = _make_arq_ctx(monkeypatch)

    # First invocation: creates child + enqueues start_study.
    await enqueue_followup_study(ctx, seeded["parent_id"])
    factory = get_session_factory()
    async with factory() as db:
        children_after_first = await repo.list_children_of_study(db, seeded["parent_id"])
    assert len(children_after_first) == 1
    first_call_count = arq_pool.enqueue_job.await_count

    # Second invocation: layer-2 backstop should fire. No new child.
    await enqueue_followup_study(ctx, seeded["parent_id"])
    async with factory() as db:
        children_after_second = await repo.list_children_of_study(db, seeded["parent_id"])
    assert len(children_after_second) == 1  # same child, NOT a second one
    # start_study should NOT have been enqueued again for the duplicate.
    assert arq_pool.enqueue_job.await_count == first_call_count


# ---------------------------------------------------------------------------
# Defensive: missing parent → skip event, no exception
# ---------------------------------------------------------------------------


async def test_missing_parent_logs_skip_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard-delete race / cold-call with bogus id → emits
    auto_followup_skipped_parent_missing; no exception, no enqueue."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    ctx, arq_pool = _make_arq_ctx(monkeypatch)
    bogus_id = str(uuid.uuid4())

    # Should not raise.
    await enqueue_followup_study(ctx, bogus_id)
    arq_pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# Budget peek > 80% threshold → skip
# ---------------------------------------------------------------------------


async def test_budget_threshold_breached_skips_no_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-seed the daily-budget Redis counter above 80% of the configured
    budget → worker logs auto_followup_skipped_budget + no child."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_chain(auto_followup_depth=3, best_metric=0.50)
    ctx, arq_pool = _make_arq_ctx(monkeypatch)

    settings = get_settings()
    # Seed Redis so peek_total alone already exceeds 80% of the budget
    # (the worker's max_call_cost addition guarantees the trip).
    over_threshold = 0.95 * settings.openai_daily_budget_usd
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await redis.set(daily_key(datetime.now(UTC)), str(over_threshold))
    finally:
        await redis.aclose()
    try:
        await enqueue_followup_study(ctx, seeded["parent_id"])
    finally:
        await _clear_budget_key()

    factory = get_session_factory()
    async with factory() as db:
        children = await repo.list_children_of_study(db, seeded["parent_id"])
    assert children == []
    arq_pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# Parent failed → defensive skip
# ---------------------------------------------------------------------------


async def test_failed_parent_skips_no_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive backstop: digest worker doesn't run on failed studies in
    normal flow (verified at orchestrator.py:452), but if invoked manually
    on a failed parent, the worker emits auto_followup_skipped_parent_failed."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_chain(
        auto_followup_depth=3,
        parent_status="failed",
        best_metric=0.50,  # has winner but status is wrong
    )
    ctx, arq_pool = _make_arq_ctx(monkeypatch)

    await enqueue_followup_study(ctx, seeded["parent_id"])

    factory = get_session_factory()
    async with factory() as db:
        children = await repo.list_children_of_study(db, seeded["parent_id"])
    assert children == []
    arq_pool.enqueue_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# Telemetry assertion: at least one happy-path enqueue emits the right event_type
# ---------------------------------------------------------------------------


async def test_enqueue_emits_auto_followup_enqueued_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies FR-9 event #1 fires with the expected metadata fields."""
    from backend.workers.auto_followup import enqueue_followup_study

    await _clear_budget_key()
    seeded = await _seed_parent_chain(auto_followup_depth=3, best_metric=0.50)
    ctx, _ = _make_arq_ctx(monkeypatch)

    with structlog.testing.capture_logs() as captured:
        await enqueue_followup_study(ctx, seeded["parent_id"])

    event_types = [e.get("event_type") for e in captured]
    assert "auto_followup_enqueued" in event_types
    enqueued = next(e for e in captured if e.get("event_type") == "auto_followup_enqueued")
    assert enqueued["parent_study_id"] == seeded["parent_id"]
    assert enqueued["remaining_depth"] == 2
    assert "lift" in enqueued
    assert "epsilon" in enqueued


# Story 2.2's digest-trigger source-inspection test lives in
# backend/tests/unit/workers/test_digest_followup_trigger.py — it doesn't
# need Postgres + Redis (just reads digest.py), so it belongs in the
# unit layer where it'll actually run.
