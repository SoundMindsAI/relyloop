# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the FR-2 baseline phase helpers in ``backend.workers.orchestrator``.

Covers (real-backend integration coverage lives in
``backend/tests/integration/test_orchestrator_baseline_trial.py``):

- :class:`BaselineEnqueueResult` discriminated union (plan-cycle-2 F2
  regression guard).
- :func:`_compute_baseline_wait_s` formula (FR-2 step 5).
- :func:`_resolve_and_enqueue_baseline` — skipped / enqueued / deduped
  branches.
- :func:`_run_baseline_phase` resume-path stamping of an existing complete
  baseline.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.core.settings import get_settings
from backend.app.db import repo as _db_repo
from backend.app.services import study_state as _study_state
from backend.workers import orchestrator as orch
from backend.workers.orchestrator import (
    BaselineEnqueueResult,
    _compute_baseline_wait_s,
)


@pytest.fixture(autouse=True)
def _settings_env_and_restore(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Seed required-secret env vars + clear the settings lru_cache.

    Settings construction needs DATABASE_URL_FILE + POSTGRES_PASSWORD_FILE per
    CLAUDE.md Rule #2. Point both at /dev/null — the cached_property accessors
    aren't invoked here, so the empty file content is never read. Clears the
    cache on the canonical get_settings imported from backend.app.core.settings
    (NOT orch.get_settings, which test_missing_trial_timeout_uses_settings_default
    monkeypatches to a plain lambda with no .cache_clear()). Makes the module
    hermetic regardless of collection order (FR-2).
    """
    monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _study(**overrides: Any) -> Any:
    base = {
        "id": "study-1",
        "config": {"trial_timeout_s": 30},
        "baseline_trial_id": None,
        "parent_proposal_id": None,
        "parent_study_id": None,
        "search_space": {"params": {"x": {"type": "float", "low": 0.0, "high": 1.0}}},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestBaselineEnqueueResult:
    def test_skipped_kind_has_no_trial_id(self) -> None:
        result = BaselineEnqueueResult(kind="skipped")
        assert result.kind == "skipped"
        assert result.trial_id is None

    def test_enqueued_kind_carries_trial_id(self) -> None:
        result = BaselineEnqueueResult(kind="enqueued", trial_id="t-1")
        assert result.kind == "enqueued"
        assert result.trial_id == "t-1"

    def test_deduped_kind_has_no_trial_id(self) -> None:
        result = BaselineEnqueueResult(kind="deduped")
        assert result.kind == "deduped"
        assert result.trial_id is None


class TestComputeBaselineWaitS:
    def test_short_timeout_floors_at_60(self) -> None:
        study = _study(config={"trial_timeout_s": 5})
        # 5 + 30 = 35, floor at 60.
        assert _compute_baseline_wait_s(study) == 60.0

    def test_typical_timeout_returns_plus_30(self) -> None:
        study = _study(config={"trial_timeout_s": 60})
        # max(60, 60+30) = 90, min(600, 90) = 90.
        assert _compute_baseline_wait_s(study) == 90.0

    def test_long_timeout_caps_at_600(self) -> None:
        study = _study(config={"trial_timeout_s": 1200})
        # max(60, 1200+30) = 1230, min(600, 1230) = 600.
        assert _compute_baseline_wait_s(study) == 600.0

    def test_missing_trial_timeout_uses_settings_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_settings = SimpleNamespace(studies_default_timeout_s=45)
        monkeypatch.setattr(orch, "get_settings", lambda: fake_settings)
        study = _study(config={})
        # max(60, 45+30) = 75.
        assert _compute_baseline_wait_s(study) == 75.0

    def test_explicit_timeout_does_not_read_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FR-1: an explicit trial_timeout_s must not construct Settings."""

        def _boom() -> Any:
            raise AssertionError("get_settings() must not be called for explicit timeout")

        monkeypatch.setattr(orch, "get_settings", _boom)
        study = _study(config={"trial_timeout_s": 60})
        assert _compute_baseline_wait_s(study) == 90.0


class TestResolveAndEnqueueBaseline:
    async def test_skipped_when_resolver_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(orch, "resolve_baseline_params", AsyncMock(return_value=None))
        arq_pool = AsyncMock()
        result = await orch._resolve_and_enqueue_baseline(AsyncMock(), arq_pool, _study())
        assert result.kind == "skipped"
        arq_pool.enqueue_job.assert_not_awaited()

    async def test_enqueued_when_resolver_returns_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(orch, "resolve_baseline_params", AsyncMock(return_value={"x": 0.5}))
        arq_pool = AsyncMock()
        arq_pool.enqueue_job = AsyncMock(return_value=MagicMock())  # non-None = accepted

        result = await orch._resolve_and_enqueue_baseline(AsyncMock(), arq_pool, _study())

        assert result.kind == "enqueued"
        assert result.trial_id is not None and len(result.trial_id) == 36
        kwargs = arq_pool.enqueue_job.await_args.kwargs
        assert kwargs == {"_job_id": "baseline:study-1"}
        # Positional args: function_name, study_id, trial_id, params.
        args = arq_pool.enqueue_job.await_args.args
        assert args[0] == "run_baseline_trial"
        assert args[1] == "study-1"
        assert args[3] == {"x": 0.5}

    async def test_deduped_when_arq_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(orch, "resolve_baseline_params", AsyncMock(return_value={"x": 0.5}))
        arq_pool = AsyncMock()
        arq_pool.enqueue_job = AsyncMock(return_value=None)  # duplicate rejected

        result = await orch._resolve_and_enqueue_baseline(AsyncMock(), arq_pool, _study())

        assert result.kind == "deduped"
        assert result.trial_id is None


class TestRunBaselinePhaseResumePath:
    async def test_skips_when_already_stamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resume path: if baseline_trial_id is already set, do nothing."""
        study_with_stamp = _study(baseline_trial_id="trial-1")
        db_session = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr(_db_repo, "get_study", AsyncMock(return_value=study_with_stamp))
        # Spy on the resolver — it should NOT be called.
        spy_resolver = AsyncMock()
        monkeypatch.setattr(orch, "resolve_baseline_params", spy_resolver)
        arq_pool = AsyncMock()

        await orch._run_baseline_phase(factory, arq_pool, "study-1")

        spy_resolver.assert_not_awaited()
        arq_pool.enqueue_job.assert_not_awaited()

    async def test_stamps_when_complete_baseline_exists_unstamped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resume path: complete baseline row exists but study unstamped — stamp it."""
        study = _study(baseline_trial_id=None)
        existing_baseline = SimpleNamespace(
            id="trial-1",
            status="complete",
            primary_metric=0.612,
        )
        db_session = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr(_db_repo, "get_study", AsyncMock(return_value=study))
        monkeypatch.setattr(
            orch, "_find_terminal_baseline_row", AsyncMock(return_value=existing_baseline)
        )
        stamp_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(_study_state, "stamp_baseline_trial", stamp_mock)

        # Spy: the resolver should NOT be called (resume short-circuits).
        spy_resolver = AsyncMock()
        monkeypatch.setattr(orch, "resolve_baseline_params", spy_resolver)
        arq_pool = AsyncMock()

        await orch._run_baseline_phase(factory, arq_pool, "study-1")

        stamp_mock.assert_awaited_once_with(db_session, "study-1", "trial-1", 0.612)
        spy_resolver.assert_not_awaited()
        arq_pool.enqueue_job.assert_not_awaited()

    async def test_skips_when_failed_baseline_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resume path: only failed baseline row exists — DO NOT retry."""
        study = _study(baseline_trial_id=None)
        failed_baseline = SimpleNamespace(id="trial-1", status="failed", primary_metric=None)
        db_session = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=db_session)
        factory.return_value.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr(_db_repo, "get_study", AsyncMock(return_value=study))
        monkeypatch.setattr(
            orch, "_find_terminal_baseline_row", AsyncMock(return_value=failed_baseline)
        )
        spy_resolver = AsyncMock()
        monkeypatch.setattr(orch, "resolve_baseline_params", spy_resolver)
        arq_pool = AsyncMock()

        await orch._run_baseline_phase(factory, arq_pool, "study-1")

        spy_resolver.assert_not_awaited()
        arq_pool.enqueue_job.assert_not_awaited()
