"""Partial-failure integration test for ``run_trial`` (Story 3.1 / AC-8b).

Spec §11 clause 1b: when the worker dies between ``study.tell()`` and the
app-row INSERT, Optuna has a terminal trial but the app does not. On retry,
the worker reconstructs the app row from ``study.trials[N]`` WITHOUT
re-running search/score/tell.

These tests use the ``_subprocess_helpers/run_trial_with_test_stubs.py``
entrypoint to invoke ``run_trial`` in a fresh Python interpreter with
``INFRA_OPTUNA_EVAL_FAULT`` set — pytest monkeypatches do not survive into
a child process, so the helper reinstalls the test doubles itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import optuna
import pytest
from optuna.trial import TrialState

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage
from backend.tests.conftest import postgres_reachable
from backend.tests.integration.fixtures.handbuilt_qrels import build_qrels
from backend.tests.integration.fixtures.run_trial_setup import (
    cleanup_study,
    create_optuna_trial_for_study,
    setup_study_with_cluster,
)
from backend.tests.integration.fixtures.stub_adapter import StubAdapter

REPO_ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = (
    REPO_ROOT
    / "backend"
    / "tests"
    / "integration"
    / "_subprocess_helpers"
    / "run_trial_with_test_stubs.py"
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


def _hits_json_for(query_ids: list[str]) -> str:
    """JSON-serializable shape mapping query_id → [(doc_id, score), ...]."""
    from backend.tests.integration.fixtures.handbuilt_qrels import _HITS

    return json.dumps({str(qid): _HITS[i] for i, qid in enumerate(query_ids[: len(_HITS)])})


def _run_subprocess_with_fault(
    *,
    study_id: str,
    optuna_trial_number: int,
    query_ids: list[str],
    fault: str,
) -> int:
    """Launch the helper subprocess; return its exit code."""
    qrels = build_qrels(query_ids)
    env = {
        **os.environ,
        "INFRA_OPTUNA_EVAL_TEST_QRELS_JSON": json.dumps(qrels),
        "INFRA_OPTUNA_EVAL_TEST_HITS_JSON": _hits_json_for(query_ids),
        "INFRA_OPTUNA_EVAL_TEST_STUDY_ID": study_id,
        "INFRA_OPTUNA_EVAL_TEST_TRIAL_NUMBER": str(optuna_trial_number),
        "INFRA_OPTUNA_EVAL_FAULT": fault,
    }
    proc = subprocess.run(
        [sys.executable, str(HELPER_PATH)],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    return proc.returncode


async def test_ac8b_case1_death_before_tell_recoverable_on_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-8b case 1: worker dies after loading the in-flight trial, before tell.

    End state per spec §11 (clarified): 1 terminal app row + 1 COMPLETE Optuna
    trial; no orphan accumulates (the worker doesn't call ask, so the retry
    completes the SAME trial number rather than allocating a fresh one).
    """
    fixture = await setup_study_with_cluster()
    storage = build_storage(get_settings().database_url)
    optuna_trial_number = create_optuna_trial_for_study(
        storage, optuna_study_name=fixture.optuna_study_name
    )

    # Subprocess invocation with seam #1 — dies before tell.
    rc = _run_subprocess_with_fault(
        study_id=fixture.study_id,
        optuna_trial_number=optuna_trial_number,
        query_ids=fixture.query_ids,
        fault="after_trial_load_before_execute",
    )
    assert rc == 1, "child should have died via os._exit(1) at the seam"

    # State after death: 0 app rows; 1 RUNNING Optuna trial.
    factory = get_session_factory()
    async with factory() as db:
        trials_after_death = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials_after_death) == 0

    optuna_study = optuna.load_study(study_name=fixture.optuna_study_name, storage=storage)
    assert optuna_study.trials[optuna_trial_number].state == TrialState.RUNNING

    # Retry — parent process this time, with stubs reinstalled.
    stub = StubAdapter(
        engine_type="elasticsearch",
        search_batch_response={
            qid: []
            for qid in fixture.query_ids  # filled below
        },
    )
    from backend.tests.integration.fixtures.handbuilt_qrels import build_hits_response

    stub.search_batch_response = build_hits_response(fixture.query_ids)
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _c: stub)
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

    # End state: 1 terminal app row, 1 COMPLETE Optuna trial, no duplicates.
    async with factory() as db:
        trials_after_retry = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials_after_retry) == 1
    assert trials_after_retry[0].status == "complete"

    optuna_study = optuna.load_study(study_name=fixture.optuna_study_name, storage=storage)
    assert optuna_study.trials[optuna_trial_number].state == TrialState.COMPLETE
    # Only one trial for this study (no duplicate ask was called).
    assert len(optuna_study.trials) == 1

    await cleanup_study(fixture.study_id)


async def test_ac8b_case2_death_after_tell_before_insert_reconciles(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-8b case 2: worker dies AFTER tell, BEFORE INSERT — spec §11 clause 1b.

    End state per spec §11 clause 1b: retry detects the COMPLETE Optuna trial
    and reconstructs the app row WITHOUT re-running search/score/tell. Exactly
    1 terminal app row, exactly 1 COMPLETE Optuna trial; no duplicates.
    """
    fixture = await setup_study_with_cluster()
    storage = build_storage(get_settings().database_url)
    optuna_trial_number = create_optuna_trial_for_study(
        storage, optuna_study_name=fixture.optuna_study_name
    )

    rc = _run_subprocess_with_fault(
        study_id=fixture.study_id,
        optuna_trial_number=optuna_trial_number,
        query_ids=fixture.query_ids,
        fault="after_tell_before_insert",
    )
    assert rc == 1

    # State after death: 0 app rows; Optuna trial is COMPLETE (tell happened).
    factory = get_session_factory()
    async with factory() as db:
        trials_after_death = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials_after_death) == 0

    optuna_study = optuna.load_study(study_name=fixture.optuna_study_name, storage=storage)
    assert optuna_study.trials[optuna_trial_number].state == TrialState.COMPLETE

    # Retry with stubs that RAISE if called — reconciliation must skip search/score.
    raising_stub = StubAdapter(raise_on_search=RuntimeError("must not run search again"))
    monkeypatch.setattr("backend.workers.trials.build_adapter", lambda _c: raising_stub)

    qrels_mock = AsyncMock(side_effect=RuntimeError("must not load qrels"))
    monkeypatch.setattr("backend.workers.trials.load_qrels", qrels_mock)

    from backend.workers.trials import run_trial

    await run_trial(
        ctx={"optuna_storage": storage},
        study_id=fixture.study_id,
        optuna_trial_number=optuna_trial_number,
    )

    # End state: 1 reconstructed app row + 1 COMPLETE Optuna trial.
    async with factory() as db:
        trials_after_retry = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials_after_retry) == 1
    t = trials_after_retry[0]
    assert t.status == "complete"
    assert t.primary_metric is not None
    # The metrics dict carries ONLY the primary (reconstruction can't recover the rest).
    # Per cycle-3 review A3 there is no metadata marker in metrics.
    assert "ndcg@10" in t.metrics
    assert len(t.metrics) == 1
    # search_batch was NEVER called on the second attempt.
    assert len(raising_stub.search_batch_calls) == 0
    # load_qrels was NEVER called either.
    qrels_mock.assert_not_called()

    await cleanup_study(fixture.study_id)
