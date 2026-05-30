# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for backend.workers.trials helpers (Story 2.3).

These tests cover the pure-ish helpers — ``_snapshot_optuna_trial``,
``_reconstruct_from_optuna`` (state mapping + metrics shape per spec §11
clause 1b + cycle-3 review A3) — using mocks so no real Postgres or Optuna
storage is touched. Full ``run_trial`` execution is exercised by the
integration tests in Story 3.1.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from optuna.trial import TrialState

from backend.workers.trials import (
    _OPTUNA_STATE_TO_APP_STATUS,
    TrialSnapshot,
    _reconstruct_from_optuna,
    _snapshot_optuna_trial,
)

# ---------------------------------------------------------------------------
# _snapshot_optuna_trial — copies the four needed fields off the live trial
# ---------------------------------------------------------------------------


def test_snapshot_optuna_trial_copies_fields():
    """Snapshot dataclass receives number/state/params/value from study.trials[n]."""
    frozen = MagicMock()
    frozen.number = 7
    frozen.state = TrialState.COMPLETE
    frozen.params = {"bm25_k1": 1.5, "bm25_b": 0.75}
    frozen.value = 0.87

    study = MagicMock()
    study.trials = {7: frozen}

    snapshot = _snapshot_optuna_trial(study, 7)
    assert snapshot.number == 7
    assert snapshot.state == TrialState.COMPLETE
    assert snapshot.params == {"bm25_k1": 1.5, "bm25_b": 0.75}
    assert snapshot.value == 0.87


def test_snapshot_optuna_trial_copies_params_dict():
    """params is a fresh dict — mutations on the snapshot don't leak to the FrozenTrial."""
    frozen = MagicMock()
    frozen.number = 0
    frozen.state = TrialState.COMPLETE
    frozen.params = {"k": 1.0}
    frozen.value = 0.5

    study = MagicMock()
    study.trials = {0: frozen}

    snapshot = _snapshot_optuna_trial(study, 0)
    snapshot.params["new_key"] = 999  # would raise if frozen
    assert frozen.params == {"k": 1.0}  # untouched


# ---------------------------------------------------------------------------
# _OPTUNA_STATE_TO_APP_STATUS — terminal-state mapping
# ---------------------------------------------------------------------------


def test_optuna_state_mapping_covers_all_terminal_states():
    """The three terminal Optuna states map to the three spec §8.4 statuses."""
    assert _OPTUNA_STATE_TO_APP_STATUS == {
        TrialState.COMPLETE: "complete",
        TrialState.FAIL: "failed",
        TrialState.PRUNED: "pruned",
    }


# ---------------------------------------------------------------------------
# _reconstruct_from_optuna — state-specific metrics shape (cycle-3 review A3)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_and_repo(monkeypatch: pytest.MonkeyPatch):
    """AsyncMock session + capturing ``repo.create_trial`` stub.

    Returns ``(db, captured_kwargs)`` where ``captured_kwargs`` is a dict
    populated when the helper calls ``repo.create_trial(db, **fields)``.
    """
    db = AsyncMock()
    captured: dict[str, Any] = {}

    async def fake_create_trial(_db, **fields: Any):
        captured.update(fields)
        return MagicMock(**fields)

    monkeypatch.setattr("backend.workers.trials.repo.create_trial", fake_create_trial)
    return db, captured


async def test_reconstruct_complete_persists_primary_metric_in_metrics_dict(
    mock_db_and_repo,
):
    """COMPLETE: metrics = {objective_key: value} — no metadata pollution.

    Per cycle-3 review A3: the ``_reconciled`` marker is emitted via
    structlog event, NOT polluted into ``trials.metrics`` (which spec
    FR-5 reserves for user-facing metric names only).
    """
    db, captured = mock_db_and_repo
    snapshot = TrialSnapshot(number=3, state=TrialState.COMPLETE, params={"k1": 1.2}, value=0.91)
    await _reconstruct_from_optuna(
        db,
        snapshot,
        trial_id="t-uuid",
        study_id="s-uuid",
        optuna_trial_number=3,
        objective_key="ndcg@10",
    )
    assert captured["status"] == "complete"
    assert captured["primary_metric"] == 0.91
    assert captured["metrics"] == {"ndcg@10": 0.91}
    assert captured["params"] == {"k1": 1.2}
    assert captured["error"] is None
    assert captured["duration_ms"] is None
    assert captured["id"] == "t-uuid"


async def test_reconstruct_fail_persists_empty_metrics_and_reconstruction_error(
    mock_db_and_repo,
):
    """FAIL: metrics = {}, primary_metric = None, error explains reconstruction."""
    db, captured = mock_db_and_repo
    snapshot = TrialSnapshot(number=4, state=TrialState.FAIL, params={"k1": 0.5}, value=None)
    await _reconstruct_from_optuna(
        db,
        snapshot,
        trial_id="t-uuid",
        study_id="s-uuid",
        optuna_trial_number=4,
        objective_key="ndcg@10",
    )
    assert captured["status"] == "failed"
    assert captured["primary_metric"] is None
    assert captured["metrics"] == {}
    assert "reconstructed from Optuna FAIL" in captured["error"]
    assert captured["duration_ms"] is None


async def test_reconstruct_pruned_preserves_partial_value_and_empty_metrics(
    mock_db_and_repo,
):
    """PRUNED: metrics = {}, primary_metric = snapshot.value (may be None), error = None."""
    db, captured = mock_db_and_repo
    snapshot = TrialSnapshot(number=5, state=TrialState.PRUNED, params={"k1": 0.7}, value=0.42)
    await _reconstruct_from_optuna(
        db,
        snapshot,
        trial_id="t-uuid",
        study_id="s-uuid",
        optuna_trial_number=5,
        objective_key="ndcg@10",
    )
    assert captured["status"] == "pruned"
    assert captured["primary_metric"] == 0.42
    assert captured["metrics"] == {}
    assert captured["error"] is None
    assert captured["duration_ms"] is None


async def test_reconstruct_pruned_with_no_value_preserves_none(mock_db_and_repo):
    """PRUNED before warmup may have no value; reconstruction tolerates None."""
    db, captured = mock_db_and_repo
    snapshot = TrialSnapshot(number=6, state=TrialState.PRUNED, params={}, value=None)
    await _reconstruct_from_optuna(
        db,
        snapshot,
        trial_id="t-uuid",
        study_id="s-uuid",
        optuna_trial_number=6,
        objective_key="ndcg@10",
    )
    assert captured["status"] == "pruned"
    assert captured["primary_metric"] is None


async def test_reconstruct_unknown_state_raises_value_error(mock_db_and_repo):
    """A non-terminal state during reconciliation is a programming error."""
    db, _captured = mock_db_and_repo
    # RUNNING is not in the terminal-state mapping.
    snapshot = TrialSnapshot(number=7, state=TrialState.RUNNING, params={}, value=None)
    with pytest.raises(ValueError, match=r"unexpected non-terminal Optuna state"):
        await _reconstruct_from_optuna(
            db,
            snapshot,
            trial_id="t-uuid",
            study_id="s-uuid",
            optuna_trial_number=7,
            objective_key="ndcg@10",
        )


async def test_reconstruct_complete_uses_objective_key_for_metrics_index(
    mock_db_and_repo,
):
    """objective_key flows into the metrics dict key — not hardcoded."""
    db, captured = mock_db_and_repo
    snapshot = TrialSnapshot(number=0, state=TrialState.COMPLETE, params={}, value=0.5)
    await _reconstruct_from_optuna(
        db,
        snapshot,
        trial_id="t-uuid",
        study_id="s-uuid",
        optuna_trial_number=0,
        objective_key="map@10",  # different from the prior ndcg@10
    )
    assert captured["metrics"] == {"map@10": 0.5}


async def test_reconstruct_commits_via_db_session(mock_db_and_repo):
    """Reconciliation commits the inserted row (no caller commit required)."""
    db, _captured = mock_db_and_repo
    snapshot = TrialSnapshot(number=1, state=TrialState.COMPLETE, params={}, value=0.5)
    await _reconstruct_from_optuna(
        db,
        snapshot,
        trial_id="t-uuid",
        study_id="s-uuid",
        optuna_trial_number=1,
        objective_key="ndcg@10",
    )
    db.commit.assert_awaited_once()
