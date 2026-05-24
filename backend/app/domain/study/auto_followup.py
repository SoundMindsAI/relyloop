"""Auto-followup chain gate (feat_auto_followup_studies Story 1.1).

Pure domain function deciding whether a completed study should enqueue
a follow-up. No DB, no I/O, no async.

Per spec FR-2a (and locked in D-3): the gate is "lift-over-first-decile."
The parent's winner must beat the max metric of the parent's earliest
decile of complete trials by at least ``epsilon`` (default 0.005). When
``feat_study_baseline_trial`` ships and populates ``studies.baseline_metric``,
FR-2b activates and this module switches to "lift-over-baseline" via a
one-line change in :func:`evaluate_chain_gate`.

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
from typing import Any


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


def compute_first_decile_max(complete_trials: Iterable[Any]) -> float | None:
    """Return max(primary_metric) over the first decile of complete trials.

    First decile = ``complete_trials_sorted[:max(1, len // 10)]`` (floor
    division, per spec FR-2a). Boundary cases:

    * len=0 → returns None
    * len=1..9 → first 1 trial (floor(N/10) = 0, clamped to 1)
    * len=10 → first 1 trial (10 // 10 = 1)
    * len=11..19 → first 1 trial (11 // 10 = 1, NOT ceil(11/10) = 2)
    * len=20 → first 2 trials

    Sort key is ``optuna_trial_number`` ASC — see module docstring for
    why this is the right ordering field.

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
    return max(metrics)


def evaluate_chain_gate(
    parent: Any,
    complete_trials: Iterable[Any],
    *,
    epsilon: float = 0.005,
) -> ChainGateOutcome:
    """Decide whether to enqueue a follow-up study for ``parent``.

    Inputs are loaded by the caller — this function does no I/O.

    Duck-typed signature (parent is Any) mirrors the
    :func:`backend.app.domain.study.confidence.compute_study_confidence`
    pattern at confidence.py:496 — lets tests pass ``SimpleNamespace``
    stand-ins without a Protocol class. Caller passes a real
    :class:`~backend.app.db.models.study.Study` in production; tests pass
    a SimpleNamespace with the required attributes
    (``status``, ``best_metric``, ``config``).

    Decision matrix (in evaluation order):

    1. ``parent.status in {'failed', 'cancelled'}`` → SKIP_PARENT_FAILED.
       Defensive: the digest worker doesn't run on failed studies
       (verified at backend/workers/orchestrator.py:452 — digest enqueue
       only fires from ``_stop()`` after the ``completed`` transition),
       so this branch fires only on manual invocation or race-with-cancel.
    2. ``config.auto_followup_depth`` missing or ``== 0`` →
       SKIP_DEPTH_EXHAUSTED. The depth=0 leaf (worker-set terminal value
       per FR-1 + D-12) hits this branch on its own enqueue invocation,
       which is how the chain ends.
    3. ``parent.best_metric is None`` → SKIP_NO_LIFT (cannot compute
       lift without a winner; defensive).
    4. ``first_decile_max`` is ``None`` (no usable trials) → SKIP_NO_LIFT.
    5. ``best_metric > first_decile_max + epsilon`` → ENQUEUE.
       Otherwise → SKIP_NO_LIFT.
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

    first_decile_max = compute_first_decile_max(complete_trials)
    if first_decile_max is None:
        return ChainGateOutcome(
            decision=ChainGateDecision.SKIP_NO_LIFT,
            lift=None,
            first_decile_max=None,
            epsilon=epsilon,
        )

    lift = parent.best_metric - first_decile_max
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
