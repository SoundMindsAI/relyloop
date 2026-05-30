# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Idempotency integration test for ``run_trial`` (Story 3.1 / AC-8a).

Spec §11 clause 1a: re-running ``run_trial(study_id, N)`` after a
successful first invocation is a no-op — the worker detects the existing
terminal app row and returns without re-executing search/score/tell.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.handbuilt_qrels import (
    build_hits_response,
    build_qrels,
)
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


async def test_re_running_completed_trial_is_no_op(monkeypatch: pytest.MonkeyPatch):
    """AC-8a — second invocation does not re-execute search/score."""
    fixture = await setup_study_with_cluster()

    storage = build_storage(get_settings().database_url)
    optuna_trial_number = create_optuna_trial_for_study(
        storage, optuna_study_name=fixture.optuna_study_name
    )

    stub = StubAdapter(
        engine_type="elasticsearch",
        search_batch_response=build_hits_response(fixture.query_ids),
    )
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _c: stub)
    monkeypatch.setattr(
        "backend.workers.trials.load_qrels",
        AsyncMock(return_value=build_qrels(fixture.query_ids)),
    )

    from backend.workers.trials import run_trial

    # First invocation — should write a 'complete' row.
    await run_trial(
        ctx={"optuna_storage": storage},
        study_id=fixture.study_id,
        optuna_trial_number=optuna_trial_number,
    )

    factory = get_session_factory()
    async with factory() as db:
        trials_after_first = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials_after_first) == 1
    assert trials_after_first[0].status == "complete"
    assert len(stub.search_batch_calls) == 1

    # Second invocation — must be a no-op (clause 1a).
    await run_trial(
        ctx={"optuna_storage": storage},
        study_id=fixture.study_id,
        optuna_trial_number=optuna_trial_number,
    )

    async with factory() as db:
        trials_after_second = await repo.list_trials_for_study(db, fixture.study_id)
    # Same row count — no duplicate written.
    assert len(trials_after_second) == 1
    # No second search_batch call — short-circuit fired before reaching the adapter.
    assert len(stub.search_batch_calls) == 1

    await cleanup_fixture(fixture)
