# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Chain-summary derivation helpers (feat_overnight_autopilot Story 1.1).

Pure-Python domain logic for the rolled-up overnight-chain summary surfaced
by ``GET /api/v1/studies/{id}/chain`` (FR-3). No DB, no I/O, no async.

The three public derivations:

* :func:`derive_chain_stop_reason` — walks the §9 decision matrix
  (conditions 1-8, first match wins) against the chain's *tail* link and
  returns one of the six :data:`CHAIN_STOP_REASONS` wire values. There is
  no ``unknown`` value (decision D-6); the residual case classifies as
  ``"budget"``.
* :func:`compute_cumulative_lift` — the universal lift formula (D-9):
  ``best_of_completed.best_metric - anchor_baseline`` (direction-flipped
  for minimize), never short-circuited to ``0`` for single-link chains.
* :func:`select_best_link` — argmax/argmin over the completed-link subset
  (D-8), with a deterministic ``created_at ASC, id ASC`` tie-break.

All three reuse the direction-aware lift semantics + the first-decile
fallback from :mod:`backend.app.domain.study.auto_followup` rather than
duplicating them — the chain summary and ``evaluate_chain_gate`` share the
same comparison-point definitions so they never drift.
"""

from __future__ import annotations

from typing import Any, Literal

from backend.app.domain.study.auto_followup import (
    _direction_normalized_lift,
    compute_first_decile_max,
)

ChainStopReason = Literal[
    "depth_exhausted",
    "no_lift",
    "budget",
    "parent_failed",
    "cancelled",
    "in_flight",
]

#: Wire values for the chain summary's ``stop_reason`` field. The frontend
#: stop-reason mapping table (FR-4) MUST be grounded in this frozenset —
#: cite ``// Values must match backend/app/domain/study/chain_summary.py
#: CHAIN_STOP_REASONS``. No ``unknown`` value ships (decision D-6).
CHAIN_STOP_REASONS: frozenset[ChainStopReason] = frozenset(
    {
        "depth_exhausted",
        "no_lift",
        "budget",
        "parent_failed",
        "cancelled",
        "in_flight",
    }
)

#: Lift gate epsilon. Matches ``evaluate_chain_gate``'s default
#: (``auto_followup.py`` ``epsilon=0.005``) so the chain-summary derivation
#: and the gate agree on "no meaningful improvement."
CHAIN_LIFT_EPSILON: float = 0.005


def _direction_of(link: Any) -> Literal["maximize", "minimize"]:
    """Read a link's objective direction, defaulting to ``"maximize"``.

    Mirrors the pattern at ``studies.py:165`` — ``objective`` is a non-null
    JSONB dict but the ``direction`` key arrived with
    ``feat_study_baseline_trial`` so older rows may lack it.
    """
    direction = link.objective.get("direction", "maximize")
    return "minimize" if direction == "minimize" else "maximize"


def _tail_baseline(tail: Any, anchor_trials: list[Any] | None) -> float | None:
    """Resolve the tail's comparison baseline (FR-3 fallback).

    ``tail.baseline_metric`` when non-null, else the first-decile extremum
    of ``anchor_trials`` (the anchor's complete trials — only populated by
    the repo layer when the anchor's ``baseline_metric IS NULL``), else
    ``None``. Mirrors ``evaluate_chain_gate``'s FR-2a/FR-2b baseline
    resolution so the derivation never drifts from the gate.
    """
    if tail.baseline_metric is not None:
        return float(tail.baseline_metric)
    if anchor_trials:
        return compute_first_decile_max(anchor_trials, _direction_of(tail))
    return None


def derive_chain_stop_reason(
    links: list[Any],
    anchor_trials: list[Any] | None = None,
) -> ChainStopReason:
    """Derive the chain's ``stop_reason`` per the spec §9 decision matrix.

    ``links`` is ordered ``created_at ASC`` (anchor first); the tail is
    ``links[-1]``. Conditions 1-8 are evaluated in order and the first match
    wins. ``anchor_trials`` is consulted only when the tail's
    ``baseline_metric IS NULL`` (the first-decile fallback for conditions
    6 and 7).

    Returns one of :data:`CHAIN_STOP_REASONS`. There is no ``unknown`` value
    (D-6); the residual case (condition 8) classifies as ``"budget"``.
    """
    # Condition 1: any link still in flight → the chain isn't done.
    if any(link.status in {"queued", "running"} for link in links):
        return "in_flight"

    tail = links[-1]

    # Condition 2: tail cancelled.
    if tail.status == "cancelled":
        return "cancelled"

    # Condition 3: tail failed.
    if tail.status == "failed":
        return "parent_failed"

    # Conditions 4-8 only apply to a completed tail. Anything else (e.g. a
    # 'pruned'-style status that isn't in the studies CHECK) is defensively
    # treated as terminal-without-more — depth_exhausted.
    if tail.status != "completed":
        return "depth_exhausted"

    depth = tail.config.get("auto_followup_depth")

    # Condition 4: depth exhausted (None or post-decrement 0).
    if depth is None or depth == 0:
        return "depth_exhausted"

    # Condition 5: depth remaining but no winner metric (defensive — mirrors
    # evaluate_chain_gate's best_metric-is-None branch).
    if tail.best_metric is None:
        return "no_lift"

    # Condition 6: depth remaining but no usable baseline (no explicit
    # baseline + no usable first-decile).
    tail_baseline = _tail_baseline(tail, anchor_trials)
    if tail_baseline is None:
        return "no_lift"

    # Condition 7: depth remaining + baseline present but lift <= epsilon.
    lift = _direction_normalized_lift(tail.best_metric, tail_baseline, _direction_of(tail))
    if lift <= CHAIN_LIFT_EPSILON:
        return "no_lift"

    # Condition 8: residual — completed tail, depth remaining, lift gate
    # passed, yet no child enqueued. The documented approximation is
    # "budget" (D-6).
    return "budget"


def compute_cumulative_lift(
    links: list[Any],
    anchor_trials: list[Any] | None = None,
) -> float | None:
    """Return the chain's cumulative lift via the universal formula (D-9).

    ``best_of_completed.best_metric - anchor_baseline`` where:

    * ``best_of_completed`` is the best link in the completed-link subset
      (the same selection :func:`select_best_link` makes).
    * ``anchor_baseline`` is ``anchor.baseline_metric`` when non-null, else
      the first-decile extremum of ``anchor_trials``, else ``None``.

    The lift is direction-normalized (sign-flipped for minimize) so a
    positive value always means "better than the anchor's baseline."

    Returns ``None`` when the completed-link subset is empty OR no
    comparison baseline is derivable. Never short-circuited to ``0`` for
    single-link chains (D-9).
    """
    best_id = select_best_link(links)
    if best_id is None:
        return None
    best_link = next(link for link in links if link.id == best_id)
    if best_link.best_metric is None:  # pragma: no cover - guarded by select_best_link
        return None

    anchor = links[0]
    direction = _direction_of(anchor)
    if anchor.baseline_metric is not None:
        anchor_baseline: float | None = float(anchor.baseline_metric)
    elif anchor_trials:
        anchor_baseline = compute_first_decile_max(anchor_trials, direction)
    else:
        anchor_baseline = None

    if anchor_baseline is None:
        return None

    return _direction_normalized_lift(best_link.best_metric, anchor_baseline, direction)


def select_best_link(links: list[Any]) -> str | None:
    """Return the id of the best link in the completed-link subset (D-8).

    Subset = ``status == 'completed' AND best_metric IS NOT NULL``. Best =
    ``argmax(best_metric)`` (``argmin`` under minimize). Tie-break is
    deterministic: lowest (earliest) ``created_at``, then lowest ``id``.
    Direction is read from the anchor (``links[0]``) — linear chains share
    the anchor's direction.

    Returns ``None`` when the completed subset is empty.
    """
    completed = [
        link for link in links if link.status == "completed" and link.best_metric is not None
    ]
    if not completed:
        return None

    direction = _direction_of(links[0])
    # Sort by (metric, created_at, id) and pick the extremum. Under maximize
    # we want the largest metric → reverse the metric ordering; the
    # created_at/id tie-break stays ascending either way.
    if direction == "minimize":
        best = min(completed, key=lambda link: (link.best_metric, link.created_at, link.id))
    else:
        # Negate is unavailable for arbitrary comparables; use a two-stage
        # selection: take the max metric, then the earliest created_at/id
        # among ties.
        max_metric = max(link.best_metric for link in completed)
        tied = [link for link in completed if link.best_metric == max_metric]
        best = min(tied, key=lambda link: (link.created_at, link.id))
    return str(best.id)


def _direction_normalized_delta_from_prev(
    this_metric: float | None,
    prev_metric: float | None,
    direction: Literal["maximize", "minimize"],
) -> float | None:
    """Return ``this - prev`` (sign-flipped for minimize), or ``None``.

    ``None`` when either side is ``None``. Used by the router to populate
    each link's ``delta_from_prev`` (the anchor's is forced to ``None``
    separately per spec §8.3).
    """
    if this_metric is None or prev_metric is None:
        return None
    return _direction_normalized_lift(this_metric, prev_metric, direction)
