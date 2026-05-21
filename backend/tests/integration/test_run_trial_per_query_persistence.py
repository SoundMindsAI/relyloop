"""``run_trial`` per_query_metrics persistence (feat_pr_metric_confidence Story 1.2).

Asserts that the run_trial worker persists ``scored["per_query"]`` from
``backend/app/eval/scoring.py:194`` to ``trials.per_query_metrics`` on the
success branch (AC-1) AND leaves the column NULL on the failure branch (AC-2).

Pairs with ``test_trials_per_query_metrics_migration.py`` (Story 1.1) — that
test asserts schema shape; this test asserts the worker actually writes the
column on success and omits it on failure.

Reuses the established ``setup_study_with_cluster()`` + ``StubAdapter`` +
monkeypatch pattern from ``test_run_trial.py``.

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


async def test_successful_trial_writes_per_query_metrics(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-1: a successful trial persists ``per_query_metrics`` as a non-NULL
    JSONB object shaped ``{qid: {metric_name: float}}`` using user-facing
    metric names (ndcg, map, precision, recall, mrr — NOT pytrec_eval wire
    forms)."""
    fixture = await setup_study_with_cluster()

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

    factory = get_session_factory()
    async with factory() as db:
        trials = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials) == 1
    t = trials[0]
    assert t.status == "complete"

    # AC-1: per_query_metrics is non-NULL and shaped as expected.
    assert t.per_query_metrics is not None, "successful trial must persist per_query_metrics (FR-1)"
    assert isinstance(t.per_query_metrics, dict)

    # Every seeded query_id appears as a key.
    persisted_qids = set(t.per_query_metrics.keys())
    expected_qids = set(fixture.query_ids)
    assert persisted_qids == expected_qids, (
        f"per_query_metrics keys should match the seeded query_ids; "
        f"got={persisted_qids}, expected={expected_qids}"
    )

    # Every value is a dict keyed by user-facing metric tokens. The score()
    # function emits user-facing tokens with the @<k> cutoff preserved for
    # metrics that take a cutoff (ndcg@10, map@10, precision@10, recall@10)
    # and bare names for cutoff-free metrics (mrr, plain map). The base
    # name (everything before any @) must be in MetricCatalog.
    expected_metric_bases = {"ndcg", "map", "precision", "recall", "mrr"}
    for qid, per_metric in t.per_query_metrics.items():
        assert isinstance(per_metric, dict), (
            f"per_query_metrics[{qid}] must be a dict, got {type(per_metric)}"
        )
        # The score() function returns one entry per metric in the
        # study's objective set. Assert at least ndcg is present (the
        # study's default objective metric) AND no pytrec_eval wire-form
        # keys leak through (e.g., "ndcg_cut.10", "P_10").
        assert per_metric, f"per_query_metrics[{qid}] is empty"
        for metric_key in per_metric:
            base = metric_key.partition("@")[0]
            assert base in expected_metric_bases, (
                f"unexpected metric key {metric_key!r} in per_query_metrics[{qid}]; "
                f"base name {base!r} not in {sorted(expected_metric_bases)} — "
                f"score() should remap pytrec_eval wire names to user-facing tokens"
            )
            assert isinstance(per_metric[metric_key], (int, float)), (
                f"per_query_metrics[{qid}][{metric_key}] must be numeric, "
                f"got {type(per_metric[metric_key])}"
            )

    await cleanup_fixture(fixture)


async def test_failed_trial_leaves_per_query_metrics_null(
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-2: when a trial fails (simulated adapter exception), the persisted
    row has ``status='failed'`` AND ``per_query_metrics IS NULL``. The failure
    branch at backend/workers/trials.py never passes ``per_query_metrics`` to
    ``repo.create_trial`` — confirms the worker correctly omits the kwarg on
    the failed path per FR-1."""
    fixture = await setup_study_with_cluster()

    storage = build_storage(get_settings().database_url)
    optuna_trial_number = create_optuna_trial_for_study(
        storage, optuna_study_name=fixture.optuna_study_name
    )

    # Stub adapter that raises on search_batch — pre-tell failure path.
    class _FailingAdapter:
        engine_type = "elasticsearch"
        aclose_called = False

        async def search_batch(self, *args, **kwargs):
            raise RuntimeError("simulated upstream failure")

        async def aclose(self):
            self.aclose_called = True

    stub: _FailingAdapter = _FailingAdapter()
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

    factory = get_session_factory()
    async with factory() as db:
        trials = await repo.list_trials_for_study(db, fixture.study_id)
    assert len(trials) == 1
    t = trials[0]
    assert t.status == "failed"
    assert t.error is not None
    # AC-2: per_query_metrics is NULL on the failure branch (kwarg omitted).
    assert t.per_query_metrics is None, (
        "failed trial must leave per_query_metrics NULL (FR-1 + INV-2)"
    )
    assert t.metrics == {}  # existing contract — failure path writes empty dict

    await cleanup_fixture(fixture)
