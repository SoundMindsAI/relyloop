# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.app.domain.study.auto_followup`` (Story 1.1).

Pure tests — no DB, no fixtures beyond SimpleNamespace stand-ins for
Study / Trial ORM rows (consistent with backend/tests/unit/domain/study/
test_confidence.py pattern). The chain gate is a pure function, so
fixtures stay minimal.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.domain.study.auto_followup import (
    AUTO_FOLLOWUP_LIFT_EPSILON,
    ChainGateDecision,
    ChainGateOutcome,
    compute_first_decile_max,
    evaluate_chain_gate,
)


def _trial(*, num: int, metric: float | None) -> SimpleNamespace:
    """Build a Trial stand-in. Only ``optuna_trial_number`` and
    ``primary_metric`` are read by the domain function."""
    return SimpleNamespace(optuna_trial_number=num, primary_metric=metric)


def _study(
    *,
    status: str = "completed",
    best_metric: float | None = 0.5,
    auto_followup_depth: int | None = 3,
    baseline_metric: float | None = None,
) -> SimpleNamespace:
    """Build a Study stand-in. The domain function reads ``status``,
    ``best_metric``, ``config[auto_followup_depth]``, and (post-
    feat_study_baseline_trial) ``baseline_metric``."""
    return SimpleNamespace(
        status=status,
        best_metric=best_metric,
        baseline_metric=baseline_metric,
        config={"auto_followup_depth": auto_followup_depth},
    )


# ---------------------------------------------------------------------------
# compute_first_decile_max
# ---------------------------------------------------------------------------


class TestComputeFirstDecileMax:
    def test_empty_list_returns_none(self) -> None:
        assert compute_first_decile_max([]) is None

    def test_single_trial_uses_only_that_trial(self) -> None:
        # len=1 → floor(1/10)=0, clamped to 1 → first 1 trial
        trials = [_trial(num=0, metric=0.42)]
        assert compute_first_decile_max(trials) == 0.42

    def test_nine_trials_uses_first_one(self) -> None:
        # len=9 → floor(9/10)=0, clamped to 1 → first 1 trial
        trials = [_trial(num=i, metric=float(i)) for i in range(9)]
        assert compute_first_decile_max(trials) == 0.0  # first trial (num=0)

    def test_ten_trials_uses_first_one(self) -> None:
        # len=10 → floor(10/10)=1 → first 1 trial
        trials = [_trial(num=i, metric=float(i)) for i in range(10)]
        assert compute_first_decile_max(trials) == 0.0

    def test_eleven_trials_still_uses_first_one_floor_not_ceil(self) -> None:
        # Critical boundary: ceil(11/10)=2, floor=1. Spec FR-2a is floor.
        # If this fails, the algorithm regressed to ceil.
        trials = [_trial(num=i, metric=float(i)) for i in range(11)]
        assert compute_first_decile_max(trials) == 0.0

    def test_twenty_trials_uses_first_two(self) -> None:
        # len=20 → floor(20/10)=2 → first 2 trials
        trials = [_trial(num=i, metric=float(i)) for i in range(20)]
        # max of trial 0 (metric 0.0) and trial 1 (metric 1.0) = 1.0
        assert compute_first_decile_max(trials) == 1.0

    def test_unsorted_input_is_sorted_by_optuna_trial_number(self) -> None:
        # Pass trials out of order; the function sorts internally.
        trials = [
            _trial(num=5, metric=0.99),  # late trial — not in first decile
            _trial(num=0, metric=0.10),  # first trial — IS in first decile
            _trial(num=1, metric=0.20),
            _trial(num=2, metric=0.30),
            _trial(num=3, metric=0.40),
            _trial(num=4, metric=0.50),
            _trial(num=6, metric=0.60),
            _trial(num=7, metric=0.70),
            _trial(num=8, metric=0.80),
            _trial(num=9, metric=0.90),
            _trial(num=10, metric=0.95),  # len=11 → first 1 → trial num=0 → metric=0.10
        ]
        assert compute_first_decile_max(trials) == 0.10

    def test_all_none_metrics_in_decile_returns_none(self) -> None:
        trials = [_trial(num=0, metric=None), _trial(num=1, metric=None)]
        assert compute_first_decile_max(trials) is None

    def test_partial_none_metrics_in_decile_skips_them(self) -> None:
        # len=20 → first 2 trials. trial 0 has None, trial 1 has 0.5 → max=0.5.
        trials = [_trial(num=0, metric=None), _trial(num=1, metric=0.5)]
        trials += [_trial(num=i, metric=0.9) for i in range(2, 20)]
        assert compute_first_decile_max(trials) == 0.5

    def test_minimize_returns_min_not_max(self) -> None:
        """feat_study_baseline_trial FR-5: direction-aware extremum."""
        trials = [_trial(num=0, metric=0.5), _trial(num=1, metric=0.2)]
        trials += [_trial(num=i, metric=0.9) for i in range(2, 20)]
        # len=20 → first 2 trials. Maximize: max(0.5, 0.2) = 0.5.
        assert compute_first_decile_max(trials, "maximize") == 0.5
        # Minimize: min(0.5, 0.2) = 0.2.
        assert compute_first_decile_max(trials, "minimize") == 0.2


# ---------------------------------------------------------------------------
# evaluate_chain_gate
# ---------------------------------------------------------------------------


class TestEvaluateChainGateBaselineBranch:
    """feat_study_baseline_trial FR-5: explicit-baseline branch."""

    def test_baseline_branch_enqueues_when_lift_exceeds_epsilon(self) -> None:
        """AC-7: parent.baseline_metric set → lift = best - baseline."""
        parent = _study(best_metric=0.65, baseline_metric=0.55, auto_followup_depth=3)
        # complete_trials is irrelevant when baseline_metric is set.
        outcome = evaluate_chain_gate(parent, [], direction="maximize")
        assert outcome.decision is ChainGateDecision.ENQUEUE
        assert outcome.lift == pytest.approx(0.10)
        # first_decile_max is None when the explicit-baseline branch fires.
        assert outcome.first_decile_max is None

    def test_baseline_branch_skips_when_lift_within_epsilon(self) -> None:
        parent = _study(best_metric=0.553, baseline_metric=0.55, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, [], direction="maximize")
        assert outcome.decision is ChainGateDecision.SKIP_NO_LIFT
        assert outcome.lift == pytest.approx(0.003)
        assert outcome.first_decile_max is None

    def test_fallback_to_first_decile_when_baseline_metric_is_none(self) -> None:
        """AC-8: baseline_metric=None → falls back to first-decile."""
        trials = [_trial(num=i, metric=0.30) for i in range(20)]
        parent = _study(best_metric=0.65, baseline_metric=None, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials, direction="maximize")
        assert outcome.decision is ChainGateDecision.ENQUEUE
        assert outcome.lift == pytest.approx(0.35)
        assert outcome.first_decile_max == 0.30


class TestEvaluateChainGateDirectionAware:
    """feat_study_baseline_trial FR-5 / AC-18."""

    def test_minimize_direction_with_baseline(self) -> None:
        """AC-18: minimize objective inverts lift sign so 'better than
        baseline' is always positive."""
        # Lower is better. winner 0.30 beats baseline 0.50 by 0.20.
        parent = _study(best_metric=0.30, baseline_metric=0.50, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, [], direction="minimize")
        assert outcome.decision is ChainGateDecision.ENQUEUE
        assert outcome.lift == pytest.approx(0.20)

    def test_minimize_direction_with_first_decile_fallback(self) -> None:
        """Minimize + first-decile fallback: extremum is min, lift is
        first_decile_min - best."""
        # First decile of 20 trials → first 2 trials.
        trials = [_trial(num=0, metric=0.5), _trial(num=1, metric=0.4)]
        trials += [_trial(num=i, metric=0.1) for i in range(2, 20)]
        # Minimize: first_decile_min = 0.4. winner = 0.10 beats by 0.30.
        parent = _study(best_metric=0.10, baseline_metric=None, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials, direction="minimize")
        assert outcome.decision is ChainGateDecision.ENQUEUE
        assert outcome.lift == pytest.approx(0.30)
        assert outcome.first_decile_max == 0.4  # the min in minimize mode

    def test_maximize_default_preserves_backward_compat(self) -> None:
        """No direction kwarg → defaults to maximize (existing behavior)."""
        trials = [_trial(num=i, metric=0.30) for i in range(20)]
        parent = _study(best_metric=0.42, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.ENQUEUE
        assert outcome.lift == pytest.approx(0.12)


class TestEvaluateChainGate:
    def test_lift_above_epsilon_returns_enqueue(self) -> None:
        # parent.best_metric=0.42, first_decile_max=0.30, lift=0.12 > epsilon=0.005
        trials = [_trial(num=i, metric=0.30) for i in range(20)]  # decile max = 0.30
        parent = _study(best_metric=0.42, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.ENQUEUE
        assert outcome.lift == pytest.approx(0.12)
        assert outcome.first_decile_max == 0.30
        assert outcome.epsilon == 0.005

    def test_lift_within_epsilon_returns_skip_no_lift(self) -> None:
        # parent.best_metric=0.302, first_decile_max=0.30, lift=0.002 ≤ epsilon=0.005
        trials = [_trial(num=i, metric=0.30) for i in range(20)]
        parent = _study(best_metric=0.302, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.SKIP_NO_LIFT
        assert outcome.lift == pytest.approx(0.002)
        assert outcome.first_decile_max == 0.30

    def test_status_failed_returns_skip_parent_failed(self) -> None:
        trials = [_trial(num=i, metric=0.30) for i in range(20)]
        parent = _study(status="failed", best_metric=0.42, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.SKIP_PARENT_FAILED
        # Defensive — lift/first_decile not computed when parent failed.
        assert outcome.lift is None

    def test_status_cancelled_returns_skip_parent_failed_defensive(self) -> None:
        trials = [_trial(num=i, metric=0.30) for i in range(20)]
        parent = _study(status="cancelled", best_metric=0.42, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.SKIP_PARENT_FAILED

    def test_depth_zero_returns_skip_depth_exhausted(self) -> None:
        # Depth-0 leaf hits this branch on its OWN enqueue invocation —
        # how the chain ends.
        trials = [_trial(num=i, metric=0.30) for i in range(20)]
        parent = _study(best_metric=0.42, auto_followup_depth=0)
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.SKIP_DEPTH_EXHAUSTED

    def test_depth_none_returns_skip_depth_exhausted_defensive(self) -> None:
        # Shouldn't fire — digest worker gates on `is not None` — but defensive.
        trials = [_trial(num=i, metric=0.30) for i in range(20)]
        parent = SimpleNamespace(
            status="completed", best_metric=0.42, config={}
        )  # no auto_followup_depth key
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.SKIP_DEPTH_EXHAUSTED

    def test_best_metric_none_returns_skip_no_lift_cycle1_finding_c1_15(self) -> None:
        # Cannot compute lift without a winner. Defensive.
        trials = [_trial(num=i, metric=0.30) for i in range(20)]
        parent = _study(best_metric=None, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.SKIP_NO_LIFT
        assert outcome.lift is None
        assert outcome.first_decile_max is None

    def test_empty_complete_trials_returns_skip_no_lift(self) -> None:
        # No trials → no decile → cannot compute baseline.
        parent = _study(best_metric=0.42, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, [])
        assert outcome.decision is ChainGateDecision.SKIP_NO_LIFT
        assert outcome.first_decile_max is None

    def test_eleven_trials_floor_boundary(self) -> None:
        # Floor-vs-ceil regression guard at the integration layer:
        # 11 complete trials → first decile = 1 trial (not 2).
        # If first trial has metric=0.30 and parent's best=0.36, lift=0.06 > epsilon.
        # If algorithm regressed to ceil, decile would be 2 trials and
        # the second trial (metric=0.99) would be in the decile, making
        # first_decile_max=0.99 and parent's 0.36 NOT win — skip.
        trials = [_trial(num=0, metric=0.30)]
        trials.append(_trial(num=1, metric=0.99))  # ceil-bug detector
        trials += [_trial(num=i, metric=0.50) for i in range(2, 11)]
        parent = _study(best_metric=0.36, auto_followup_depth=3)
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.decision is ChainGateDecision.ENQUEUE
        assert outcome.first_decile_max == 0.30  # NOT 0.99
        assert outcome.lift == pytest.approx(0.06)

    def test_outcome_carries_epsilon(self) -> None:
        # Custom epsilon plumbs through to the outcome.
        trials = [_trial(num=0, metric=0.30)]
        parent = _study(best_metric=0.50, auto_followup_depth=2)
        outcome = evaluate_chain_gate(parent, trials, epsilon=0.1)
        assert outcome.epsilon == 0.1
        assert outcome.decision is ChainGateDecision.ENQUEUE  # 0.50 - 0.30 = 0.20 > 0.1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Convenience: assert outcome equality including frozen-dataclass repr
def test_chain_gate_outcome_is_frozen() -> None:
    outcome = ChainGateOutcome(decision=ChainGateDecision.ENQUEUE)
    try:
        outcome.decision = ChainGateDecision.SKIP_NO_LIFT  # type: ignore[misc]
    except Exception:  # noqa: BLE001
        return
    raise AssertionError("ChainGateOutcome should be frozen (immutable)")


# ---------------------------------------------------------------------------
# feat_study_convergence_indicator Story 1.1 — epsilon hoist value-lock
# ---------------------------------------------------------------------------


class TestAutoFollowupLiftEpsilonHoist:
    """Story 1.1 value-lock: the module-level ``AUTO_FOLLOWUP_LIFT_EPSILON``
    constant exists, equals 0.005, and is the value both the dataclass
    field default and the ``evaluate_chain_gate`` kwarg default resolve
    to. Uses value equality (``==``) per plan §0 — never ``is``."""

    def test_constant_equals_legacy_literal(self) -> None:
        assert AUTO_FOLLOWUP_LIFT_EPSILON == 0.005

    def test_dataclass_field_default_matches_constant(self) -> None:
        outcome = ChainGateOutcome(decision=ChainGateDecision.ENQUEUE)
        assert outcome.epsilon == AUTO_FOLLOWUP_LIFT_EPSILON
        assert outcome.epsilon == 0.005

    def test_evaluate_chain_gate_kwarg_default_matches_constant(self) -> None:
        # The kwarg default flows into the returned outcome's ``epsilon``
        # field. Driving evaluate_chain_gate without passing ``epsilon=``
        # asserts the kwarg default resolves to the hoisted constant.
        parent = _study(best_metric=0.6)
        # 50 trials, all metric 0.4 → first_decile_max = 0.4, lift = 0.2 > 0.005 → ENQUEUE
        trials = [_trial(num=i, metric=0.4) for i in range(50)]
        outcome = evaluate_chain_gate(parent, trials)
        assert outcome.epsilon == AUTO_FOLLOWUP_LIFT_EPSILON
        assert outcome.epsilon == 0.005
