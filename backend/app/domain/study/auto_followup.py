"""Auto-followup chain gate (feat_auto_followup_studies Story 1.1).

Pure domain function deciding whether a completed study should enqueue
a follow-up. No DB, no I/O, no async.

Per spec FR-2a (and locked in D-3): the gate is "lift-over-first-decile"
when no explicit baseline exists. **FR-2b activated** by
``feat_study_baseline_trial`` (2026-05-25): when
``parent.baseline_metric IS NOT NULL`` (i.e., the orchestrator's baseline
phase ran and successfully stamped the study), lift is computed directly
against the explicit baseline. Otherwise the existing implicit-baseline
(first-decile-max) fallback fires unchanged.

**Direction-aware** (feat_study_baseline_trial FR-5): the gate now takes
a ``direction: Literal["maximize", "minimize"]`` kwarg (default
``"maximize"`` preserves the existing behavior). For minimize objectives,
lift signs flip so "better than baseline" is always positive — closes
a latent bug in the maximize-only implementation when minimize studies
land. ``ChainGateOutcome.first_decile_max`` is the legacy name kept for
backward compatibility; conceptually it's now the "first-decile extremum"
(max for maximize, min for minimize). Existing callers can rely on the
field name and the maximize-default; direction-aware callers pass
``parent.objective.get('direction')``.

Ordering note: the spec/plan referenced ``created_at`` for trial sorting,
but :class:`~backend.app.db.models.trial.Trial` exposes ``started_at``
(nullable) and ``optuna_trial_number`` (monotonic per-study, never NULL).
``optuna_trial_number`` is the canonical "trial order within the study"
field (assigned at ``study.ask().number`` time before enqueue), so
:func:`compute_first_decile_max` sorts by it — earlier numbers = earlier
trials in the optimizer's exploration. The first decile thus captures
the random-sampling phase before TPE's exploit kicks in, which is the
implicit-baseline semantics FR-2a wants.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal


class ChainGateDecision(StrEnum):
    """What :func:`evaluate_chain_gate` decided.

    One value per terminating branch. The caller (:func:`backend.workers.
    auto_followup.enqueue_followup_study`) dispatches on the value and emits
    the matching FR-9 telemetry event.
    """

    ENQUEUE = "enqueue"
    SKIP_NO_LIFT = "skip_no_lift"
    SKIP_PARENT_FAILED = "skip_parent_failed"
    SKIP_DEPTH_EXHAUSTED = "skip_depth_exhausted"


@dataclass(frozen=True)
class ChainGateOutcome:
    """Result of the gate evaluation.

    ``lift`` is ``best_metric - first_decile_max`` when ENQUEUE or
    SKIP_NO_LIFT; ``None`` otherwise. ``first_decile_max`` is populated
    whenever the first-decile computation ran (ENQUEUE / SKIP_NO_LIFT).
    """

    decision: ChainGateDecision
    lift: float | None = None
    first_decile_max: float | None = None
    epsilon: float = 0.005


def compute_first_decile_max(
    complete_trials: Iterable[Any],
    direction: Literal["maximize", "minimize"] = "maximize",
) -> float | None:
    """Return the first-decile extremum of complete trials' primary_metric.

    First decile = ``complete_trials_sorted[:max(1, len // 10)]`` (floor
    division, per spec FR-2a). Boundary cases:

    * len=0 → returns None
    * len=1..9 → first 1 trial (floor(N/10) = 0, clamped to 1)
    * len=10 → first 1 trial (10 // 10 = 1)
    * len=11..19 → first 1 trial (11 // 10 = 1, NOT ceil(11/10) = 2)
    * len=20 → first 2 trials

    Sort key is ``optuna_trial_number`` ASC — see module docstring for
    why this is the right ordering field.

    For ``direction='maximize'`` (the default, preserving existing
    behavior) returns ``max(primary_metric)`` over the decile. For
    ``direction='minimize'`` returns ``min(primary_metric)`` — i.e., the
    most-easily-beaten value, which is the right baseline-shaped
    comparison point under minimize semantics (feat_study_baseline_trial
    FR-5).

    Returns ``None`` when the first-decile slice has no usable
    ``primary_metric`` values (all NULL, or zero trials).
    """
    sorted_trials = sorted(complete_trials, key=lambda t: t.optuna_trial_number)
    n = len(sorted_trials)
    if n == 0:
        return None
    decile_size = max(1, n // 10)
    decile = sorted_trials[:decile_size]
    metrics: list[float] = [t.primary_metric for t in decile if t.primary_metric is not None]
    if not metrics:
        return None
    return max(metrics) if direction == "maximize" else min(metrics)


def evaluate_chain_gate(
    parent: Any,
    complete_trials: Iterable[Any],
    *,
    epsilon: float = 0.005,
    direction: Literal["maximize", "minimize"] = "maximize",
) -> ChainGateOutcome:
    """Decide whether to enqueue a follow-up study for ``parent``.

    Inputs are loaded by the caller — this function does no I/O.

    **feat_study_baseline_trial FR-5 activation**: when
    ``parent.baseline_metric IS NOT NULL`` (the orchestrator's baseline
    phase stamped the study), lift is computed directly against the
    explicit baseline. Otherwise the existing first-decile fallback
    fires unchanged. ``ChainGateOutcome.first_decile_max`` is populated
    ONLY when the fallback branch ran; the explicit-baseline branch
    leaves it ``None`` (and the ``lift`` field carries the
    explicit-baseline computation).

    **Direction-aware** (FR-5): the ``direction`` kwarg flips lift signs
    for minimize objectives so the ``lift > epsilon`` gate predicate
    works the same for both directions. Default ``"maximize"`` preserves
    backward compatibility — existing callers that don't pass
    ``direction`` continue to work.

    Decision matrix (in evaluation order):

    1. ``parent.status in {'failed', 'cancelled'}`` → SKIP_PARENT_FAILED.
    2. ``config.auto_followup_depth`` missing or ``== 0`` → SKIP_DEPTH_EXHAUSTED.
    3. ``parent.best_metric is None`` → SKIP_NO_LIFT (defensive).
    4. **Explicit baseline (FR-5)**: ``parent.baseline_metric IS NOT NULL`` →
       ``lift = (best - baseline)`` (maximize) or ``(baseline - best)``
       (minimize). Gate on ``lift > epsilon``.
    5. **Fallback**: ``first_decile_max`` is ``None`` → SKIP_NO_LIFT.
    6. Direction-normalized lift over first-decile extremum.
    """
    if parent.status in {"failed", "cancelled"}:
        return ChainGateOutcome(
            decision=ChainGateDecision.SKIP_PARENT_FAILED,
            epsilon=epsilon,
        )

    depth = parent.config.get("auto_followup_depth")
    if depth is None or depth == 0:
        return ChainGateOutcome(
            decision=ChainGateDecision.SKIP_DEPTH_EXHAUSTED,
            epsilon=epsilon,
        )

    if parent.best_metric is None:
        return ChainGateOutcome(
            decision=ChainGateDecision.SKIP_NO_LIFT,
            lift=None,
            first_decile_max=None,
            epsilon=epsilon,
        )

    # FR-5: explicit-baseline branch — prefer parent.baseline_metric when set.
    baseline_metric = getattr(parent, "baseline_metric", None)
    if baseline_metric is not None:
        lift = _direction_normalized_lift(parent.best_metric, baseline_metric, direction)
        if lift > epsilon:
            return ChainGateOutcome(
                decision=ChainGateDecision.ENQUEUE,
                lift=lift,
                first_decile_max=None,  # explicit-baseline branch — no decile compute
                epsilon=epsilon,
            )
        return ChainGateOutcome(
            decision=ChainGateDecision.SKIP_NO_LIFT,
            lift=lift,
            first_decile_max=None,
            epsilon=epsilon,
        )

    # Fallback: first-decile-extremum (implicit baseline, direction-aware).
    first_decile_max = compute_first_decile_max(complete_trials, direction)
    if first_decile_max is None:
        return ChainGateOutcome(
            decision=ChainGateDecision.SKIP_NO_LIFT,
            lift=None,
            first_decile_max=None,
            epsilon=epsilon,
        )

    lift = _direction_normalized_lift(parent.best_metric, first_decile_max, direction)
    if lift > epsilon:
        return ChainGateOutcome(
            decision=ChainGateDecision.ENQUEUE,
            lift=lift,
            first_decile_max=first_decile_max,
            epsilon=epsilon,
        )
    return ChainGateOutcome(
        decision=ChainGateDecision.SKIP_NO_LIFT,
        lift=lift,
        first_decile_max=first_decile_max,
        epsilon=epsilon,
    )


def _direction_normalized_lift(
    best_metric: float,
    baseline_metric: float,
    direction: Literal["maximize", "minimize"],
) -> float:
    """Normalize lift sign so "better than baseline" is always positive."""
    if direction == "minimize":
        return baseline_metric - best_metric
    return best_metric - baseline_metric
