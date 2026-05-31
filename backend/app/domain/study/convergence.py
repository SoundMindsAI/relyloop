# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Per-study convergence verdict (feat_study_convergence_indicator Story 1.2).

Pure-Python classifier that answers the operator's morning question:
*"did this study actually finish learning, or did I stop it too early?"*
The verdict — ``converged`` / ``still_improving`` / ``too_few_trials`` —
drives the UI badge on ``/studies/[id]``, the digest narrative's lead
recommendation framing, and (via FR-7's soft contract) the overnight
autopilot chain panel's per-link summary.

**Domain-layer convention** (per CLAUDE.md "Domain Layer"): every function
in this module is pure — no DB access, no I/O, no async. The service
helper :func:`backend.app.services.study_convergence.fetch_study_convergence`
loads the trial rows and orchestrates direction resolution + exception
shielding; this module deterministically returns the same verdict for the
same input.

**Name-collision discipline reminder** (plan §0): this module is
``convergence.py`` (singular). It introduces brand-new names —
:data:`ConvergenceVerdict`, :class:`ConvergenceShape`,
:data:`CONVERGENCE_FLAT_EPSILON`, :data:`CONVERGENCE_FLAT_WINDOW`,
:data:`CONVERGENCE_FLAT_MIN_COMPLETE`. **Do NOT** import or shadow
``confidence.py``'s ``ConvergenceRegime`` or ``CONVERGENCE_MIN_COMPLETE`` —
those mean different things (winner-trial *timing*, not metric *plateau*).

Algorithm (matches spec §9 decision matrix):

1. Filter input to ``status == "complete" AND is_baseline is False AND
   primary_metric is not None``; sort by ``optuna_trial_number ASC``.
2. If filtered count ``< CONVERGENCE_FLAT_MIN_COMPLETE`` (5) → return
   ``None`` (panel renders the null-state badge).
3. Build the best-so-far curve via running max (maximize) or running min
   (minimize).
4. ``window_size = min(CONVERGENCE_FLAT_WINDOW, max(5, total // 5))``.
5. ``improvement_in_window = curve[-1] - curve[-window_size]`` (maximize)
   or sign-flipped (minimize). Always ``>= 0`` by construction.
6. Decision matrix (first match wins):

   - ``total < STUDIES_TPE_WARMUP_FLOOR`` (50) → ``too_few_trials``
   - ``improvement_in_window <= CONVERGENCE_FLAT_EPSILON`` → ``converged``
   - else → ``still_improving``
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel

from backend.app.domain.study.auto_followup import (
    AUTO_FOLLOWUP_LIFT_EPSILON as CONVERGENCE_FLAT_EPSILON,
)
from backend.app.eval.optuna_runtime import STUDIES_TPE_WARMUP_FLOOR

# Trailing-window-flat parameters (locked by spec §9 / D-1):
#
# - ``CONVERGENCE_FLAT_WINDOW`` — the "last N trials" the trailing-flat
#   check averages over. 20 trials is large enough that one anomalous
#   late trial cannot single-handedly flip the verdict, and small enough
#   that mid-budget studies (200 trials) still get a meaningful tail
#   slice.
# - ``CONVERGENCE_FLAT_MIN_COMPLETE`` — below this many usable Optuna
#   trials the classifier returns ``None`` (panel falls back to "Verdict
#   pending — not enough trials yet"). Distinct from
#   ``STUDIES_TPE_WARMUP_FLOOR`` (50): below 5 we lack a meaningful tail
#   at all; between 5 and 50 the verdict is ``too_few_trials``.
CONVERGENCE_FLAT_WINDOW: int = 20
CONVERGENCE_FLAT_MIN_COMPLETE: int = 5

ConvergenceVerdict = Literal["converged", "still_improving", "too_few_trials"]


class CurvePoint(BaseModel):
    """One point on the best-so-far curve.

    ``trial_number`` is the trial's ``optuna_trial_number`` (the canonical
    "trial order within the study" field — see ``auto_followup.py`` module
    docstring for why we sort by this rather than ``started_at``).
    ``best_so_far`` is the running extremum of ``primary_metric`` over all
    earlier trials, sign-corrected to the study's optimization direction.
    """

    trial_number: int
    best_so_far: float


class ConvergenceShape(BaseModel):
    """Verdict + supporting numerics for the UI panel and the digest narrative.

    Mirrors the ``ConfidenceShape`` pattern from ``confidence.py``: the
    domain module owns the Pydantic model, and ``backend.app.api.v1.schemas``
    re-exports it for the ``StudyDetail.convergence`` field. The
    ``best_so_far_curve`` is the chart's data series; ``verdict`` is the
    badge label.
    """

    verdict: ConvergenceVerdict
    direction: Literal["maximize", "minimize"]
    window_size: int
    epsilon: float
    warmup_floor: int
    total_complete_trials: int
    improvement_in_window: float
    best_so_far_curve: list[CurvePoint]


def _usable(trial: Any) -> bool:
    """Return True iff a trial contributes to the curve.

    Complete, non-baseline, and carries a primary metric. Mirrors the SQL
    filter in
    :func:`backend.app.db.repo.trial.list_complete_optuna_trials_for_study`
    so the pure classifier degrades gracefully when fed a wider set.
    """
    return (
        getattr(trial, "status", None) == "complete"
        and getattr(trial, "is_baseline", False) is False
        and getattr(trial, "primary_metric", None) is not None
    )


def classify_convergence(
    complete_trials: Sequence[Any],
    *,
    direction: Literal["maximize", "minimize"],
) -> ConvergenceShape | None:
    """Deterministically classify a study's convergence state.

    Returns ``None`` when the trial count is below
    :data:`CONVERGENCE_FLAT_MIN_COMPLETE` (caller surfaces the panel's
    "Verdict pending — not enough trials yet" badge). Returns a populated
    :class:`ConvergenceShape` otherwise — every sub-field is always set.

    The function is pure: same input → same output across any number of
    calls (asserted by the determinism property test). No DB, no I/O, no
    async.
    """
    # Defense-in-depth: also filter at the domain layer in case the caller
    # passes a wider set (the dedicated repo helper from Story 2.1 already
    # pushes the same filter into SQL).
    usable = sorted(
        (t for t in complete_trials if _usable(t)),
        key=lambda t: t.optuna_trial_number,
    )
    total = len(usable)
    if total < CONVERGENCE_FLAT_MIN_COMPLETE:
        return None

    # Best-so-far curve, direction-aware (running max for maximize, running
    # min for minimize). The metric values are the raw study primary
    # metric; "best" is interpreted via ``direction``.
    curve: list[CurvePoint] = []
    if direction == "maximize":
        running = float("-inf")
        for t in usable:
            metric = float(t.primary_metric)
            if metric > running:
                running = metric
            curve.append(CurvePoint(trial_number=t.optuna_trial_number, best_so_far=running))
    else:
        running = float("inf")
        for t in usable:
            metric = float(t.primary_metric)
            if metric < running:
                running = metric
            curve.append(CurvePoint(trial_number=t.optuna_trial_number, best_so_far=running))

    # Window size clamps so we always have at least 5 trials to compare
    # against and never request more trials than we have. At total=5 the
    # window is the whole curve; at total=100+ it caps at 20.
    window_size = min(CONVERGENCE_FLAT_WINDOW, max(5, total // 5))

    # Improvement-in-window: how much "best" moved from the start of the
    # window to its end. Sign-flipped for minimize so the value is always
    # ``>= 0`` ("how much did we improve" — never negative by construction
    # because best-so-far is monotonic).
    window_start = curve[-window_size].best_so_far
    window_end = curve[-1].best_so_far
    raw_improvement = window_end - window_start
    improvement_in_window = raw_improvement if direction == "maximize" else -raw_improvement

    # Decision matrix (spec §9, first match wins). The warmup-floor check
    # fires FIRST so studies with insufficient trials are flagged
    # ``too_few_trials`` even if their tail happens to look flat.
    verdict: ConvergenceVerdict
    if total < STUDIES_TPE_WARMUP_FLOOR:
        verdict = "too_few_trials"
    elif improvement_in_window <= CONVERGENCE_FLAT_EPSILON:
        verdict = "converged"
    else:
        verdict = "still_improving"

    return ConvergenceShape(
        verdict=verdict,
        direction=direction,
        window_size=window_size,
        epsilon=CONVERGENCE_FLAT_EPSILON,
        warmup_floor=STUDIES_TPE_WARMUP_FLOOR,
        total_complete_trials=total,
        improvement_in_window=improvement_in_window,
        best_so_far_curve=curve,
    )


__all__ = [
    "CONVERGENCE_FLAT_EPSILON",
    "CONVERGENCE_FLAT_MIN_COMPLETE",
    "CONVERGENCE_FLAT_WINDOW",
    "ConvergenceShape",
    "ConvergenceVerdict",
    "CurvePoint",
    "classify_convergence",
]
