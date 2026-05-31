# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the chain-summary derivations (feat_overnight_autopilot Story 1.1).

Pure-domain tests — no DB, no fixtures. Each helper is exercised against
lightweight fake link/trial objects that expose only the attributes the
derivations read.

Covers spec §12 ACs that map to FR-3 (AC-5 through AC-10) plus the
maximize/minimize direction flip, the ``baseline_metric IS NULL``
first-decile fallback (and its ``None`` edge), the single-link aggregation
case, the empty-completed-subset case, the ``select_best_link`` tie-break,
and the ``delta_from_prev`` minimize sign-flip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.app.domain.study.chain_summary import (
    CHAIN_LIFT_EPSILON,
    CHAIN_STOP_REASONS,
    _direction_normalized_delta_from_prev,
    compute_cumulative_lift,
    derive_chain_stop_reason,
    select_best_link,
)


@dataclass
class FakeLink:
    """Minimal stand-in for a hydrated ``Study`` row."""

    id: str
    status: str = "completed"
    best_metric: float | None = None
    baseline_metric: float | None = None
    direction: str = "maximize"
    auto_followup_depth: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime(2026, 5, 31, tzinfo=UTC))

    @property
    def objective(self) -> dict[str, Any]:
        return {"direction": self.direction}

    @property
    def config(self) -> dict[str, Any]:
        if self.auto_followup_depth is None:
            return {}
        return {"auto_followup_depth": self.auto_followup_depth}


@dataclass
class FakeTrial:
    """Minimal stand-in for a hydrated ``Trial`` row (first-decile input)."""

    optuna_trial_number: int
    primary_metric: float | None


def _at(seconds: int) -> datetime:
    return datetime(2026, 5, 31, 0, 0, seconds, tzinfo=UTC)


# ---------------------------------------------------------------------------
# CHAIN_STOP_REASONS frozenset shape
# ---------------------------------------------------------------------------


def test_chain_stop_reasons_membership() -> None:
    assert CHAIN_STOP_REASONS == frozenset(
        {
            "depth_exhausted",
            "no_lift",
            "budget",
            "parent_failed",
            "cancelled",
            "in_flight",
        }
    )
    assert "unknown" not in CHAIN_STOP_REASONS  # D-6: no unknown wire value


# ---------------------------------------------------------------------------
# derive_chain_stop_reason — §9 decision matrix (AC-6..AC-10 + depth_exhausted)
# ---------------------------------------------------------------------------


def test_stop_reason_in_flight_when_any_link_running() -> None:
    # AC-8: a 2-link chain with the tail still running.
    anchor = FakeLink(id="s1", status="completed", best_metric=0.7, created_at=_at(1))
    tail = FakeLink(id="s2", status="running", created_at=_at(2))
    assert derive_chain_stop_reason([anchor, tail]) == "in_flight"


def test_stop_reason_in_flight_when_queued_anywhere() -> None:
    anchor = FakeLink(id="s1", status="queued", created_at=_at(1))
    tail = FakeLink(id="s2", status="completed", best_metric=0.7, created_at=_at(2))
    assert derive_chain_stop_reason([anchor, tail]) == "in_flight"


def test_stop_reason_cancelled() -> None:
    # AC-9: most-recent terminal link cancelled.
    anchor = FakeLink(id="s1", status="completed", best_metric=0.6, created_at=_at(1))
    mid = FakeLink(id="s2", status="completed", best_metric=0.7, created_at=_at(2))
    tail = FakeLink(id="s3", status="cancelled", created_at=_at(3))
    assert derive_chain_stop_reason([anchor, mid, tail]) == "cancelled"


def test_stop_reason_parent_failed() -> None:
    # AC-10: most-recent terminal link failed.
    anchor = FakeLink(id="s1", status="completed", best_metric=0.6, created_at=_at(1))
    mid = FakeLink(id="s2", status="completed", best_metric=0.7, created_at=_at(2))
    tail = FakeLink(id="s3", status="failed", created_at=_at(3))
    assert derive_chain_stop_reason([anchor, mid, tail]) == "parent_failed"


def test_stop_reason_depth_exhausted_depth_zero() -> None:
    # AC-7: tail completed with post-decrement depth 0.
    links = [
        FakeLink(
            id="s1", status="completed", best_metric=0.6, auto_followup_depth=2, created_at=_at(1)
        ),
        FakeLink(
            id="s2", status="completed", best_metric=0.7, auto_followup_depth=0, created_at=_at(2)
        ),
    ]
    assert derive_chain_stop_reason(links) == "depth_exhausted"


def test_stop_reason_depth_exhausted_depth_absent() -> None:
    # Tail completed with no auto_followup_depth key → depth_exhausted.
    tail = FakeLink(id="x", status="completed", best_metric=0.7)
    assert derive_chain_stop_reason([tail]) == "depth_exhausted"


def test_stop_reason_no_lift_below_epsilon_maximize() -> None:
    # AC-6 maximize: lift 0.001 <= epsilon 0.005 → no_lift.
    tail = FakeLink(
        id="t",
        status="completed",
        best_metric=0.601,
        baseline_metric=0.60,
        direction="maximize",
        auto_followup_depth=2,
    )
    anchor = FakeLink(id="a", status="completed", best_metric=0.60, created_at=_at(1))
    assert derive_chain_stop_reason([anchor, tail]) == "no_lift"


def test_stop_reason_no_lift_below_epsilon_minimize() -> None:
    # AC-6 minimize companion: post sign-flip lift 0.001 <= epsilon → no_lift.
    anchor = FakeLink(
        id="a", status="completed", best_metric=0.60, direction="minimize", created_at=_at(1)
    )
    tail = FakeLink(
        id="t",
        status="completed",
        best_metric=0.599,
        baseline_metric=0.60,
        direction="minimize",
        auto_followup_depth=2,
        created_at=_at(2),
    )
    assert derive_chain_stop_reason([anchor, tail]) == "no_lift"


def test_stop_reason_no_lift_best_metric_none() -> None:
    # Condition 5 (defensive): depth remaining but best_metric is None.
    tail = FakeLink(id="t", status="completed", best_metric=None, auto_followup_depth=2)
    assert derive_chain_stop_reason([tail]) == "no_lift"


def test_stop_reason_no_lift_no_usable_baseline() -> None:
    # Condition 6: depth remaining, best_metric set, but baseline NULL and no
    # anchor_trials → no usable first-decile → no_lift.
    tail = FakeLink(
        id="t", status="completed", best_metric=0.7, baseline_metric=None, auto_followup_depth=2
    )
    assert derive_chain_stop_reason([tail], anchor_trials=None) == "no_lift"


def test_stop_reason_budget_residual() -> None:
    # Condition 8: completed tail, depth remaining, lift > epsilon, no child →
    # budget (D-6 residual classification).
    anchor = FakeLink(id="a", status="completed", best_metric=0.60, created_at=_at(1))
    tail = FakeLink(
        id="t",
        status="completed",
        best_metric=0.80,
        baseline_metric=0.60,
        auto_followup_depth=2,
        created_at=_at(2),
    )
    assert derive_chain_stop_reason([anchor, tail]) == "budget"


def test_stop_reason_uses_first_decile_when_tail_baseline_null() -> None:
    # baseline_metric IS NULL → first-decile fallback from anchor_trials.
    # decile of 10 trials = 1 trial (the lowest optuna_trial_number); max over
    # the single-element decile = that trial's metric = 0.50. lift = 0.80 -
    # 0.50 = 0.30 > epsilon → budget (not no_lift).
    tail = FakeLink(
        id="t", status="completed", best_metric=0.80, baseline_metric=None, auto_followup_depth=2
    )
    trials = [FakeTrial(optuna_trial_number=i, primary_metric=0.50 + 0.01 * i) for i in range(10)]
    assert derive_chain_stop_reason([tail], anchor_trials=trials) == "budget"


# ---------------------------------------------------------------------------
# compute_cumulative_lift — universal formula (D-9) + AC-5 + direction flip
# ---------------------------------------------------------------------------


def test_cumulative_lift_single_link_completed() -> None:
    # AC-5: single-link, best 0.74, baseline 0.65 → 0.09 (universal formula).
    link = FakeLink(id="x", status="completed", best_metric=0.74, baseline_metric=0.65)
    lift = compute_cumulative_lift([link])
    assert lift is not None
    assert abs(lift - 0.09) < 1e-9


def test_cumulative_lift_three_link_chain() -> None:
    # AC-3: best at S3 (0.74), anchor baseline 0.60 → 0.14.
    s1 = FakeLink(
        id="s1", status="completed", best_metric=0.65, baseline_metric=0.60, created_at=_at(1)
    )
    s2 = FakeLink(id="s2", status="completed", best_metric=0.72, created_at=_at(2))
    s3 = FakeLink(id="s3", status="completed", best_metric=0.74, created_at=_at(3))
    lift = compute_cumulative_lift([s1, s2, s3])
    assert lift is not None
    assert abs(lift - 0.14) < 1e-9


def test_cumulative_lift_minimize_direction_flip() -> None:
    # minimize: best is the LOWEST metric; lift = baseline - best.
    # anchor baseline 0.60, best-of-completed 0.40 → lift 0.20.
    s1 = FakeLink(
        id="s1",
        status="completed",
        best_metric=0.55,
        baseline_metric=0.60,
        direction="minimize",
        created_at=_at(1),
    )
    s2 = FakeLink(
        id="s2", status="completed", best_metric=0.40, direction="minimize", created_at=_at(2)
    )
    lift = compute_cumulative_lift([s1, s2])
    assert lift is not None
    assert abs(lift - 0.20) < 1e-9


def test_cumulative_lift_none_when_completed_subset_empty() -> None:
    # In-flight tail, no completed link → None.
    link = FakeLink(id="x", status="running", best_metric=None, baseline_metric=0.65)
    assert compute_cumulative_lift([link]) is None


def test_cumulative_lift_first_decile_fallback() -> None:
    # anchor baseline NULL → first-decile of anchor_trials supplies the
    # comparison baseline. decile(10)=1 trial → max=0.50; best 0.74 → 0.24.
    anchor = FakeLink(id="a", status="completed", best_metric=0.74, baseline_metric=None)
    trials = [FakeTrial(optuna_trial_number=i, primary_metric=0.50 - 0.01 * i) for i in range(10)]
    lift = compute_cumulative_lift([anchor], anchor_trials=trials)
    assert lift is not None
    assert abs(lift - 0.24) < 1e-9


def test_cumulative_lift_none_when_first_decile_none() -> None:
    # anchor baseline NULL AND first-decile returns None (all primary_metric
    # NULL) → cumulative_lift None.
    anchor = FakeLink(id="a", status="completed", best_metric=0.74, baseline_metric=None)
    trials = [FakeTrial(optuna_trial_number=i, primary_metric=None) for i in range(10)]
    assert compute_cumulative_lift([anchor], anchor_trials=trials) is None


def test_cumulative_lift_none_when_no_baseline_and_no_trials() -> None:
    anchor = FakeLink(id="a", status="completed", best_metric=0.74, baseline_metric=None)
    assert compute_cumulative_lift([anchor], anchor_trials=None) is None


# ---------------------------------------------------------------------------
# select_best_link — argmax/argmin over completed subset (D-8) + tie-break
# ---------------------------------------------------------------------------


def test_select_best_link_maximize_argmax() -> None:
    s1 = FakeLink(id="s1", status="completed", best_metric=0.65, created_at=_at(1))
    s2 = FakeLink(id="s2", status="completed", best_metric=0.74, created_at=_at(2))
    s3 = FakeLink(id="s3", status="completed", best_metric=0.70, created_at=_at(3))
    assert select_best_link([s1, s2, s3]) == "s2"


def test_select_best_link_minimize_argmin() -> None:
    s1 = FakeLink(
        id="s1", status="completed", best_metric=0.65, direction="minimize", created_at=_at(1)
    )
    s2 = FakeLink(
        id="s2", status="completed", best_metric=0.40, direction="minimize", created_at=_at(2)
    )
    assert select_best_link([s1, s2]) == "s2"


def test_select_best_link_excludes_non_completed_and_null_metric() -> None:
    s1 = FakeLink(id="s1", status="running", best_metric=0.99, created_at=_at(1))
    s2 = FakeLink(id="s2", status="completed", best_metric=None, created_at=_at(2))
    s3 = FakeLink(id="s3", status="completed", best_metric=0.50, created_at=_at(3))
    assert select_best_link([s1, s2, s3]) == "s3"


def test_select_best_link_none_when_subset_empty() -> None:
    s1 = FakeLink(id="s1", status="running", best_metric=None, created_at=_at(1))
    assert select_best_link([s1]) is None


def test_select_best_link_tie_break_earliest_created_at() -> None:
    # Two completed links with identical best_metric → earlier created_at wins.
    early = FakeLink(id="zzz", status="completed", best_metric=0.70, created_at=_at(1))
    late = FakeLink(id="aaa", status="completed", best_metric=0.70, created_at=_at(5))
    assert select_best_link([late, early]) == "zzz"


def test_select_best_link_tie_break_id_when_created_at_equal() -> None:
    # Identical metric AND created_at → lowest id wins.
    a = FakeLink(id="aaa", status="completed", best_metric=0.70, created_at=_at(2))
    b = FakeLink(id="bbb", status="completed", best_metric=0.70, created_at=_at(2))
    assert select_best_link([b, a]) == "aaa"


# ---------------------------------------------------------------------------
# _direction_normalized_delta_from_prev
# ---------------------------------------------------------------------------


def test_delta_from_prev_maximize() -> None:
    delta = _direction_normalized_delta_from_prev(0.72, 0.65, "maximize")
    assert delta is not None
    assert abs(delta - 0.07) < 1e-9


def test_delta_from_prev_minimize_sign_flip() -> None:
    # minimize: improvement is prev - this. this=0.40, prev=0.55 → +0.15.
    delta = _direction_normalized_delta_from_prev(0.40, 0.55, "minimize")
    assert delta is not None
    assert abs(delta - 0.15) < 1e-9


def test_delta_from_prev_none_when_either_side_none() -> None:
    assert _direction_normalized_delta_from_prev(None, 0.65, "maximize") is None
    assert _direction_normalized_delta_from_prev(0.72, None, "maximize") is None


def test_chain_lift_epsilon_matches_gate_default() -> None:
    assert CHAIN_LIFT_EPSILON == 0.005
