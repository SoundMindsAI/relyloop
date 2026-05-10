"""Adapter-failure integration test for ``run_trial`` (Story 3.1 / AC-5).

When the adapter raises ``ClusterUnreachableError`` mid-trial, the worker
must:

* persist a ``trials`` row with ``status='failed'``, populated ``error``,
  ``metrics={}``, ``primary_metric=None``;
* call ``study.tell(..., state=TrialState.FAIL)`` so the Optuna trial
  doesn't dangle in RUNNING state;
* return normally (Arq treats success — failed trial is a recorded outcome,
  not a job-level error).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.app.adapters.errors import ClusterUnreachableError
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.handbuilt_qrels import build_qrels
from backend.tests.integration.fixtures.run_trial_setup import (
    cleanup_fixture,
    create_optuna_trial_for_study,
    setup_study_with_cluster,
)
from backend.tests.integration.fixtures.stub_adapter import StubAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_run_trial_persists_failed_row_on_adapter_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-5: adapter raises → status='failed', error populated, metrics={}."""
    fixture = await setup_study_with_cluster()

    storage = build_storage(get_settings().database_url)
    optuna_trial_number = create_optuna_trial_for_study(
        storage, optuna_study_name=fixture.optuna_study_name
    )

    failing_stub = StubAdapter(
        raise_on_search=ClusterUnreachableError("CLUSTER_UNREACHABLE: stub failure"),
    )
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _c: failing_stub)
    monkeypatch.setattr(
        "backend.workers.trials.load_qrels",
        AsyncMock(return_value=build_qrels(fixture.query_ids)),
    )

    from backend.workers.trials import run_trial

    await run_trial(
        ctx={"optuna_storage": storage},
        study_id=fixture.study_id,
        optuna_trial_number=optuna_trial_number,
    )

    # Failed trial row should exist with the documented shape.
    factory = get_session_factory()
    async with factory() as db:
        trials = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials) == 1
    t = trials[0]
    assert t.status == "failed"
    assert t.metrics == {}
    assert t.primary_metric is None
    assert t.error is not None
    assert "CLUSTER_UNREACHABLE" in t.error
    # Adapter aclose() still ran via finally.
    assert failing_stub.aclose_called is True

    await cleanup_fixture(fixture)
