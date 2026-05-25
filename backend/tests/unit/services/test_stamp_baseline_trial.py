"""Unit tests for :func:`backend.app.services.study_state.stamp_baseline_trial`.

The helper does one DB read (``repo.get_trial``) and one DB write (idempotent
UPDATE via raw SQL). Both are mocked here — integration coverage lives in
``backend/tests/integration/test_stamp_baseline_trial_integration.py``.

Spec: feat_study_baseline_trial FR-12. AC-1 / AC-16 depend on this contract.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from backend.app.db import repo as _db_repo
from backend.app.services.study_state import (
    BaselineTrialNotFound,
    InvalidBaselineTrialState,
    stamp_baseline_trial,
)


def _trial(**overrides: Any) -> Any:
    """SimpleNamespace stand-in for a Trial row."""
    base = {
        "id": "trial-1",
        "study_id": "study-1",
        "is_baseline": True,
        "status": "complete",
        "primary_metric": 0.612,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def mock_db() -> Any:
    """AsyncMock AsyncSession — execute() returns a configurable mock."""
    db = AsyncMock()
    return db


def _stub_execute_returns_row(db: Any, row: object | None) -> None:
    """Configure db.execute() to simulate the UPDATE ... RETURNING result.

    db.execute(...) is awaited and returns a Result whose .fetchone() is
    synchronous (per SQLAlchemy 2.0 async). The stamping helper calls
    `result.fetchone()` — None means 0 rows affected, a row means 1.
    """
    result = MagicMock()
    result.fetchone = MagicMock(return_value=row)
    db.execute = AsyncMock(return_value=result)


class TestStampBaselineTrial:
    async def test_happy_path_stamps_and_returns_true(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _db_repo,
            "get_trial",
            AsyncMock(return_value=_trial()),
        )
        _stub_execute_returns_row(mock_db, ("study-1",))

        stamped = await stamp_baseline_trial(mock_db, "study-1", "trial-1", 0.612)

        assert stamped is True
        assert mock_db.execute.await_count == 1
        # The UPDATE must use named bind params (plan F8).
        _stmt, params = mock_db.execute.await_args.args
        assert params == {
            "trial_id": "trial-1",
            "primary_metric": 0.612,
            "study_id": "study-1",
        }

    async def test_already_stamped_returns_false(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Idempotent: a sibling already stamped → UPDATE affects 0 rows
        (WHERE baseline_trial_id IS NULL no longer matches)."""
        monkeypatch.setattr(
            _db_repo,
            "get_trial",
            AsyncMock(return_value=_trial()),
        )
        _stub_execute_returns_row(mock_db, None)  # 0 rows affected

        stamped = await stamp_baseline_trial(mock_db, "study-1", "trial-1", 0.612)

        assert stamped is False

    async def test_missing_trial_raises_baseline_trial_not_found(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _db_repo,
            "get_trial",
            AsyncMock(return_value=None),
        )

        with pytest.raises(BaselineTrialNotFound, match="not found"):
            await stamp_baseline_trial(mock_db, "study-1", "trial-missing", 0.5)

    async def test_wrong_study_id_raises_invalid_state(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _db_repo,
            "get_trial",
            AsyncMock(return_value=_trial(study_id="other-study")),
        )

        with pytest.raises(InvalidBaselineTrialState, match="study_id"):
            await stamp_baseline_trial(mock_db, "study-1", "trial-1", 0.5)

    async def test_non_baseline_trial_raises_invalid_state(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            _db_repo,
            "get_trial",
            AsyncMock(return_value=_trial(is_baseline=False)),
        )

        with pytest.raises(InvalidBaselineTrialState, match="is_baseline=False"):
            await stamp_baseline_trial(mock_db, "study-1", "trial-1", 0.5)

    async def test_non_complete_status_raises_invalid_state(
        self, mock_db: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for non_complete in ("failed", "pruned"):
            monkeypatch.setattr(
                _db_repo,
                "get_trial",
                AsyncMock(return_value=_trial(status=non_complete)),
            )
            with pytest.raises(InvalidBaselineTrialState, match="status="):
                await stamp_baseline_trial(mock_db, "study-1", "trial-1", 0.5)

    async def test_does_not_commit(self, mock_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """Commit is left to the caller (spec FR-12)."""
        monkeypatch.setattr(
            _db_repo,
            "get_trial",
            AsyncMock(return_value=_trial()),
        )
        _stub_execute_returns_row(mock_db, ("study-1",))

        await stamp_baseline_trial(mock_db, "study-1", "trial-1", 0.5)

        assert mock_db.commit.await_count == 0

    async def test_emits_stamped_log_on_success(
        self,
        mock_db: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _db_repo,
            "get_trial",
            AsyncMock(return_value=_trial()),
        )
        _stub_execute_returns_row(mock_db, ("study-1",))

        with structlog.testing.capture_logs() as logs:
            await stamp_baseline_trial(mock_db, "study-1", "trial-1", 0.612)

        events = [log.get("event_type") for log in logs]
        assert "baseline_stamped" in events, logs

    async def test_emits_no_op_log_when_already_stamped(
        self,
        mock_db: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            _db_repo,
            "get_trial",
            AsyncMock(return_value=_trial()),
        )
        _stub_execute_returns_row(mock_db, None)

        with structlog.testing.capture_logs() as logs:
            await stamp_baseline_trial(mock_db, "study-1", "trial-1", 0.612)

        events = [log.get("event_type") for log in logs]
        assert "baseline_stamp_no_op" in events, logs
