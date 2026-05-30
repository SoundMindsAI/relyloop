# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""AC-3 (service-layer half) — orchestrator detects cancel + drains.

The HTTP 409 "cancel an already-cancelled study" half lives in Story 3.5's
``test_studies_error_codes.py`` (Epic 3). This file owns the
service-layer + orchestrator contract without HTTP overhead — the
orchestrator loop must transition to exit on the next poll tick after
``cancel_study`` commits, and ``_drain_in_flight`` must wait (bounded)
for any in-flight Optuna trials to terminate before exiting.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage
from backend.app.services import study_state
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.study_factories import (
    cleanup_study,
    install_stub_adapter,
    monkeypatch_qrels,
    seed_study,
)
from backend.tests.integration.test_study_lifecycle import (
    _InProcessPool,
    _running_orchestrator,
    _wait_for_status,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_orchestrator_detects_cancel_and_exits(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-3 service-layer half: cancel_study while orchestrator is running
    causes the orchestrator to detect the new status on its next poll tick,
    drain any in-flight trials, and exit silently."""
    fixture = await seed_study(max_trials=1000, parallelism=2)
    try:
        install_stub_adapter(monkeypatch, fixture.query_ids)
        monkeypatch_qrels(monkeypatch, fixture.query_ids)

        storage = build_storage(get_settings().database_url)
        pool = _InProcessPool(storage)
        caplog.set_level(logging.INFO)
        async with _running_orchestrator(fixture, pool) as orchestrator_task:
            # Wait until the study reaches running + at least one trial committed.
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "running", timeout=10.0),
                timeout=10.0,
            )

            # Wait a brief moment so at least one trial accumulates.
            for _ in range(40):  # up to 4s
                await asyncio.sleep(0.1)
                factory = get_session_factory()
                async with factory() as db:
                    summary = await repo.aggregate_trials_summary(db, fixture.study_id)
                if summary.complete >= 1:
                    break

            # Cancel via service layer (the HTTP endpoint lands in Story 3.3).
            async with factory() as db:
                await study_state.cancel_study(db, fixture.study_id)
                await db.commit()

            # Within 30s, status should be cancelled AND orchestrator should exit.
            await asyncio.wait_for(
                _wait_for_status(fixture.study_id, "cancelled", timeout=30.0),
                timeout=30.0,
            )
            # Give the orchestrator time to see the new status on its next tick + exit.
            await asyncio.wait_for(orchestrator_task, timeout=10.0)

        # Verify no trial was marked failed by the cancel itself.
        factory = get_session_factory()
        async with factory() as db:
            summary = await repo.aggregate_trials_summary(db, fixture.study_id)
            assert summary.failed == 0

        # Verify orchestrator logged its exit (drain reached or status read).
        # structlog passes structured kwargs through as record.args / record.__dict__
        # — match on the human-readable message instead, which contains "orchestrator exit".
        exit_messages = [r for r in caplog.records if "orchestrator exit" in r.getMessage()]
        assert exit_messages, "expected an orchestrator_exit log entry"
    finally:
        await cleanup_study(fixture)
