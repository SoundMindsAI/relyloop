# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``resolve_list_convergence_verdicts`` (Story 1.1).

Pins the gate order and decision matrix exactly as documented in the
spec (``feat_studies_convergence_visibility/feature_spec.md`` FR-2 +
AC-3b) without booting a real DB or full FastAPI app:

1. In-flight short-circuit → ``None``.
2. Direction-invalid → ``None`` (BEFORE the count gate — fixes the
   parity bug AC-3b catches).
3. Count gate: ``< CONVERGENCE_FLAT_MIN_COMPLETE`` (5) → ``None``;
   ``5 ≤ complete < STUDIES_TPE_WARMUP_FLOOR`` (50) →
   ``"too_few_trials"``.
4. Classifier path → reuses ``classify_convergence``; no trial-load
   for any study with ``complete < 50``.

The DB layer is monkey-patched so the test asserts NO trial-load is
issued in gates 1–3 (this is the "M=0 → 1 added query" half of AC-5,
covered structurally here without needing an integration DB).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.db.repo.trial import TrialCounts
from backend.app.domain.study.convergence import (
    CONVERGENCE_FLAT_MIN_COMPLETE,
    CurvePoint,
    StudyConvergenceShape,
)
from backend.app.eval.optuna_runtime import STUDIES_TPE_WARMUP_FLOOR
from backend.app.services.study_convergence import resolve_list_convergence_verdicts


class _FakeStudy:
    """Minimal stand-in for the ORM Study row.

    Only the attributes ``resolve_list_convergence_verdicts`` reads are
    populated (``id`` / ``status`` / ``objective``) — everything else
    SQLAlchemy would carry is unused on the resolver path.
    """

    def __init__(
        self,
        *,
        id: str,
        status: str,
        direction: str | None | object = "maximize",
    ) -> None:
        self.id = id
        self.status = status
        if direction is None:
            self.objective: Any = {"metric": "ndcg", "k": 10}  # no direction key
        else:
            self.objective = {"metric": "ndcg", "k": 10, "direction": direction}


async def _no_trials_loaded(*_: Any, **__: Any) -> dict[str, list[Any]]:
    """Sentinel that fails the test if the batched trial-loader is hit."""
    raise AssertionError(
        "list_complete_optuna_trials_for_studies must NOT be called when no "
        "study reaches the >=50 classifier gate (AC-5 M=0 case)"
    )


@pytest.mark.asyncio
async def test_in_flight_short_circuits_before_count_gate(monkeypatch) -> None:
    """A running study with plenty of trials still yields None (gate 1)."""
    monkeypatch.setattr(
        "backend.app.services.study_convergence.repo.list_complete_optuna_trials_for_studies",
        _no_trials_loaded,
    )
    studies = [_FakeStudy(id="s-run", status="running")]
    counts = {"s-run": TrialCounts(total=80, complete=80)}

    verdicts = await resolve_list_convergence_verdicts(None, studies, counts)  # type: ignore[arg-type]

    assert verdicts == {"s-run": None}


@pytest.mark.asyncio
async def test_queued_short_circuits(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.services.study_convergence.repo.list_complete_optuna_trials_for_studies",
        _no_trials_loaded,
    )
    studies = [_FakeStudy(id="s-q", status="queued")]
    verdicts = await resolve_list_convergence_verdicts(
        None,  # type: ignore[arg-type]
        studies,  # type: ignore[arg-type]
        {"s-q": TrialCounts(total=0, complete=0)},
    )
    assert verdicts == {"s-q": None}


@pytest.mark.asyncio
async def test_invalid_direction_at_5_to_49_trials_yields_null(monkeypatch) -> None:
    """AC-3b: invalid direction fires BEFORE the count gate.

    A completed study with 30 trials but an unrecognized ``direction``
    must yield ``None`` (matching ``fetch_study_convergence`` detail) —
    NOT ``"too_few_trials"`` (which would be the wrong answer if the
    gates were ordered count → direction).
    """
    monkeypatch.setattr(
        "backend.app.services.study_convergence.repo.list_complete_optuna_trials_for_studies",
        _no_trials_loaded,
    )
    studies = [_FakeStudy(id="s-bad", status="completed", direction="sideways")]
    counts = {"s-bad": TrialCounts(total=30, complete=30)}

    verdicts = await resolve_list_convergence_verdicts(None, studies, counts)  # type: ignore[arg-type]

    assert verdicts == {"s-bad": None}


@pytest.mark.asyncio
async def test_below_min_complete_yields_null(monkeypatch) -> None:
    """`< 5` complete trials → None (no badge)."""
    monkeypatch.setattr(
        "backend.app.services.study_convergence.repo.list_complete_optuna_trials_for_studies",
        _no_trials_loaded,
    )
    studies = [_FakeStudy(id="s-tiny", status="completed")]
    counts = {"s-tiny": TrialCounts(total=4, complete=CONVERGENCE_FLAT_MIN_COMPLETE - 1)}

    verdicts = await resolve_list_convergence_verdicts(None, studies, counts)  # type: ignore[arg-type]

    assert verdicts == {"s-tiny": None}


@pytest.mark.asyncio
async def test_5_to_49_complete_yields_too_few_trials_without_loading(monkeypatch) -> None:
    """The whole [5, 50) band is `too_few_trials` from the count alone."""
    monkeypatch.setattr(
        "backend.app.services.study_convergence.repo.list_complete_optuna_trials_for_studies",
        _no_trials_loaded,
    )
    studies = [
        _FakeStudy(id="s-5", status="completed"),
        _FakeStudy(id="s-12", status="completed"),
        _FakeStudy(id="s-49", status="completed"),
    ]
    counts = {
        "s-5": TrialCounts(total=5, complete=CONVERGENCE_FLAT_MIN_COMPLETE),
        "s-12": TrialCounts(total=12, complete=12),
        "s-49": TrialCounts(total=49, complete=STUDIES_TPE_WARMUP_FLOOR - 1),
    }

    verdicts = await resolve_list_convergence_verdicts(None, studies, counts)  # type: ignore[arg-type]

    assert verdicts == {
        "s-5": "too_few_trials",
        "s-12": "too_few_trials",
        "s-49": "too_few_trials",
    }


@pytest.mark.asyncio
async def test_at_or_above_warmup_runs_classifier_once_batched(monkeypatch) -> None:
    """Only the >=50 subset triggers the batched trial-load + classify pass.

    Also verifies the loader is called EXACTLY ONCE (not per-study), so
    the bounded-query budget holds.
    """
    load_calls: list[list[str]] = []

    async def _fake_loader(_db: Any, ids: list[str]) -> dict[str, list[Any]]:
        load_calls.append(list(ids))
        # Return whatever — `classify_convergence` is monkey-patched too.
        return {sid: [] for sid in ids}

    monkeypatch.setattr(
        "backend.app.services.study_convergence.repo.list_complete_optuna_trials_for_studies",
        _fake_loader,
    )

    fake_shape = StudyConvergenceShape(
        verdict="converged",
        direction="maximize",
        window_size=20,
        epsilon=0.005,
        warmup_floor=50,
        total_complete_trials=60,
        improvement_in_window=0.001,
        best_so_far_curve=[CurvePoint(trial_number=0, best_so_far=0.5)],
    )
    monkeypatch.setattr(
        "backend.app.services.study_convergence.classify_convergence",
        lambda *_a, **_kw: fake_shape,
    )

    studies = [
        _FakeStudy(id="s-low", status="completed"),
        _FakeStudy(id="s-big", status="completed"),
    ]
    counts = {
        "s-low": TrialCounts(total=12, complete=12),
        "s-big": TrialCounts(total=60, complete=60),
    }

    verdicts = await resolve_list_convergence_verdicts(None, studies, counts)  # type: ignore[arg-type]

    assert verdicts == {"s-low": "too_few_trials", "s-big": "converged"}
    # Loader fired exactly once, for the >=50 subset only.
    assert load_calls == [["s-big"]]


@pytest.mark.asyncio
async def test_classifier_exception_degrades_to_null(monkeypatch) -> None:
    """A classifier exception for one study yields None for THAT study,
    not a 500 for the whole list (mirrors fetch_study_convergence's try/except)."""

    async def _loader(_db: Any, ids: list[str]) -> dict[str, list[Any]]:
        return {sid: [] for sid in ids}

    monkeypatch.setattr(
        "backend.app.services.study_convergence.repo.list_complete_optuna_trials_for_studies",
        _loader,
    )

    def _explode(*_a: Any, **_kw: Any) -> StudyConvergenceShape | None:
        raise RuntimeError("boom")

    monkeypatch.setattr("backend.app.services.study_convergence.classify_convergence", _explode)

    studies = [_FakeStudy(id="s-big", status="completed")]
    counts = {"s-big": TrialCounts(total=60, complete=60)}

    verdicts = await resolve_list_convergence_verdicts(None, studies, counts)  # type: ignore[arg-type]

    assert verdicts == {"s-big": None}


@pytest.mark.asyncio
async def test_missing_count_treated_as_zero(monkeypatch) -> None:
    """A study not in ``trial_counts`` falls back to zero (gate 3 -> None).

    Defensive guard so a stale id list cannot KeyError the whole list.
    """
    monkeypatch.setattr(
        "backend.app.services.study_convergence.repo.list_complete_optuna_trials_for_studies",
        _no_trials_loaded,
    )
    studies = [_FakeStudy(id="s-orphan", status="completed")]
    verdicts = await resolve_list_convergence_verdicts(None, studies, {})  # type: ignore[arg-type]
    assert verdicts == {"s-orphan": None}


# Defensive: the test uses datetime to ensure timezone import works on import
_ = datetime.now(UTC)
