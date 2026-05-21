"""Unit tests for ``backend.app.domain.study.confidence`` (Story 1.3).

Covers every helper and every FR-7 degraded path. Pure tests — no DB, no
fixtures beyond simple data structures. The orchestrator
(:func:`compute_study_confidence`) is tested with lightweight ``SimpleNamespace``
stand-ins for ``Trial`` / ``Study`` ORM rows since the orchestrator only reads
attributes, not behavior.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.domain.study.confidence import (
    BOOTSTRAP_MIN_N_QUERIES,
    CONVERGENCE_MIN_COMPLETE,
    LATE_TRIAL_MIN_COMPLETE,
    REGRESSOR_THRESHOLDS,
    RUNNER_UP_GAP_MIN_COMPLETE,
    RUNNER_UP_PLATEAU_BAND,
    TOP_REGRESSORS_CAP,
    ConfidenceShape,
    bootstrap_ci_95,
    build_regressor_rows,
    classify_convergence_regime,
    classify_runner_up_gap,
    compute_late_trial_stddev,
    compute_outcome_summary,
    compute_study_confidence,
)

# ---------------------------------------------------------------------------
# bootstrap_ci_95
# ---------------------------------------------------------------------------


class TestBootstrapCI:
    def test_returns_none_when_n_below_threshold(self) -> None:
        """AC-15: N(queries) < 5 suppresses ci_95."""
        assert bootstrap_ci_95([0.5, 0.6, 0.7, 0.8]) is None
        assert bootstrap_ci_95([]) is None

    def test_returns_shape_when_n_meets_threshold(self) -> None:
        """At exactly BOOTSTRAP_MIN_N_QUERIES the CI is computable."""
        values = [0.5, 0.6, 0.7, 0.8, 0.9]
        result = bootstrap_ci_95(values)
        assert result is not None
        assert result.n_samples == len(values)
        assert result.method == "bootstrap_n1000"
        # CI must straddle the sample mean.
        sample_mean = sum(values) / len(values)
        assert result.low <= sample_mean <= result.high

    def test_seed_determinism_byte_identical(self) -> None:
        """AC-4: two calls with identical input produce byte-identical CI
        values (fixed seed = 42)."""
        values = [0.78, 0.82, 0.85, 0.80, 0.84, 0.79, 0.83, 0.81, 0.77, 0.86]
        first = bootstrap_ci_95(values)
        second = bootstrap_ci_95(values)
        assert first is not None
        assert second is not None
        assert first.low == second.low
        assert first.high == second.high

    def test_zero_variance_collapses_ci(self) -> None:
        """All-equal input → CI collapses to the constant value."""
        values = [0.5] * 10
        result = bootstrap_ci_95(values)
        assert result is not None
        assert result.low == pytest.approx(0.5)
        assert result.high == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# classify_runner_up_gap
# ---------------------------------------------------------------------------


class TestRunnerUpGap:
    def test_returns_none_below_min_complete(self) -> None:
        """FR-7: < RUNNER_UP_GAP_MIN_COMPLETE (2) → None."""
        assert classify_runner_up_gap([0.8]) is None
        assert classify_runner_up_gap([]) is None

    def test_robust_plateau_when_top10_within_band(self) -> None:
        """AC-5: top-10 all within 0.005 → robust_plateau."""
        # Winner 0.840, top-10 all within 0.004 (strictly less than the 0.005
        # band — avoids float-precision flake at the boundary).
        metrics = [0.840, 0.838, 0.838, 0.837, 0.839, 0.838, 0.838, 0.838, 0.837, 0.836]
        result = classify_runner_up_gap(metrics)
        assert result is not None
        assert result.classification == "robust_plateau"
        assert result.value == pytest.approx(0.002)
        assert result.runner_up_metric == pytest.approx(0.838)
        assert result.top10_within <= RUNNER_UP_PLATEAU_BAND

    def test_sharp_peak_when_gap_exceeds_band(self) -> None:
        """AC-5 counter-example: gap > 0.005 → sharp_peak."""
        metrics = [0.840, 0.760, 0.750, 0.740]
        result = classify_runner_up_gap(metrics)
        assert result is not None
        assert result.classification == "sharp_peak"
        assert result.value == pytest.approx(0.080)
        assert result.runner_up_metric == pytest.approx(0.760)
        assert result.top10_within > RUNNER_UP_PLATEAU_BAND

    def test_two_trial_edge_case(self) -> None:
        """At exactly 2 trials (minimum), classification still computes from
        the winner-vs-runner_up gap."""
        # 2 trials, gap = 0.001 → robust_plateau (within 0.005).
        result = classify_runner_up_gap([0.840, 0.839])
        assert result is not None
        assert result.classification == "robust_plateau"

        # 2 trials, gap = 0.10 → sharp_peak.
        result = classify_runner_up_gap([0.840, 0.740])
        assert result is not None
        assert result.classification == "sharp_peak"


# ---------------------------------------------------------------------------
# compute_late_trial_stddev
# ---------------------------------------------------------------------------


class TestLateTrialStddev:
    def test_returns_none_when_n_below_threshold(self) -> None:
        """FR-7 + AC-7: < LATE_TRIAL_MIN_COMPLETE (10) → None."""
        assert compute_late_trial_stddev([0.5] * 9) is None
        assert compute_late_trial_stddev([]) is None

    def test_window_size_at_n_50(self) -> None:
        """AC-6: at N=50, window = max(5, int(50*0.2)) = 10."""
        values = [0.7 + 0.01 * (i % 5) for i in range(50)]
        result = compute_late_trial_stddev(values)
        assert result is not None
        assert result.window_size == 10
        assert result.min_window_required == LATE_TRIAL_MIN_COMPLETE

    def test_window_size_floor_at_5(self) -> None:
        """N=10 → window = max(5, int(10*0.2)) = 5 (the floor)."""
        values = [0.7] * 10
        result = compute_late_trial_stddev(values)
        assert result is not None
        assert result.window_size == 5
        assert result.value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# classify_convergence_regime
# ---------------------------------------------------------------------------


class TestConvergenceRegime:
    def test_returns_none_below_min_complete(self) -> None:
        """FR-7: < CONVERGENCE_MIN_COMPLETE (3) → None."""
        result = classify_convergence_regime(
            winner_trial_number=0,
            primary_metrics_by_trial_number={0: 0.8, 1: 0.7},
        )
        assert result is None

    def test_early_held_when_late_trial_within_band(self) -> None:
        """AC-8: winner at 20% AND ≥1 late-window trial within 0.005 → early_held."""
        # Winner at trial 200 out of 1000; late window is trial >= 750.
        # Synthesize: winner 0.840, late trials include 0.838 (within 0.005).
        metrics_by_trial = {0: 0.700}
        metrics_by_trial[200] = 0.840  # winner
        # Mid trials.
        for tn in range(250, 750, 50):
            metrics_by_trial[tn] = 0.820
        # Late trials, at least one within 0.005 of winner.
        metrics_by_trial[800] = 0.838
        metrics_by_trial[900] = 0.825
        metrics_by_trial[1000] = 0.830

        result = classify_convergence_regime(
            winner_trial_number=200,
            primary_metrics_by_trial_number=metrics_by_trial,
        )
        assert result is not None
        assert result.regime == "early_held"
        assert result.best_at_trial == 200
        assert result.total_trials == len(metrics_by_trial)

    def test_late_rising_at_90pct(self) -> None:
        """AC-9: winner at 95% → late_rising."""
        metrics_by_trial = {tn: 0.700 + 0.001 * tn for tn in range(0, 1001, 50)}
        # Winner at 950 — above 90%.
        metrics_by_trial[950] = 0.860
        result = classify_convergence_regime(
            winner_trial_number=950,
            primary_metrics_by_trial_number=metrics_by_trial,
        )
        assert result is not None
        assert result.regime == "late_rising"

    def test_noisy_when_winner_early_but_no_late_plateau(self) -> None:
        """AC-8 counter-example: winner at 20% but NO late trial within 0.005
        → noisy (late budget didn't find similar plateau)."""
        metrics_by_trial = {tn: 0.700 for tn in range(0, 1001, 50)}
        metrics_by_trial[200] = 0.840  # winner — far from late trials
        # All late trials (>= 750) are at 0.700, gap = 0.140 (far from 0.005).
        result = classify_convergence_regime(
            winner_trial_number=200,
            primary_metrics_by_trial_number=metrics_by_trial,
        )
        assert result is not None
        assert result.regime == "noisy"

    def test_noisy_when_winner_in_middle(self) -> None:
        """Winner at 60% (neither early nor late) → noisy."""
        metrics_by_trial = {tn: 0.700 for tn in range(0, 1001, 50)}
        metrics_by_trial[600] = 0.840
        result = classify_convergence_regime(
            winner_trial_number=600,
            primary_metrics_by_trial_number=metrics_by_trial,
        )
        assert result is not None
        assert result.regime == "noisy"


# ---------------------------------------------------------------------------
# compute_outcome_summary + build_regressor_rows
# ---------------------------------------------------------------------------


class TestOutcomeSummary:
    def test_returns_none_on_empty_input(self) -> None:
        assert compute_outcome_summary({}, {"q1": {"ndcg": 0.5}}, "ndcg") is None
        assert compute_outcome_summary({"q1": {"ndcg": 0.5}}, {}, "ndcg") is None

    def test_returns_none_on_unknown_metric(self) -> None:
        winner = {"q1": {"ndcg": 0.8}}
        comparison = {"q1": {"ndcg": 0.7}}
        assert compute_outcome_summary(winner, comparison, "unknown_metric") is None

    def test_classifies_per_fr4a_thresholds_ndcg(self) -> None:
        """AC-10: NDCG threshold = 0.01. Deltas of -0.51, 0, 0.18 classify as
        regressed/unchanged/improved respectively."""
        winner = {
            "qA": {"ndcg": 0.41},  # delta -0.51 vs 0.92 → regressed
            "qB": {"ndcg": 0.85},  # delta 0.00 vs 0.85 → unchanged
            "qC": {"ndcg": 0.78},  # delta +0.18 vs 0.60 → improved
        }
        comparison = {
            "qA": {"ndcg": 0.92},
            "qB": {"ndcg": 0.85},
            "qC": {"ndcg": 0.60},
        }
        result = compute_outcome_summary(winner, comparison, "ndcg")
        assert result is not None
        assert result.regressed == 1
        assert result.unchanged == 1
        assert result.improved == 1
        # The single regressor candidate (qA) is in the list.
        assert len(result.regressor_candidates) == 1
        qid, w, c, delta = result.regressor_candidates[0]
        assert qid == "qA"
        assert w == pytest.approx(0.41)
        assert c == pytest.approx(0.92)
        assert delta == pytest.approx(-0.51)

    def test_uses_map_threshold_at_002(self) -> None:
        """MAP threshold = 0.02 (Decision D2). Delta of -0.015 is unchanged."""
        winner = {"q1": {"map": 0.50}}
        comparison = {"q1": {"map": 0.515}}  # delta -0.015 → within ±0.02 → unchanged
        result = compute_outcome_summary(winner, comparison, "map")
        assert result is not None
        assert result.unchanged == 1
        assert result.regressed == 0

    def test_caps_regressors_at_top_5(self) -> None:
        """AC-10: top-regressor list is capped at TOP_REGRESSORS_CAP, sorted
        by abs(delta) descending."""
        winner = {f"q{i}": {"ndcg": 0.1 + 0.01 * i} for i in range(8)}
        comparison = {f"q{i}": {"ndcg": 0.9 - 0.01 * i} for i in range(8)}  # all huge regressions
        result = compute_outcome_summary(winner, comparison, "ndcg")
        assert result is not None
        assert result.regressed == 8
        assert len(result.regressor_candidates) == TOP_REGRESSORS_CAP
        # First candidate has the most-negative delta.
        deltas = [c[3] for c in result.regressor_candidates]
        assert deltas == sorted(deltas)  # ascending (most negative first)


class TestBuildRegressorRows:
    def test_hydrates_query_text(self) -> None:
        candidates = [("qA", 0.41, 0.92, -0.51), ("qB", 0.71, 0.85, -0.14)]
        text_by_id = {"qA": "shipping policy", "qB": "wireless headphones"}
        rows = build_regressor_rows(candidates, text_by_id)
        assert len(rows) == 2
        assert rows[0].query_id == "qA"
        assert rows[0].query_text == "shipping policy"
        assert rows[0].delta == pytest.approx(-0.51)

    def test_omits_rows_with_missing_text(self) -> None:
        """A query deleted between Q1+Q2 and Q4 (cascade race) is silently
        dropped — we don't surface a regressor we can't name."""
        candidates = [("qA", 0.41, 0.92, -0.51), ("qDeleted", 0.30, 0.80, -0.50)]
        text_by_id = {"qA": "shipping policy"}  # qDeleted absent
        rows = build_regressor_rows(candidates, text_by_id)
        assert len(rows) == 1
        assert rows[0].query_id == "qA"


# ---------------------------------------------------------------------------
# compute_study_confidence orchestrator
# ---------------------------------------------------------------------------


def _trial(
    *,
    optuna_trial_number: int = 0,
    primary_metric: float = 0.84,
    per_query_metrics: dict[str, dict[str, float]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        optuna_trial_number=optuna_trial_number,
        primary_metric=primary_metric,
        per_query_metrics=per_query_metrics,
    )


class TestComputeStudyConfidence:
    def test_returns_none_when_winner_missing(self) -> None:
        """AC-3a: winner_trial=None → whole-object None."""
        result = compute_study_confidence(
            study_objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            study_best_metric=None,
            winner_trial=None,
            runner_up_trial=None,
            complete_trials_summary=[],
        )
        assert result is None

    def test_returns_none_when_no_complete_trials(self) -> None:
        result = compute_study_confidence(
            study_objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            study_best_metric=0.84,
            winner_trial=_trial(),
            runner_up_trial=None,
            complete_trials_summary=[],
        )
        assert result is None

    def test_partial_shape_when_per_query_metrics_null(self) -> None:
        """AC-3: old study with winner row but per_query_metrics=None →
        partial ConfidenceShape with aggregate signals populated, ci_95 +
        per_query_outcomes + headline.n_queries all null."""
        winner = _trial(
            optuna_trial_number=0,  # must appear in summary keys
            primary_metric=0.840,
            per_query_metrics=None,
        )
        runner_up = _trial(optuna_trial_number=10, primary_metric=0.760, per_query_metrics=None)
        # 15 complete trials so all aggregate signals can compute.
        # Winner (trial 0) is the best; later trials taper down.
        summary = [(0.840 - 0.01 * i, i * 10) for i in range(15)]
        result = compute_study_confidence(
            study_objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            study_best_metric=0.840,
            winner_trial=winner,
            runner_up_trial=runner_up,
            complete_trials_summary=summary,
        )
        assert result is not None
        assert isinstance(result, ConfidenceShape)
        assert result.headline.value == pytest.approx(0.840)
        assert result.headline.n_queries is None
        assert result.ci_95 is None
        assert result.per_query_outcomes is None
        # Aggregate signals populated (independent of per_query).
        assert result.runner_up_gap is not None
        assert result.late_trial_stddev is not None
        assert result.convergence is not None

    def test_full_shape_with_all_data(self) -> None:
        """All sub-fields populated when winner + runner-up both have
        per_query_metrics, ≥10 complete trials, ≥5 queries."""
        per_query = {f"q{i}": {"ndcg": 0.8 + 0.01 * i} for i in range(10)}
        winner = _trial(
            optuna_trial_number=0,  # winner appears in summary keys
            primary_metric=0.85,
            per_query_metrics=per_query,
        )
        # Runner-up's per_query is shifted slightly so most queries improved.
        runner_up_pq = {f"q{i}": {"ndcg": 0.7 + 0.01 * i} for i in range(10)}
        runner_up = _trial(
            optuna_trial_number=10,
            primary_metric=0.75,
            per_query_metrics=runner_up_pq,
        )
        # 15 complete trials. Winner is trial 0 (early — under 50% of max=140).
        # Synthesize a late-window trial within 0.005 of the winner so we
        # get early_held: trial 140 (= max) at 0.848 (gap = 0.002 < 0.005).
        summary = [(0.85 - 0.01 * i, i * 10) for i in range(15)]
        summary[-1] = (0.848, 140)

        result = compute_study_confidence(
            study_objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            study_best_metric=0.85,
            winner_trial=winner,
            runner_up_trial=runner_up,
            complete_trials_summary=summary,
            query_text_by_id={},  # no regressors expected (all improved)
        )
        assert result is not None
        assert result.headline.n_queries == 10
        assert result.ci_95 is not None
        assert result.runner_up_gap is not None
        assert result.late_trial_stddev is not None
        assert result.convergence is not None
        assert result.per_query_outcomes is not None
        # All queries improved → 0 regressors.
        assert result.per_query_outcomes.regressed == 0
        assert result.per_query_outcomes.improved == 10
        assert result.per_query_outcomes.comparison_against == "runner_up"

    def test_ci_95_independent_of_runner_up_per_query(self) -> None:
        """AC-16: 1-complete-trial case — winner has per_query but no
        runner-up → ci_95 + headline.n_queries populate from winner alone,
        per_query_outcomes + runner_up_gap suppressed."""
        per_query = {f"q{i}": {"ndcg": 0.8 + 0.01 * i} for i in range(10)}
        winner = _trial(
            optuna_trial_number=0,
            primary_metric=0.85,
            per_query_metrics=per_query,
        )
        summary = [(0.85, 0)]  # only the winner
        result = compute_study_confidence(
            study_objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            study_best_metric=0.85,
            winner_trial=winner,
            runner_up_trial=None,
            complete_trials_summary=summary,
        )
        assert result is not None
        # Winner-side signals populate.
        assert result.headline.n_queries == 10
        assert result.ci_95 is not None
        # Comparison-side signals suppress.
        assert result.runner_up_gap is None  # only 1 trial
        assert result.per_query_outcomes is None  # no runner-up
        # Aggregate signals that need ≥10 / ≥3 trials suppress.
        assert result.late_trial_stddev is None
        assert result.convergence is None  # only 1 trial < CONVERGENCE_MIN_COMPLETE


# Sanity check that all constants are defined and referenced (drift guard).
def test_constants_exported() -> None:
    assert BOOTSTRAP_MIN_N_QUERIES == 5
    assert RUNNER_UP_GAP_MIN_COMPLETE == 2
    assert LATE_TRIAL_MIN_COMPLETE == 10
    assert CONVERGENCE_MIN_COMPLETE == 3
    assert TOP_REGRESSORS_CAP == 5
    assert set(REGRESSOR_THRESHOLDS.keys()) == {"ndcg", "precision", "recall", "map", "mrr"}
    assert REGRESSOR_THRESHOLDS["ndcg"] == 0.01
    assert REGRESSOR_THRESHOLDS["map"] == 0.02
