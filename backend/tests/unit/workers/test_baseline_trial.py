# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :func:`backend.workers.baseline.run_baseline_trial`.

The worker is heavy I/O — covers adapter + scorer + DB + studystate.
Tests mock every external dependency via ``monkeypatch`` per the existing
``test_run_trial.py`` convention. Integration coverage (real Postgres +
real Arq + real qrels load) lives in
``backend/tests/integration/test_orchestrator_baseline_trial.py``.

Spec: feat_study_baseline_trial FR-10. AC-1 / AC-3 / AC-16 depend.
"""

from __future__ import annotations

import asyncio as _asyncio_module
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.db import repo as _db_repo
from backend.app.services import study_state as _study_state
from backend.workers import baseline as baseline_worker


@pytest.fixture(autouse=True)
def _stub_ssrf_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the SSRF policy settings so the workers' inline base_url guard is a
    hermetic no-op (avoids constructing full Settings in this unit test)."""
    monkeypatch.setattr(
        "backend.app.services.cluster_url_policy.get_settings",
        lambda: MagicMock(relyloop_allow_private_clusters=True),
    )


def _study(**overrides: Any) -> Any:
    base = {
        "id": "study-1",
        "cluster_id": "cluster-1",
        "template_id": "template-1",
        "query_set_id": "qs-1",
        "judgment_list_id": "jl-1",
        "target": "products",
        "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
        "config": {"trial_timeout_s": 30},
        "search_space": {"params": {"boost_title": {"type": "float", "low": 0.5, "high": 10.0}}},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _cluster() -> Any:
    return SimpleNamespace(id="cluster-1", engine_type="elasticsearch", base_url="http://es:9200")


def _template_row() -> Any:
    return SimpleNamespace(
        id="template-1",
        name="my-template",
        engine_type="elasticsearch",
        body='{"query": {"match_all": {}}}',
        declared_params={"boost_title": "float"},
    )


def _query() -> Any:
    return SimpleNamespace(id="q-1", query_text="red shoes")


@pytest.fixture
def patched_externals(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub all I/O dependencies of run_baseline_trial."""
    mock_db = AsyncMock()
    # session_factory().__aenter__() returns mock_db.
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(baseline_worker, "get_session_factory", lambda: factory)

    monkeypatch.setattr(baseline_worker, "_existing_terminal_row", AsyncMock(return_value=None))

    monkeypatch.setattr(_db_repo, "get_study", AsyncMock(return_value=_study()))
    monkeypatch.setattr(_db_repo, "get_cluster", AsyncMock(return_value=_cluster()))
    monkeypatch.setattr(
        _db_repo,
        "get_query_template",
        AsyncMock(return_value=_template_row()),
    )
    monkeypatch.setattr(
        _db_repo,
        "list_queries_for_set",
        AsyncMock(return_value=[_query()]),
    )
    monkeypatch.setattr(baseline_worker, "load_qrels", AsyncMock(return_value={"q-1": {}}))

    mock_adapter = AsyncMock()
    mock_adapter.render = MagicMock(
        return_value=SimpleNamespace(query_id="q-1", body={"query": {}})
    )
    mock_adapter.search_batch = AsyncMock(
        return_value={"q-1": [SimpleNamespace(doc_id="d1", score=0.8)]}
    )
    mock_adapter.aclose = AsyncMock()
    monkeypatch.setattr(baseline_worker, "build_adapter", lambda _c: mock_adapter)

    monkeypatch.setattr(
        baseline_worker,
        "score",
        lambda qrels, run, metrics: {
            "aggregate": {"ndcg@10": 0.612, "map@10": 0.5, "mrr": 0.7},
            "per_query": {"q-1": {"ndcg@10": 0.612}},
        },
    )

    mock_trial = SimpleNamespace(
        id="trial-1",
        study_id="study-1",
        is_baseline=True,
        status="complete",
        primary_metric=0.612,
    )
    monkeypatch.setattr(_db_repo, "create_trial", AsyncMock(return_value=mock_trial))

    monkeypatch.setattr(
        _study_state,
        "stamp_baseline_trial",
        AsyncMock(return_value=True),
    )

    return {
        "db": mock_db,
        "adapter": mock_adapter,
        "create_trial": _db_repo.create_trial,
        "stamp": _study_state.stamp_baseline_trial,
    }


class TestRunBaselineTrialHappyPath:
    async def test_happy_path_inserts_and_stamps(self, patched_externals: dict[str, Any]) -> None:
        await baseline_worker.run_baseline_trial(
            ctx={}, study_id="study-1", trial_id="trial-1", params={"boost_title": 5.0}
        )

        # Trial INSERTed.
        patched_externals["create_trial"].assert_awaited_once()
        kwargs = patched_externals["create_trial"].await_args.kwargs
        assert kwargs["id"] == "trial-1"
        assert kwargs["study_id"] == "study-1"
        assert kwargs["is_baseline"] is True
        assert kwargs["optuna_trial_number"] == -1
        assert kwargs["status"] == "complete"
        assert kwargs["primary_metric"] == 0.612

        # Stamping helper called.
        patched_externals["stamp"].assert_awaited_once_with(
            patched_externals["db"], "study-1", "trial-1", 0.612
        )

    async def test_uses_default_secondary_metrics_when_config_absent(
        self,
        patched_externals: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Override study to remove secondary_metrics config.
        study = _study(config={"trial_timeout_s": 30})  # no secondary_metrics
        monkeypatch.setattr(_db_repo, "get_study", AsyncMock(return_value=study))

        captured: dict[str, Any] = {}

        def _capture_score(qrels: Any, run: Any, metrics: set[str]) -> Any:
            captured["metrics"] = metrics
            return {
                "aggregate": {"ndcg@10": 0.5, "map@10": 0.4, "mrr": 0.6},
                "per_query": {"q-1": {"ndcg@10": 0.5}},
            }

        monkeypatch.setattr(baseline_worker, "score", _capture_score)

        await baseline_worker.run_baseline_trial(
            ctx={}, study_id="study-1", trial_id="trial-1", params={}
        )

        # ndcg@10 (primary) + the default secondary set.
        assert captured["metrics"] == {"ndcg@10", "map@10", "mrr"}


class TestRunBaselineTrialIdempotency:
    async def test_idempotent_when_terminal_row_already_exists(
        self,
        patched_externals: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        existing = SimpleNamespace(
            id="trial-1",
            status="complete",
            is_baseline=True,
            primary_metric=0.612,
        )
        monkeypatch.setattr(
            baseline_worker, "_existing_terminal_row", AsyncMock(return_value=existing)
        )

        await baseline_worker.run_baseline_trial(
            ctx={}, study_id="study-1", trial_id="trial-1", params={}
        )

        # No new INSERT — but the stamp helper IS called (idempotent re-stamp).
        patched_externals["create_trial"].assert_not_awaited()
        patched_externals["stamp"].assert_awaited_once()

    async def test_idempotent_complete_existing_with_failed_status_no_stamp(
        self,
        patched_externals: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        existing = SimpleNamespace(
            id="trial-1",
            status="failed",
            is_baseline=True,
            primary_metric=None,
        )
        monkeypatch.setattr(
            baseline_worker, "_existing_terminal_row", AsyncMock(return_value=existing)
        )

        await baseline_worker.run_baseline_trial(
            ctx={}, study_id="study-1", trial_id="trial-1", params={}
        )

        patched_externals["create_trial"].assert_not_awaited()
        # Failed baseline doesn't stamp.
        patched_externals["stamp"].assert_not_awaited()


class TestRunBaselineTrialFailures:
    async def test_adapter_search_raises_persists_failed_row(
        self,
        patched_externals: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Adapter raises mid-search.
        patched_externals["adapter"].search_batch = AsyncMock(
            side_effect=RuntimeError("cluster unreachable")
        )

        # create_trial is called twice: first attempt (complete) fails because
        # adapter raised, then again from the failure-handler path. Reset to
        # a single AsyncMock that always returns a Trial.
        await baseline_worker.run_baseline_trial(
            ctx={}, study_id="study-1", trial_id="trial-1", params={}
        )

        # Last create_trial call should be the failed-row INSERT.
        assert patched_externals["create_trial"].await_count == 1
        kwargs = patched_externals["create_trial"].await_args.kwargs
        assert kwargs["status"] == "failed"
        assert kwargs["primary_metric"] is None
        assert "cluster unreachable" in kwargs["error"]
        # Failed baseline does NOT stamp.
        patched_externals["stamp"].assert_not_awaited()

    async def test_scorer_raises_persists_failed_row(
        self,
        patched_externals: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _raise(*a: Any, **kw: Any) -> Any:
            raise ValueError("metric not supported")

        monkeypatch.setattr(baseline_worker, "score", _raise)

        await baseline_worker.run_baseline_trial(
            ctx={}, study_id="study-1", trial_id="trial-1", params={}
        )

        assert patched_externals["create_trial"].await_count == 1
        kwargs = patched_externals["create_trial"].await_args.kwargs
        assert kwargs["status"] == "failed"
        assert "metric not supported" in kwargs["error"]
        patched_externals["stamp"].assert_not_awaited()

    async def test_operational_error_reraises_for_arq_retry(
        self,
        patched_externals: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from sqlalchemy.exc import OperationalError

        # Force the search to raise an OperationalError; the worker MUST
        # re-raise rather than swallowing it (Arq retries).
        patched_externals["adapter"].search_batch = AsyncMock(
            side_effect=OperationalError("DB unreachable", None, Exception())
        )

        with pytest.raises(OperationalError):
            await baseline_worker.run_baseline_trial(
                ctx={}, study_id="study-1", trial_id="trial-1", params={}
            )


class TestFaultSeam:
    async def test_fault_delay_seam_triggers_asyncio_sleep(
        self,
        patched_externals: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sleep_args: list[float] = []

        async def _fake_sleep(s: float) -> None:
            sleep_args.append(s)

        monkeypatch.setattr(_asyncio_module, "sleep", _fake_sleep)
        monkeypatch.setenv("FEAT_STUDY_BASELINE_TRIAL_FAULT", "delay_before_score")
        monkeypatch.setenv("FEAT_STUDY_BASELINE_TRIAL_FAULT_DELAY_S", "0.3")

        await baseline_worker.run_baseline_trial(
            ctx={}, study_id="study-1", trial_id="trial-1", params={}
        )

        assert sleep_args == [0.3]

    async def test_no_delay_when_env_var_unset(
        self,
        patched_externals: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sleep_called: list[float] = []

        async def _fake_sleep(s: float) -> None:
            sleep_called.append(s)

        monkeypatch.setattr(_asyncio_module, "sleep", _fake_sleep)
        monkeypatch.delenv("FEAT_STUDY_BASELINE_TRIAL_FAULT", raising=False)

        await baseline_worker.run_baseline_trial(
            ctx={}, study_id="study-1", trial_id="trial-1", params={}
        )

        assert sleep_called == []
