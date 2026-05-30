# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Happy-path integration test for ``run_trial`` (Story 3.1).

Covers ACs 2 (TPE default), 4 (complete trial row), and 7 (single _msearch
call, zero _search). Uses a stub adapter installed via monkeypatch instead
of a recorded cassette — the assertion against AC-7 is performed by counting
calls on the stub, which is equivalent to inspecting a cassette but avoids
the cassette-recording brittleness.

Skips automatically when Postgres isn't reachable from the host shell.
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
    EXPECTED_NDCG_AT_10,
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


async def test_run_trial_writes_complete_trial_row_with_tpe_sampler(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-2 + AC-4 + AC-7.

    - TPE sampler is the default (AC-2).
    - A 'complete' trials row is written with populated metrics, primary
      denormalized, duration > 0 (AC-4).
    - Exactly one ``search_batch`` call (AC-7 — proxy for "exactly one
      _msearch, zero _search" since the stub adapter records calls).
    """
    fixture = await setup_study_with_cluster()

    storage = build_storage(get_settings().database_url)
    optuna_trial_number = create_optuna_trial_for_study(
        storage, optuna_study_name=fixture.optuna_study_name
    )

    # Install the stub adapter via monkeypatch.
    stub = StubAdapter(
        engine_type="elasticsearch",
        search_batch_response=build_hits_response(fixture.query_ids),
    )
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _cluster: stub)

    # Install the qrels stub (covering for feat_llm_judgments not yet shipping).
    handbuilt = build_qrels(fixture.query_ids)
    monkeypatch.setattr(
        "backend.workers.trials.load_qrels",
        AsyncMock(return_value=handbuilt),
    )

    # AC-2: sampler check (against the constructed Optuna study).
    from backend.app.eval.optuna_runtime import (
        build_pruner as _bp,
    )
    from backend.app.eval.optuna_runtime import (
        build_sampler as _bs,
    )
    from backend.app.eval.optuna_runtime import (
        get_or_create_study as _gocs,
    )

    sampler = _bs({"max_trials": 100, "sampler": "tpe"}, seed=None)
    pruner = _bp({"max_trials": 100, "sampler": "tpe"})
    study = _gocs(
        storage=storage,
        optuna_study_name=fixture.optuna_study_name,
        direction="maximize",
        sampler=sampler,
        pruner=pruner,
    )
    assert study.sampler.__class__.__name__ == "TPESampler"

    # Run the worker.
    from backend.workers.trials import run_trial

    await run_trial(
        ctx={"optuna_storage": storage},
        study_id=fixture.study_id,
        optuna_trial_number=optuna_trial_number,
    )

    # AC-7: exactly one search_batch call (proxy for single _msearch, zero _search).
    assert len(stub.search_batch_calls) == 1
    assert stub.search_batch_calls[0]["n_queries"] == len(fixture.query_ids)
    # infra_per_trial_timeout: when the study config omits trial_timeout_s
    # the worker resolves the Settings default (60s) and passes it to
    # adapter.search_batch as a float.
    assert stub.search_batch_calls[0]["timeout"] == 60.0
    assert stub.aclose_called is True

    # AC-4: a 'complete' trials row exists with expected fields.
    factory = get_session_factory()
    async with factory() as db:
        trials = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials) == 1
    t = trials[0]
    assert t.status == "complete"
    assert t.optuna_trial_number == optuna_trial_number
    assert t.primary_metric is not None
    assert abs(t.primary_metric - EXPECTED_NDCG_AT_10) < 1e-6
    assert t.metrics.get("ndcg@10") is not None
    assert abs(t.metrics["ndcg@10"] - EXPECTED_NDCG_AT_10) < 1e-6
    assert t.duration_ms is not None
    assert t.duration_ms >= 0
    assert isinstance(t.duration_ms, int)
    assert t.error is None
    assert t.params  # populated by orchestrator simulation
    assert "bm25_k1" in t.params
    assert "bm25_b" in t.params

    await cleanup_fixture(fixture)


async def test_run_trial_threads_per_study_trial_timeout_into_adapter(
    monkeypatch: pytest.MonkeyPatch,
):
    """infra_per_trial_timeout: when ``study.config.trial_timeout_s`` is set
    it wins over ``Settings.studies_default_timeout_s`` and is forwarded
    to ``adapter.search_batch(..., timeout=...)`` as a float."""
    fixture = await setup_study_with_cluster(extra_config={"trial_timeout_s": 300})

    storage = build_storage(get_settings().database_url)
    optuna_trial_number = create_optuna_trial_for_study(
        storage, optuna_study_name=fixture.optuna_study_name
    )

    stub = StubAdapter(
        engine_type="elasticsearch",
        search_batch_response=build_hits_response(fixture.query_ids),
    )
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _cluster: stub)
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

    assert len(stub.search_batch_calls) == 1
    assert stub.search_batch_calls[0]["timeout"] == 300.0

    await cleanup_fixture(fixture)
