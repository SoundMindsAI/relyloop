"""Integration tests for the Phase 2 orchestrator (Story 2.1).

Covers AC-1, AC-2, AC-5, AC-6, AC-10 against the integration-test Postgres.

The tests drive ``start_study`` directly (not via Arq) using a
:class:`_InProcessPool` stand-in for ``ArqRedis`` that synchronously
spawns ``run_trial`` tasks against the same Optuna storage. This makes
the lifecycle deterministic — no Redis dependency, no Arq retry timing.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app.adapters.errors import ClusterUnreachableError
from backend.app.adapters.protocol import NativeQuery, ScoredHit
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage
from backend.app.services import study_state
from backend.tests._log_helpers import RecordingLogger
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.handbuilt_qrels import (
    build_hits_response,
    build_zero_scoring_hits_response,
)
from backend.tests.integration.fixtures.stub_adapter import StubAdapter
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

    async def enqueue_job(self, func_name: str, *args: Any, **_kwargs: Any) -> object:
        self.enqueued.append((func_name, args))
        if func_name == "run_trial":
            from backend.workers.trials import run_trial

            task = asyncio.create_task(run_trial({"optuna_storage": self._storage}, *args))
            self.run_trial_tasks.append(task)
        elif func_name == "run_baseline_trial":
            # feat_study_baseline_trial Story 1.7: orchestrator enqueues
            # run_baseline_trial before the Optuna loop. Dispatch inline
            # so the wait helpers can observe a terminal trial row.
            from backend.workers.baseline import run_baseline_trial

            task = asyncio.create_task(run_baseline_trial({}, *args))
            self.run_trial_tasks.append(task)
        # Return a non-None sentinel so the orchestrator's BaselineEnqueueResult
        # treats this as kind='enqueued' rather than 'deduped'.
        return object()

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
    original_baseline_floor = orchestrator._BASELINE_WAIT_FLOOR_S
    original_baseline_margin = orchestrator._BASELINE_WAIT_MARGIN_S
    orchestrator._REPLENISH_TICK_S = tick_s
    # feat_study_baseline_trial: cap the baseline-phase wait at ~2s in
    # tests (production default 60s minimum is too slow for the
    # 30s-test-timeout test_study_cancel test).
    orchestrator._BASELINE_WAIT_FLOOR_S = 2.0
    orchestrator._BASELINE_WAIT_MARGIN_S = 1.0
    storage = pool._storage
    ctx: dict[str, Any] = {"optuna_storage": storage, "arq_pool": pool}
    task = asyncio.create_task(orchestrator.start_study(ctx, fixture.study_id))
    try:
        yield task
    finally:
        orchestrator._REPLENISH_TICK_S = original_tick
        orchestrator._BASELINE_WAIT_FLOOR_S = original_baseline_floor
        orchestrator._BASELINE_WAIT_MARGIN_S = original_baseline_margin
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


async def test_ac10_trials_endpoint_returns_sorted_by_primary_metric_desc(
    monkeypatch: pytest.MonkeyPatch,
    async_client: httpx.AsyncClient,
) -> None:
    """AC-10 HTTP-level: ``GET /api/v1/studies/{id}/trials?sort=primary_metric_desc``
    returns trials in descending primary_metric order after a happy-path
    study completes. The repo-layer assertion lives in
    :func:`test_ac10_trials_sort_by_primary_metric_descending`; this test
    additionally exercises the FastAPI router + response serialization
    layer (Story 3.4 / FR-6 endpoint contract)."""
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

        resp = await async_client.get(
            f"/api/v1/studies/{fixture.study_id}/trials?sort=primary_metric_desc&limit=10"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) >= 1
        metrics = [t["primary_metric"] for t in data]
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


# ---------------------------------------------------------------------------
# feat_orchestrator_zero_streak_abort — mid-flight zero-metric streak guard
# ---------------------------------------------------------------------------


def _install_stub_adapter_with(monkeypatch: pytest.MonkeyPatch, stub: StubAdapter) -> StubAdapter:
    """Install a pre-built ``StubAdapter`` instance.

    Mirrors :func:`install_stub_adapter` but accepts a fully-built stub so
    callers can configure custom per-call behavior (zero-scoring responses,
    barrier-gated outliers, alternating raises).
    """
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _cluster: stub)
    return stub


class _OutlierStub(StubAdapter):
    """``StubAdapter`` variant that returns a non-zero ``build_hits_response`` on
    the Nth ``search_batch`` call and a zero-scoring response on every other
    call. Optionally waits on an ``asyncio.Event`` after the 20th call to
    deterministically pause the orchestrator at the terminal-20 snapshot
    (per AC-2 barrier-stub pattern)."""

    def __init__(
        self,
        query_ids: list[str],
        outlier_call_index: int,
        barrier: asyncio.Event | None = None,
        barrier_after_call: int | None = None,
    ) -> None:
        super().__init__(engine_type="elasticsearch", search_batch_response={})
        self._query_ids = query_ids
        self._outlier_call_index = outlier_call_index
        self._barrier = barrier
        self._barrier_after_call = barrier_after_call

    async def search_batch(
        self,
        target: str,
        queries: Sequence[NativeQuery],
        top_k: int,
        *,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]:
        call_index = len(self.search_batch_calls)
        self.search_batch_calls.append(
            {
                "target": target,
                "n_queries": len(queries),
                "top_k": top_k,
                "timeout": timeout,
            }
        )
        if self._barrier is not None and self._barrier_after_call is not None:
            if call_index >= self._barrier_after_call:
                await self._barrier.wait()
        if call_index == self._outlier_call_index:
            response = build_hits_response(self._query_ids)
        else:
            response = build_zero_scoring_hits_response(self._query_ids)
        # search_batch_response is keyed by query_id; the worker passes
        # NativeQuery objects whose query_id matches our handbuilt set.
        return {q.query_id: response.get(q.query_id, []) for q in queries}


class _AlternatingStub(StubAdapter):
    """``StubAdapter`` variant that alternates: even calls return zero-scoring
    hits, odd calls raise ``ClusterUnreachableError``. Used by AC-3 to verify
    that neither guard fires when failures interleave with complete-zero
    trials at the streak-threshold cadence."""

    def __init__(self, query_ids: list[str]) -> None:
        super().__init__(engine_type="elasticsearch", search_batch_response={})
        self._query_ids = query_ids

    async def search_batch(
        self,
        target: str,
        queries: Sequence[NativeQuery],
        top_k: int,
        *,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]:
        call_index = len(self.search_batch_calls)
        self.search_batch_calls.append(
            {
                "target": target,
                "n_queries": len(queries),
                "top_k": top_k,
                "timeout": timeout,
            }
        )
        if call_index % 2 == 1:
            raise ClusterUnreachableError("alternating stub: failure call")
        response = build_zero_scoring_hits_response(self._query_ids)
        return {q.query_id: response.get(q.query_id, []) for q in queries}


_ZERO_STREAK_FAILED_REASON = (
    "no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"
)


async def test_zero_streak_20_consecutive_zeros_fails_the_study(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1 + FR-3 structlog contract: 20 consecutive ``primary_metric=0.0``
    trials abort the study with the exact failed_reason string and emit
    ``event_type='stop_condition_fired', reason='no_signal'`` at WARNING."""
    fixture = await seed_study(max_trials=25, parallelism=1)
    try:
        stub = StubAdapter(
            engine_type="elasticsearch",
            search_batch_response=build_zero_scoring_hits_response(fixture.query_ids),
        )
        _install_stub_adapter_with(monkeypatch, stub)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        recording_logger = RecordingLogger()
        monkeypatch.setattr("backend.workers.orchestrator.logger", recording_logger)

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
            assert study.failed_reason == _ZERO_STREAK_FAILED_REASON
            summary = await repo.aggregate_trials_summary(db, fixture.study_id)
            assert summary.complete >= 20
            assert summary.failed == 0
            assert summary.pruned == 0

        warnings = recording_logger.find(level="warning", event_type="stop_condition_fired")
        assert any(
            w.get("reason") == "no_signal" and w.get("study_id") == fixture.study_id
            for w in warnings
        ), f"expected no_signal warning; got {warnings!r}"
    finally:
        await cleanup_study(fixture)


async def test_zero_streak_nonzero_outlier_in_recent_window_does_not_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-2 boundary: a non-zero scoring trial inside the recent-20 window
    keeps the helper at False. Uses a barrier-stub to deterministically
    snapshot at terminal-20 before letting the orchestrator run to
    completion via ``max_trials_reached``."""
    fixture = await seed_study(max_trials=30, parallelism=1)
    try:
        barrier = asyncio.Event()
        stub = _OutlierStub(
            query_ids=list(fixture.query_ids),
            outlier_call_index=10,
            barrier=barrier,
            barrier_after_call=20,
        )
        _install_stub_adapter_with(monkeypatch, stub)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        async with _running_orchestrator(fixture, pool):
            # (a) Wait until exactly 20 trials have terminated; fail-fast if
            # the orchestrator advances past 20 before we snapshot (the
            # barrier should prevent this, but the assertion is a defensive
            # backstop).
            factory = get_session_factory()
            deadline = asyncio.get_event_loop().time() + 60.0
            while asyncio.get_event_loop().time() < deadline:
                async with factory() as db:
                    summary = await repo.aggregate_trials_summary(db, fixture.study_id)
                    terminal = summary.complete + summary.failed + summary.pruned
                    if terminal > 20:
                        pytest.fail(f"snapshot missed — terminal advanced past 20 (got {terminal})")
                    if terminal == 20:
                        break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("orchestrator never reached terminal=20 within 60s")

            # Snapshot assertion: the helper returns False because the
            # outlier at optuna_trial_number=10 is in the recent-20 window.
            from backend.workers.orchestrator import _last_n_all_zero

            async with factory() as db:
                snapshot = await _last_n_all_zero(db, fixture.study_id, n=20)
                assert snapshot is False
                study = await repo.get_study(db, fixture.study_id)
                assert study is not None
                assert study.status == "running"

            # (b) Release the barrier and run to completion. With the
            # outlier at trial 10 and max_trials=30, the recent-20 window
            # always includes the outlier, so the zero-streak never fires;
            # the study completes via max_trials_reached.
            barrier.set()
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "completed", timeout=60.0),
                timeout=60.0,
            )

            async with factory() as db:
                study = await repo.get_study(db, fixture.study_id)
                assert study is not None
                assert study.status == "completed"
                assert study.failed_reason is None
                assert study.best_metric is not None
                assert study.best_metric > 0.0
    finally:
        barrier.set()  # defensive — release any waiters before teardown
        await cleanup_study(fixture)


async def test_zero_streak_interleaved_failures_does_not_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3: alternating zero-metric complete + failed trials — neither
    streak reaches its threshold. Study terminates via
    ``max_trials_reached`` with ``best_metric=0.0``."""
    fixture = await seed_study(max_trials=24, parallelism=1)
    try:
        stub = _AlternatingStub(query_ids=list(fixture.query_ids))
        _install_stub_adapter_with(monkeypatch, stub)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        recording_logger = RecordingLogger()
        monkeypatch.setattr("backend.workers.orchestrator.logger", recording_logger)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        async with _running_orchestrator(fixture, pool):
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "completed", timeout=60.0),
                timeout=60.0,
            )

        factory = get_session_factory()
        async with factory() as db:
            study = await repo.get_study(db, fixture.study_id)
            assert study is not None
            assert study.status == "completed"
            assert study.failed_reason is None
            assert study.best_metric == 0.0

        # `max_trials_reached` is emitted by `_stop()` at INFO; the
        # streak-abort paths (`consecutive_failures`, `no_signal`) emit at
        # WARNING. AC-3 asserts neither streak fired → no WARNING-level
        # stop-condition record. The INFO `max_trials_reached` record is
        # expected and asserted as the terminating reason.
        warnings = recording_logger.find(level="warning", event_type="stop_condition_fired")
        assert warnings == [], (
            f"no streak-abort should have fired; got WARNING-level "
            f"stop_condition_fired records: {warnings!r}"
        )
        infos = recording_logger.find(level="info", event_type="stop_condition_fired")
        assert any(i.get("reason") == "max_trials_reached" for i in infos), (
            f"expected an INFO stop_condition_fired with reason='max_trials_reached'; got {infos!r}"
        )
    finally:
        await cleanup_study(fixture)


async def test_zero_streak_precedence_failure_streak_runs_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5 / FR-4: when both ``_last_n_all_failed`` and ``_last_n_all_zero``
    return True, the failure-streak branch returns first and the zero-streak
    helper is never invoked."""
    fixture = await seed_study(max_trials=30, parallelism=1)
    try:
        install_stub_adapter(monkeypatch, fixture.query_ids)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        zero_streak_spy = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "backend.workers.orchestrator._last_n_all_failed",
            AsyncMock(return_value=True),
        )
        monkeypatch.setattr("backend.workers.orchestrator._last_n_all_zero", zero_streak_spy)

        recording_logger = RecordingLogger()
        monkeypatch.setattr("backend.workers.orchestrator.logger", recording_logger)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        async with _running_orchestrator(fixture, pool):
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "failed", timeout=30.0),
                timeout=30.0,
            )

        factory = get_session_factory()
        async with factory() as db:
            study = await repo.get_study(db, fixture.study_id)
            assert study is not None
            assert study.status == "failed"
            assert study.failed_reason == "5 consecutive trial failures"

        assert zero_streak_spy.call_count == 0, (
            "zero-streak helper was invoked despite failure-streak firing first; "
            "FR-4 precedence violated"
        )

        warnings = recording_logger.find(level="warning", event_type="stop_condition_fired")
        assert any(w.get("reason") == "consecutive_failures" for w in warnings), (
            f"expected consecutive_failures warning; got {warnings!r}"
        )
    finally:
        await cleanup_study(fixture)


async def test_zero_streak_cancel_race_during_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-4: ``InvalidStateTransition`` from ``fail_study`` (simulating an
    operator cancel that won the race) exits the orchestrator cleanly with
    an INFO ``orchestrator_race_lost`` log carrying
    ``attempted_reason='no_signal'`` — no exception escapes the task."""
    fixture = await seed_study(max_trials=30, parallelism=1)
    try:
        install_stub_adapter(monkeypatch, fixture.query_ids)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        monkeypatch.setattr(
            "backend.workers.orchestrator._last_n_all_zero",
            AsyncMock(return_value=True),
        )
        monkeypatch.setattr(
            "backend.workers.orchestrator.study_state.fail_study",
            AsyncMock(side_effect=study_state.InvalidStateTransition("cancelled-mid-flight")),
        )

        recording_logger = RecordingLogger()
        monkeypatch.setattr("backend.workers.orchestrator.logger", recording_logger)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        # Manually drive start_study so we can await the task and confirm
        # no exception escapes (the _running_orchestrator context manager
        # cancels the task on exit; we want it to terminate cleanly via
        # the loop's `return`).
        from backend.workers import orchestrator

        ctx: dict[str, Any] = {"optuna_storage": storage, "arq_pool": pool}
        # Speed up the polling tick so the test finishes quickly.
        original_tick = orchestrator._REPLENISH_TICK_S
        orchestrator._REPLENISH_TICK_S = 0.05
        try:
            await asyncio.wait_for(
                orchestrator.start_study(ctx, fixture.study_id),
                timeout=30.0,
            )
        finally:
            orchestrator._REPLENISH_TICK_S = original_tick

        race_logs = recording_logger.find(level="info", event_type="orchestrator_race_lost")
        assert any(
            r.get("attempted_reason") == "no_signal" and r.get("study_id") == fixture.study_id
            for r in race_logs
        ), f"expected no_signal race-lost log; got {race_logs!r}"
    finally:
        await cleanup_study(fixture)


# ---------------------------------------------------------------------------
# Helper-boundary matrix — FR-1 + FR-5
# ---------------------------------------------------------------------------


async def _seed_trials(
    study_id: str,
    rows: list[tuple[int, str, float | None]],
) -> None:
    """Insert hand-crafted trial rows for the boundary matrix.

    Each row is ``(optuna_trial_number, status, primary_metric)``.
    """
    import uuid_utils

    factory = get_session_factory()
    async with factory() as db:
        for optuna_trial_number, status, primary_metric in rows:
            await repo.create_trial(
                db,
                id=str(uuid_utils.uuid7()),
                study_id=study_id,
                optuna_trial_number=optuna_trial_number,
                params={},
                primary_metric=primary_metric,
                metrics={},
                duration_ms=None,
                status=status,
                error=None,
                started_at=None,
                ended_at=None,
            )
        await db.commit()


_BOUNDARY_CASES = [
    # (label, [(optuna_trial_number, status, primary_metric), ...], expected)
    ("zero_trials", [], False),
    (
        "nineteen_zeros",
        [(i, "complete", 0.0) for i in range(19)],
        False,
    ),
    (
        "twenty_zeros",
        [(i, "complete", 0.0) for i in range(20)],
        True,
    ),
    (
        "nonzero_at_ten",
        [(i, "complete", 0.5 if i == 10 else 0.0) for i in range(20)],
        False,
    ),
    (
        "failed_at_ten",
        [(i, "failed" if i == 10 else "complete", None if i == 10 else 0.0) for i in range(20)],
        False,
    ),
    (
        "pruned_at_ten",
        [(i, "pruned" if i == 10 else "complete", None if i == 10 else 0.0) for i in range(20)],
        False,
    ),
    (
        "null_metric_at_ten",
        [(i, "complete", None if i == 10 else 0.0) for i in range(20)],
        False,
    ),
    (
        "outliers_outside_window",
        # trials 0-4 are non-zero (older); trials 5-24 are zero (recent 20)
        [(i, "complete", 0.5) for i in range(5)] + [(i, "complete", 0.0) for i in range(5, 25)],
        True,
    ),
]


@pytest.mark.parametrize(
    "label,rows,expected",
    _BOUNDARY_CASES,
    ids=[c[0] for c in _BOUNDARY_CASES],
)
async def test_last_n_all_zero_helper_boundary_cases(
    label: str,
    rows: list[tuple[int, str, float | None]],
    expected: bool,
) -> None:
    """FR-1 + FR-5: parameterized matrix of helper boundary semantics. Each
    sub-case uses a fresh study (no shared state between cases — the
    "recent n on this study" contract requires per-case isolation)."""
    del label  # used by pytest for the parametrize id; not needed in body
    fixture = await seed_study(max_trials=100, parallelism=1, status="queued")
    try:
        if rows:
            await _seed_trials(fixture.study_id, rows)

        from backend.workers.orchestrator import _last_n_all_zero

        factory = get_session_factory()
        async with factory() as db:
            result = await _last_n_all_zero(db, fixture.study_id, n=20)
            assert result is expected, (
                f"_last_n_all_zero returned {result}, expected {expected} "
                f"for boundary case with {len(rows)} rows"
            )
    finally:
        await cleanup_study(fixture)
