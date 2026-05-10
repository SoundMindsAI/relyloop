"""Integration tests for the Phase 2 orchestrator (Story 2.1).

Covers AC-1, AC-2, AC-5, AC-6, AC-10 against the integration-test Postgres.

The tests drive ``start_study`` directly (not via Arq) using a
:class:`_InProcessPool` stand-in for ``ArqRedis`` that synchronously
spawns ``run_trial`` tasks against the same Optuna storage. This makes
the lifecycle deterministic — no Redis dependency, no Arq retry timing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.app.adapters.errors import ClusterUnreachableError
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage
from backend.app.services import study_state
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.study_factories import (
    StudyFixture,
    cleanup_study,
    install_stub_adapter,
    monkeypatch_qrels,
    seed_study,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


# ---------------------------------------------------------------------------
# In-process Arq pool stub
# ---------------------------------------------------------------------------


class _InProcessPool:
    """Stand-in for ``arq.connections.ArqRedis`` that dispatches inline.

    Captures every ``enqueue_job`` call; for ``run_trial`` it spawns the
    Arq job inline against the same Optuna storage. ``generate_digest``
    is recorded but not invoked (the orchestrator's atomic
    pending-proposal INSERT is the durable handoff under test).
    """

    def __init__(self, storage: Any) -> None:
        self._storage = storage
        self.run_trial_tasks: list[asyncio.Task[None]] = []
        self.enqueued: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, func_name: str, *args: Any, **_kwargs: Any) -> None:
        self.enqueued.append((func_name, args))
        if func_name == "run_trial":
            from backend.workers.trials import run_trial

            task = asyncio.create_task(run_trial({"optuna_storage": self._storage}, *args))
            self.run_trial_tasks.append(task)

    async def close(self) -> None:
        for task in self.run_trial_tasks:
            if not task.done():
                task.cancel()


@asynccontextmanager
async def _running_orchestrator(
    fixture: StudyFixture, pool: _InProcessPool, *, tick_s: float = 0.05
) -> AsyncIterator[asyncio.Task[None]]:
    """Start the orchestrator as a background task with a sped-up tick.

    Cancels the task on exit; ignores ``CancelledError``.
    """
    from backend.workers import orchestrator

    # Speed up the polling loop for tests.
    original_tick = orchestrator._REPLENISH_TICK_S
    orchestrator._REPLENISH_TICK_S = tick_s
    storage = pool._storage
    ctx: dict[str, Any] = {"optuna_storage": storage, "arq_pool": pool}
    task = asyncio.create_task(orchestrator.start_study(ctx, fixture.study_id))
    try:
        yield task
    finally:
        orchestrator._REPLENISH_TICK_S = original_tick
        if not task.done():
            task.cancel()
            with pytest.raises((asyncio.CancelledError, BaseException)):
                await task
        # Drain any leftover in-flight run_trial tasks.
        for t in pool.run_trial_tasks:
            if not t.done():
                t.cancel()
        # Give them a moment to settle without raising into the test body.
        await asyncio.gather(*pool.run_trial_tasks, return_exceptions=True)


async def _wait_for_status(study_id: str, *expected: str, timeout: float = 30.0) -> str:
    """Poll the studies row until status ∈ expected (or timeout)."""
    factory = get_session_factory()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with factory() as db:
            row = await repo.get_study(db, study_id)
            if row is not None and row.status in expected:
                return row.status
        await asyncio.sleep(0.1)
    raise AssertionError(f"study {study_id} did not reach any of {expected} within {timeout}s")


# ---------------------------------------------------------------------------
# AC-1 — happy path: study completes naturally
# ---------------------------------------------------------------------------


async def test_ac1_study_completes_with_best_metric_populated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: orchestrator runs a study to completion + denormalizes best_metric."""
    fixture = await seed_study(max_trials=4, parallelism=2)
    try:
        install_stub_adapter(monkeypatch, fixture.query_ids)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        async with _running_orchestrator(fixture, pool):
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "completed", timeout=60.0),
                timeout=60.0,
            )

        # Verify denormalization + trials accumulated.
        factory = get_session_factory()
        async with factory() as db:
            study = await repo.get_study(db, fixture.study_id)
            assert study is not None
            assert study.status == "completed"
            assert study.best_metric is not None
            assert study.best_trial_id is not None
            assert study.completed_at is not None
            summary = await repo.aggregate_trials_summary(db, fixture.study_id)
            assert summary.complete == 4
            # Durable digest handoff (C3-F1): pending proposal row exists.
            from sqlalchemy import select

            from backend.app.db.models import Proposal

            pending = (
                await db.execute(
                    select(Proposal)
                    .where(Proposal.study_id == fixture.study_id)
                    .where(Proposal.status == "pending")
                )
            ).scalar_one_or_none()
            assert pending is not None
            assert pending.cluster_id == fixture.cluster_id
            assert pending.template_id == fixture.template_id
    finally:
        await cleanup_study(fixture)


# ---------------------------------------------------------------------------
# AC-2 — time budget terminates a long study
# ---------------------------------------------------------------------------


async def test_ac2_time_budget_exceeded_stops_the_study(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-2: a study with ``time_budget_min=0.05`` (3s) completes with
    partial trial coverage."""
    fixture = await seed_study(
        max_trials=10_000,
        parallelism=2,
        time_budget_min=0.05,
    )
    try:
        install_stub_adapter(monkeypatch, fixture.query_ids)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        async with _running_orchestrator(fixture, pool):
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "completed", timeout=30.0),
                timeout=30.0,
            )

        factory = get_session_factory()
        async with factory() as db:
            summary = await repo.aggregate_trials_summary(db, fixture.study_id)
            # Spec AC-2: 0 < complete < max_trials.
            assert summary.complete > 0
            assert summary.complete < 10_000
    finally:
        await cleanup_study(fixture)


# ---------------------------------------------------------------------------
# AC-5 — 5 consecutive trial failures fail the study
# ---------------------------------------------------------------------------


async def test_ac5_five_consecutive_failures_fail_the_study(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5: every trial fails (cluster unreachable) → study transitions
    to ``failed`` with the documented ``failed_reason``."""
    fixture = await seed_study(max_trials=20, parallelism=2)
    try:
        # Adapter raises on every search call.
        install_stub_adapter(
            monkeypatch,
            fixture.query_ids,
            raise_on_search=ClusterUnreachableError("stub cluster unreachable"),
        )
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        async with _running_orchestrator(fixture, pool):
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "failed", timeout=60.0),
                timeout=60.0,
            )

        factory = get_session_factory()
        async with factory() as db:
            study = await repo.get_study(db, fixture.study_id)
            assert study is not None
            assert study.status == "failed"
            assert study.failed_reason == "5 consecutive trial failures"
            summary = await repo.aggregate_trials_summary(db, fixture.study_id)
            assert summary.failed >= 5
            assert summary.complete == 0
    finally:
        await cleanup_study(fixture)


# ---------------------------------------------------------------------------
# AC-6 — direct status mutation raises StudyStateProtectionError
# ---------------------------------------------------------------------------


async def test_ac6_direct_status_mutation_outside_service_layer_is_blocked() -> None:
    """AC-6: writing ``Study.status`` outside the service layer raises
    :exc:`StudyStateProtectionError` on flush."""
    fixture = await seed_study(max_trials=5, parallelism=2)
    try:
        factory = get_session_factory()
        async with factory() as db:
            study = await repo.get_study(db, fixture.study_id)
            assert study is not None
            study.status = "completed"
            with pytest.raises(study_state.StudyStateProtectionError):
                await db.flush()
            await db.rollback()
    finally:
        await cleanup_study(fixture)


# ---------------------------------------------------------------------------
# AC-10 — trials sorted by primary_metric descending
# ---------------------------------------------------------------------------


async def test_ac10_trials_sort_by_primary_metric_descending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-10: ``list_trials_paginated(sort_key='primary_metric_desc')``
    returns trials in descending primary-metric order after a happy-path
    study completes."""
    fixture = await seed_study(max_trials=5, parallelism=2)
    try:
        install_stub_adapter(monkeypatch, fixture.query_ids)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        async with _running_orchestrator(fixture, pool):
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "completed", timeout=60.0),
                timeout=60.0,
            )

        factory = get_session_factory()
        async with factory() as db:
            top = await repo.list_trials_paginated(
                db,
                fixture.study_id,
                limit=10,
                sort_key="primary_metric_desc",
            )
            assert len(top) >= 1
            # Descending order — None always last under nulls_last.
            metrics = [t.primary_metric for t in top]
            non_null = [m for m in metrics if m is not None]
            assert non_null == sorted(non_null, reverse=True)
    finally:
        await cleanup_study(fixture)


# ---------------------------------------------------------------------------
# Cancel-race: orchestrator stop loses to user cancel — verifies that
# _stop()'s try/except InvalidStateTransition path is hit and the
# orchestrator exits silently.
# ---------------------------------------------------------------------------


async def test_stop_loses_cancel_race_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §11: when a user cancel commits between the orchestrator's
    status read and its ``complete_study`` call, the orchestrator silently
    swallows the ``InvalidStateTransition`` and exits."""
    from backend.workers import orchestrator

    fixture = await seed_study(max_trials=3, parallelism=2)
    try:
        # Transition to running first so cancel_study is legal.
        factory = get_session_factory()
        async with factory() as db:
            await study_state.start_study(db, fixture.study_id)
            await db.commit()

        # Pre-cancel the study so complete_study will raise.
        async with factory() as db:
            await study_state.cancel_study(db, fixture.study_id)
            await db.commit()

        # Build a tiny TrialsSummary stand-in and call _stop directly.
        from backend.app.db.repo.trial import TrialsSummary

        summary = TrialsSummary(
            total=3,
            complete=3,
            failed=0,
            pruned=0,
            best_primary_metric=0.5,
            best_trial_id=None,
        )

        # _stop should swallow the InvalidStateTransition and not re-raise.
        fake_pool = AsyncMock()
        async with factory() as db:
            await orchestrator._stop(
                db,
                fake_pool,
                fixture.study_id,
                summary,
                reason="max_trials_reached",
            )

        # Verify study is still cancelled (no transition to completed).
        async with factory() as db:
            study = await repo.get_study(db, fixture.study_id)
            assert study is not None
            assert study.status == "cancelled"
        # Verify no proposal row was created.
        from sqlalchemy import select

        from backend.app.db.models import Proposal

        async with factory() as db:
            pending = (
                await db.execute(select(Proposal).where(Proposal.study_id == fixture.study_id))
            ).scalar_one_or_none()
            assert pending is None
    finally:
        await cleanup_study(fixture)
