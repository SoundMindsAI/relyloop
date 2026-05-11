"""AC-4 — resume-after-restart sweep (Story 2.3, FR-5).

The full subprocess-driven Arq-worker SIGTERM + restart test is heavy
infrastructure (spawns the ``arq`` CLI in a child process, requires
Redis from the host). For MVP1 we test the contract at two levels
without spawning a worker subprocess:

1. **Sweep correctness** — :func:`backend.workers.all.on_startup` lists
   running studies and enqueues ``resume_study(study_id)`` against the
   provided Arq pool. Verified by seeding a ``status='running'`` study,
   calling ``on_startup(ctx)`` with a stub pool, and asserting the
   enqueue happened.
2. **Idempotent resume** — ``resume_study`` is a wrapper around
   ``start_study``; ``services.study_state.start_study`` is idempotent
   on an already-``running`` study (returns unchanged). Combined,
   resume picks up the loop without re-transitioning the row.

Together these cover the FR-5 / AC-4 contract surface that the
production worker exercises. A spawn-arq-subprocess test would catch
Arq-version-specific wiring regressions but is deferred to the operator
runbook (``docs/03_runbooks/study-lifecycle-debugging.md`` from Story
4.1).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.services import study_state
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.study_factories import (
    cleanup_study,
    seed_study,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


class _StubArqPool:
    """Captures every ``enqueue_job`` call without dispatching."""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, func_name: str, *args: Any, **_kwargs: Any) -> None:
        self.enqueued.append((func_name, args))

    async def close(self) -> None:
        pass


async def test_on_startup_resumes_every_running_study(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-5 / AC-4 sweep: on_startup enqueues resume_study for every
    running study."""
    from backend.workers import all as workers_all

    # Seed two studies — one running, one queued. Only the running one
    # should be resumed.
    running = await seed_study(max_trials=10, parallelism=2, status="running")
    queued = await seed_study(max_trials=10, parallelism=2, status="queued")
    try:
        # Stub create_pool so on_startup returns our deterministic pool.
        stub_pool = _StubArqPool()

        async def _fake_create_pool(_settings: Any) -> _StubArqPool:
            return stub_pool

        monkeypatch.setattr(workers_all, "create_pool", _fake_create_pool)

        # Stub the storage builder so on_startup doesn't actually touch
        # Optuna RDB — we're only verifying the resume sweep here.
        monkeypatch.setattr(
            workers_all,
            "build_storage",
            lambda _url: object(),
        )

        ctx: dict[str, Any] = {}
        await workers_all.on_startup(ctx)

        resume_calls = [args for (name, args) in stub_pool.enqueued if name == "resume_study"]
        resumed_ids = {call[0] for call in resume_calls}
        assert running.study_id in resumed_ids
        assert queued.study_id not in resumed_ids
        assert "optuna_storage" in ctx
        assert ctx["arq_pool"] is stub_pool
    finally:
        await cleanup_study(running)
        await cleanup_study(queued)


async def test_resume_study_idempotent_on_already_running() -> None:
    """``services.study_state.start_study`` is a no-op when called on an
    already-running study — the contract behind ``resume_study``'s
    correctness."""
    fixture = await seed_study(max_trials=10, parallelism=2, status="running")
    try:
        factory = get_session_factory()
        async with factory() as db:
            before = await repo.get_study(db, fixture.study_id)
            assert before is not None
            assert before.status == "running"
            started_before = before.started_at

            # Calling start_study on a running study must NOT raise + must
            # leave the row unchanged.
            study = await study_state.start_study(db, fixture.study_id)
            await db.commit()
            assert study.status == "running"
            assert study.started_at == started_before
    finally:
        await cleanup_study(fixture)


async def test_resume_study_wrapper_delegates_to_start_study(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resume_study`` is a thin wrapper — verify it dispatches to
    ``start_study`` with the same args."""
    from backend.workers import orchestrator

    called: list[tuple[dict[str, Any], str]] = []

    async def _fake_start_study(ctx: dict[str, Any], study_id: str) -> None:
        called.append((ctx, study_id))

    monkeypatch.setattr(orchestrator, "start_study", _fake_start_study)

    ctx = {"sentinel": True}
    await orchestrator.resume_study(ctx, "study-xyz")
    assert called == [(ctx, "study-xyz")]
