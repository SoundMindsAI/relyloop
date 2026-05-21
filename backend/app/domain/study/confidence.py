"""Per-study metric-confidence analytics (feat_pr_metric_confidence Story 1.3).

Pure-Python helpers for computing the ``ConfidenceShape`` exposed on
``StudyDetail``, the PR body's ``## Confidence`` section, and the digest
narrative's ``<confidence>`` / ``<per_query_outcomes>`` XML blocks.

Domain-layer convention (per CLAUDE.md "Domain Layer"): every function in
this module is pure — no DB access, no I/O, no async. The API router
(:func:`backend.app.api.v1.studies._detail`) and the PR worker
(:func:`backend.workers.git_pr.open_pr`) fetch the 4 queries from FR-2 and
call :func:`compute_study_confidence` with the resulting data. This keeps the
analytics independently unit-testable without DB fixtures.

The Pydantic shapes live HERE (not in ``backend.app.api.v1.schemas``) because
the domain module is the canonical assembler — the API schemas re-export
``ConfidenceShape`` for the ``StudyDetail`` field (Story 1.4).

The :data:`ConvergenceRegime`, :data:`RunnerUpClassification`,
:data:`ComparisonAgainst`, and :data:`CIMethod` Literals also live here for
the same reason. ``ObjectiveMetric`` is intentionally NOT imported from
``schemas`` — that would create a circular import at app startup
(schemas → confidence → schemas). ``HeadlineShape.metric`` uses ``str``;
the upstream value is already validated by the existing ``ObjectiveMetric``
Literal at the create-study endpoint (``schemas.py:214``), so the wire
contract is preserved.

References:
- Spec FR-2 through FR-7: docs/02_product/planned_features/feat_pr_metric_confidence/feature_spec.md
- AC-3 / AC-3a / AC-4 / AC-5 / AC-6 / AC-7 / AC-8 / AC-9 / AC-10 / AC-15 / AC-16
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel

from backend.app.eval.scoring import objective_metric_key

# ---------------------------------------------------------------------------
# Locked constants — every value is referenced from FR-4 / FR-4a.
# Source of truth: feature_spec.md §19 Decision log (feat_pr_metric_confidence).
# ---------------------------------------------------------------------------

BOOTSTRAP_N: int = 1000
"""Number of bootstrap resamples for the CI computation (Decision D4)."""

BOOTSTRAP_SEED: int = 42
"""Fixed numpy RNG seed for reproducibility (Decision D4 / AC-4). An approver
re-reading the PR sees byte-identical CI numbers across calls."""

BOOTSTRAP_CI_LEVEL: float = 0.95
"""95% percentile interval (Decision D4)."""

BOOTSTRAP_MIN_N_QUERIES: int = 5
"""Minimum number of per-query datapoints required to compute a CI. Below
this, ``bootstrap_ci_95`` returns None (FR-7)."""

REGRESSOR_THRESHOLDS: dict[str, float] = {
    "ndcg": 0.01,
    "precision": 0.01,
    "recall": 0.01,
    "map": 0.02,
    "mrr": 0.02,
}
"""Absolute-delta threshold per metric for the improved/unchanged/regressed
classification (FR-4a, Decision D2)."""

RUNNER_UP_PLATEAU_BAND: float = 0.005
"""``robust_plateau`` if all top-N trials are within this band of the winner
(Decision D5)."""

LATE_TRIAL_WINDOW_FRAC: float = 0.2
"""Fraction of complete trials in the noise-floor window (Decision D3)."""

LATE_TRIAL_WINDOW_MIN: int = 5
"""Minimum window size for the noise-floor (Decision D3)."""

LATE_TRIAL_MIN_COMPLETE: int = 10
"""Minimum complete trials required to report a noise floor (FR-7,
Decision D3)."""

EARLY_HELD_TRIAL_NUMBER_FRAC: float = 0.5
"""Winner found in the first 50% of trials AND the late-window probe finds a
near-equivalent → ``early_held`` (Decision D6, cycle-2 GPT-5.5 F7 fix)."""

EARLY_HELD_LATE_WINDOW_FRAC: float = 0.25
"""Last 25% of trial numbers is the "late window" probe range
(Decision D6)."""

LATE_RISING_TRIAL_NUMBER_FRAC: float = 0.9
"""Winner found at or after 90% of trials → ``late_rising``
(Decision D6)."""

CONVERGENCE_MIN_COMPLETE: int = 3
"""Minimum complete trials required to classify convergence (FR-7)."""

RUNNER_UP_GAP_MIN_COMPLETE: int = 2
"""Minimum complete trials required to report a runner-up gap (FR-7)."""

TOP_REGRESSORS_CAP: int = 5
"""Maximum number of named regressor queries in the PR body / ConfidencePanel
(FR-4a)."""

# ---------------------------------------------------------------------------
# Wire-value Literals (single source of truth for the spec §8.4 enumerated
# value contract; re-exported via schemas.py for StudyDetail).
# ---------------------------------------------------------------------------

ConvergenceRegime = Literal["early_held", "late_rising", "noisy"]
RunnerUpClassification = Literal["robust_plateau", "sharp_peak"]
ComparisonAgainst = Literal["runner_up", "baseline"]
"""Phase 1 unconditionally emits ``runner_up``. ``baseline`` is reserved for
Phase 2 (see ``phase2_idea.md``)."""

CIMethod = Literal["bootstrap_n1000"]


# ---------------------------------------------------------------------------
# Pydantic shapes — exported and re-imported by schemas.py (Story 1.4).
# ---------------------------------------------------------------------------


class HeadlineShape(BaseModel):
    """Top-line metric value + N(queries) used in the CI.

    ``metric`` uses ``str`` (not ``ObjectiveMetric``) to avoid a circular
    import: ``schemas.py`` imports ``ConfidenceShape`` from here, so this
    module cannot import back from ``schemas.py``. The upstream value is
    already validated by the existing ``ObjectiveMetric`` Literal at the
    create-study endpoint (``schemas.py:214``).
    """

    metric: str
    value: float
    k: int | None
    n_queries: int | None
    """``None`` when the winner trial has ``per_query_metrics IS NULL``
    (FR-7)."""


class CIShape(BaseModel):
    """Bootstrap percentile CI on the winner's per-query metric values."""

    low: float
    high: float
    method: CIMethod
    n_samples: int


class RunnerUpGapShape(BaseModel):
    """Runner-up trial's metric vs the winner.

    The whole shape is suppressed to ``None`` when there are <2 complete
    trials (FR-2 + FR-7); ``classification`` is non-null whenever this shape
    is present.
    """

    value: float
    classification: RunnerUpClassification
    top10_within: float
    """Max distance from the winner among the top-``min(10, N)`` trials.
    Decision threshold: ``robust_plateau`` if ``top10_within <= 0.005``."""
    runner_up_metric: float


class LateTrialStddevShape(BaseModel):
    """Sample stddev of ``primary_metric`` over the late-trial window."""

    value: float
    window_size: int
    min_window_required: int  # always LATE_TRIAL_MIN_COMPLETE


class ConvergenceShape(BaseModel):
    """Where the winner sits in the Optuna trial sequence + the classified regime."""

    best_at_trial: int
    total_trials: int
    regime: ConvergenceRegime


class RegressorRowShape(BaseModel):
    """One row in the named-regressors table."""

    query_id: str
    query_text: str
    winner_score: float
    comparison_score: float
    delta: float
    """``winner_score - comparison_score``; always negative for regressors."""


class PerQueryOutcomesShape(BaseModel):
    """Per-query outcome counts + the top-5 named regressors."""

    improved: int
    unchanged: int
    regressed: int
    comparison_against: ComparisonAgainst
    top_regressors: list[RegressorRowShape]


class ConfidenceShape(BaseModel):
    """The top-level shape exposed via ``StudyDetail.confidence``.

    Every sub-field is independently nullable per FR-7 — degraded paths
    suppress only the sub-fields they affect, never the whole shape (the
    orchestrator returns whole-object ``None`` only when the winner trial
    row itself is missing).
    """

    headline: HeadlineShape
    ci_95: CIShape | None
    runner_up_gap: RunnerUpGapShape | None
    late_trial_stddev: LateTrialStddevShape | None
    convergence: ConvergenceShape | None
    per_query_outcomes: PerQueryOutcomesShape | None


@dataclass(frozen=True)
class _OutcomeSummary:
    """Outcome counts + regressor candidate qids (no query_text yet).

    Produced by :func:`compute_outcome_summary`; consumed by the
    orchestrator + :func:`build_regressor_rows`. Carries only ``query_id``
    values (NOT ``query_text``) so the orchestrator can run Q4 from FR-2's
    4-query read pattern AFTER deciding which qids are candidates (cycle-1
    GPT-5.5 F7 fix).
    """

    improved: int
    unchanged: int
    regressed: int
    regressor_candidates: list[tuple[str, float, float, float]] = field(default_factory=list)
    """Each tuple: ``(query_id, winner_score, comparison_score, delta)``.
    Sorted by ``abs(delta)`` descending; capped at TOP_REGRESSORS_CAP."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def bootstrap_ci_95(per_query_values: list[float]) -> CIShape | None:
    """Percentile bootstrap CI with seed=42, N=1000 resamples.

    Returns ``None`` when ``len(per_query_values) < BOOTSTRAP_MIN_N_QUERIES``
    (FR-7). The fixed seed ensures byte-identical CI values across re-reads
    of the same study (AC-4).
    """
    if len(per_query_values) < BOOTSTRAP_MIN_N_QUERIES:
        return None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    arr = np.asarray(per_query_values, dtype=np.float64)
    # Resample with replacement, take the mean of each sample.
    means = rng.choice(arr, size=(BOOTSTRAP_N, len(arr)), replace=True).mean(axis=1)
    alpha = (1.0 - BOOTSTRAP_CI_LEVEL) / 2.0
    low_p, high_p = 100.0 * alpha, 100.0 * (1.0 - alpha)
    low = float(np.percentile(means, low_p))
    high = float(np.percentile(means, high_p))
    return CIShape(
        low=low,
        high=high,
        method="bootstrap_n1000",
        n_samples=len(arr),
    )


def classify_runner_up_gap(
    sorted_primary_metrics: list[float],
) -> RunnerUpGapShape | None:
    """Build the full ``RunnerUpGapShape`` from sorted primary metrics.

    Input is the top trials' primary metrics in descending order. Returns
    ``None`` when ``len < RUNNER_UP_GAP_MIN_COMPLETE`` (FR-7). Otherwise
    computes:

    - ``value`` = ``winner - runner_up``
    - ``runner_up_metric`` = the 2nd-best metric
    - ``top10_within`` = max(winner - m) over the top ``min(10, N)`` trials
    - ``classification`` = ``"robust_plateau"`` if ``top10_within <=
      RUNNER_UP_PLATEAU_BAND``, else ``"sharp_peak"`` (cycle-1 GPT-5.5 F8 fix:
      the helper now returns the full shape including ``top10_within``
      + ``runner_up_metric``).
    """
    if len(sorted_primary_metrics) < RUNNER_UP_GAP_MIN_COMPLETE:
        return None
    winner = sorted_primary_metrics[0]
    runner_up = sorted_primary_metrics[1]
    top_n = min(10, len(sorted_primary_metrics))
    top_band = sorted_primary_metrics[:top_n]
    top10_within = float(max(winner - m for m in top_band))
    classification: RunnerUpClassification = (
        "robust_plateau" if top10_within <= RUNNER_UP_PLATEAU_BAND else "sharp_peak"
    )
    return RunnerUpGapShape(
        value=float(winner - runner_up),
        classification=classification,
        top10_within=top10_within,
        runner_up_metric=float(runner_up),
    )


def compute_late_trial_stddev(
    primary_metrics_in_trial_order: list[float],
) -> LateTrialStddevShape | None:
    """Sample stddev over the late-trial window (the noise floor signal).

    Window size is ``max(LATE_TRIAL_WINDOW_MIN, int(N *
    LATE_TRIAL_WINDOW_FRAC))``. Returns ``None`` when ``N <
    LATE_TRIAL_MIN_COMPLETE`` (FR-7). The ``primary_metrics_in_trial_order``
    list must be sorted by ``optuna_trial_number`` ascending; the helper
    takes the tail.
    """
    n = len(primary_metrics_in_trial_order)
    if n < LATE_TRIAL_MIN_COMPLETE:
        return None
    window_size = max(LATE_TRIAL_WINDOW_MIN, int(n * LATE_TRIAL_WINDOW_FRAC))
    tail = primary_metrics_in_trial_order[-window_size:]
    value = float(np.std(np.asarray(tail, dtype=np.float64), ddof=1))
    return LateTrialStddevShape(
        value=value,
        window_size=window_size,
        min_window_required=LATE_TRIAL_MIN_COMPLETE,
    )


def classify_convergence_regime(
    winner_trial_number: int,
    primary_metrics_by_trial_number: dict[int, float],
) -> ConvergenceShape | None:
    """Classify convergence as ``early_held`` / ``late_rising`` / ``noisy``.

    Decision D6 (cycle-2 GPT-5.5 F7 fix — the original "no improvement in last
    25%" rule was tautological because the winner is the global best by
    construction):

    - ``early_held``: winner's ``optuna_trial_number ≤ 50% of max`` AND at
      least one trial in the last 25% of trial numbers has ``primary_metric``
      within ``RUNNER_UP_PLATEAU_BAND`` of the winner (observable signal that
      the late budget found near-equivalent configs).
    - ``late_rising``: winner's ``optuna_trial_number ≥ 90% of max``.
    - ``noisy``: otherwise.

    Returns ``None`` when ``N < CONVERGENCE_MIN_COMPLETE`` (FR-7).
    ``primary_metrics_by_trial_number`` includes ONLY complete trials (the
    caller filters).
    """
    n = len(primary_metrics_by_trial_number)
    if n < CONVERGENCE_MIN_COMPLETE:
        return None
    winner_metric = primary_metrics_by_trial_number[winner_trial_number]
    max_trial_number = max(primary_metrics_by_trial_number.keys())
    total_trials = n

    if winner_trial_number >= LATE_RISING_TRIAL_NUMBER_FRAC * max_trial_number:
        regime: ConvergenceRegime = "late_rising"
    elif winner_trial_number <= EARLY_HELD_TRIAL_NUMBER_FRAC * max_trial_number:
        # Observable late-window probe: any trial in the last 25% within
        # the plateau band of the winner counts as "held".
        late_window_start = max_trial_number * (1.0 - EARLY_HELD_LATE_WINDOW_FRAC)
        late_window_trials = [
            m for tn, m in primary_metrics_by_trial_number.items() if tn >= late_window_start
        ]
        if late_window_trials and any(
            (winner_metric - m) <= RUNNER_UP_PLATEAU_BAND for m in late_window_trials
        ):
            regime = "early_held"
        else:
            regime = "noisy"
    else:
        regime = "noisy"

    return ConvergenceShape(
        best_at_trial=winner_trial_number,
        total_trials=total_trials,
        regime=regime,
    )


def compute_outcome_summary(
    winner_per_query: dict[str, dict[str, float]],
    comparison_per_query: dict[str, dict[str, float]],
    metric: str,
) -> _OutcomeSummary | None:
    """Classify per-query outcomes and surface the top regressor candidates.

    Improved/unchanged/regressed buckets use the FR-4a per-metric threshold
    table. Returned candidates are sorted by ``abs(delta)`` descending,
    capped at ``TOP_REGRESSORS_CAP``. Returns ``None`` when either input
    dict is empty or ``metric``'s base name is not in
    :data:`REGRESSOR_THRESHOLDS`.

    ``metric`` is the per-query lookup key as persisted by the worker
    (``backend.app.eval.scoring.score`` writes user-facing tokens — e.g.
    ``"ndcg@10"``, ``"map@10"``, ``"map"``, ``"mrr"``). The threshold
    table is keyed by metric *base* names (``ndcg``, ``map``, etc.), so
    the helper strips any ``@<k>`` suffix before the lookup.

    Cycle-1 GPT-5.5 F7 fix: this helper does NOT take ``query_text_by_id`` —
    candidates carry only ``query_id``. The orchestrator runs Q4 of the
    4-query read pattern AFTER seeing the candidate list, then calls
    :func:`build_regressor_rows` to hydrate the rows with text.
    """
    if not winner_per_query or not comparison_per_query:
        return None
    # Strip any @<k> suffix so "ndcg@10" → "ndcg", "map@10" → "map", and
    # bare "mrr" / "map" / "ndcg" still work. See REGRESSOR_THRESHOLDS keys.
    threshold = REGRESSOR_THRESHOLDS.get(metric.partition("@")[0])
    if threshold is None:
        return None

    improved = 0
    unchanged = 0
    regressed = 0
    candidates: list[tuple[str, float, float, float]] = []

    # Compare only qids present in BOTH dicts. Queries missing from either
    # side (e.g., a query added after the trial ran) are ignored.
    for qid in winner_per_query.keys() & comparison_per_query.keys():
        w_metrics = winner_per_query[qid]
        c_metrics = comparison_per_query[qid]
        if metric not in w_metrics or metric not in c_metrics:
            continue
        w_score = float(w_metrics[metric])
        c_score = float(c_metrics[metric])
        delta = w_score - c_score
        if delta > threshold:
            improved += 1
        elif delta < -threshold:
            regressed += 1
            candidates.append((qid, w_score, c_score, delta))
        else:
            unchanged += 1

    # Sort by absolute delta descending → most-negative delta first. For
    # regressors all deltas are negative, so ascending sort of the signed
    # delta puts the largest-magnitude regressor first.
    candidates.sort(key=lambda row: row[3])
    capped = candidates[:TOP_REGRESSORS_CAP]
    return _OutcomeSummary(
        improved=improved,
        unchanged=unchanged,
        regressed=regressed,
        regressor_candidates=capped,
    )


def build_regressor_rows(
    candidates: list[tuple[str, float, float, float]],
    query_text_by_id: dict[str, str],
) -> list[RegressorRowShape]:
    """Hydrate candidate qids with ``query_text`` from Q4's result.

    Rows whose ``query_id`` is missing from ``query_text_by_id`` are
    omitted — the query may have been deleted by a cascade race; we don't
    want to surface a regressor we can't name.
    """
    rows: list[RegressorRowShape] = []
    for qid, winner_score, comparison_score, delta in candidates:
        text = query_text_by_id.get(qid)
        if text is None:
            continue
        rows.append(
            RegressorRowShape(
                query_id=qid,
                query_text=text,
                winner_score=winner_score,
                comparison_score=comparison_score,
                delta=delta,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Orchestrator — pure (no DB, no async). The API router / PR worker fetch
# the 4 queries from FR-2 and pass the results in.
# ---------------------------------------------------------------------------


def compute_study_confidence(
    *,
    study_objective: dict[str, Any],
    study_best_metric: float | None,
    winner_trial: Any | None,
    runner_up_trial: Any | None,
    complete_trials_summary: list[tuple[float, int]],
    query_text_by_id: dict[str, str] | None = None,
) -> ConfidenceShape | None:
    """Assemble the ``ConfidenceShape`` from pre-fetched DB data.

    Arguments mirror the 4-query read pattern from FR-2:

    - ``study_objective`` — ``study.objective`` JSONB (``{metric, k,
      direction}``). The ``metric`` key drives ``HeadlineShape`` + the
      threshold lookup in :func:`compute_outcome_summary`.
    - ``study_best_metric`` — ``study.best_metric``. Populates
      ``HeadlineShape.value``.
    - ``winner_trial`` — full ``Trial`` ORM row at ``study.best_trial_id``,
      OR ``None`` if the row is missing (cascade-delete race or
      ``best_trial_id IS NULL`` for an incomplete study). Triggers whole-
      object ``None`` per FR-7.
    - ``runner_up_trial`` — 2nd-best complete trial by ``primary_metric``,
      OR ``None`` when there's only one complete trial.
    - ``complete_trials_summary`` — list of ``(primary_metric,
      optuna_trial_number)`` for every complete trial, sorted by
      ``optuna_trial_number`` ascending. Drives the aggregate signals
      (``runner_up_gap``, ``late_trial_stddev``, ``convergence``).
    - ``query_text_by_id`` — result of Q4 (only fetched after
      ``compute_outcome_summary`` produces candidates); maps ``query_id``
      → ``query_text`` for the named regressors. May be ``None`` /
      ``{}`` when there are no candidates.

    Returns ``None`` whole-object when ``winner_trial is None``. Otherwise
    returns a partial ``ConfidenceShape`` per FR-7: each sub-field is
    independently nullable.

    Cycle-2 GPT-5.5 F2 fix: ``ci_95`` + ``headline.n_queries`` decouple
    from the runner-up gate — AC-16 (1-complete-trial case) requires CI
    to populate from the winner alone.
    """
    # FR-2 condition (a/b/c) — whole-object null.
    if winner_trial is None:
        return None
    if not complete_trials_summary:
        return None

    metric = study_objective.get("metric")
    if not isinstance(metric, str):
        return None
    k = study_objective.get("k")
    if k is not None and not isinstance(k, int):
        k = None

    # Compute the per-query lookup key. The worker persists what
    # :func:`backend.app.eval.scoring.score` emits — user-facing tokens
    # like ``ndcg@10``, ``map@10``, ``map``, ``mrr``. Bug captured in
    # ``bug_confidence_per_query_metric_key_drift`` and fixed inline on
    # ``feat_pr_metric_confidence``.
    try:
        per_query_key = objective_metric_key(study_objective)
    except ValueError:
        # Malformed objective (missing required k, unsupported metric, …):
        # graceful degrade to whole-object None per FR-7 invariant.
        return None

    # Headline value comes from study.best_metric (denormalized winner
    # primary_metric); the n_queries comes from the winner's per_query
    # dict when present.
    headline_value = (
        float(study_best_metric)
        if study_best_metric is not None
        else float(winner_trial.primary_metric or 0.0)
    )
    winner_per_query = winner_trial.per_query_metrics or {}
    winner_values_for_metric = [
        float(v[per_query_key])
        for v in winner_per_query.values()
        if isinstance(v, dict) and per_query_key in v
    ]
    n_queries: int | None = len(winner_values_for_metric) if winner_per_query else None

    headline = HeadlineShape(
        metric=metric,
        value=headline_value,
        k=k,
        n_queries=n_queries,
    )

    # Aggregate signals — independent of per_query data.
    sorted_primary_metrics = sorted(
        (m for m, _ in complete_trials_summary if m is not None),
        reverse=True,
    )
    runner_up_gap = classify_runner_up_gap(sorted_primary_metrics)

    primary_in_trial_order = [m for m, _ in complete_trials_summary if m is not None]
    late_trial_stddev = compute_late_trial_stddev(primary_in_trial_order)

    primary_by_trial_number = {tn: m for m, tn in complete_trials_summary if m is not None}
    convergence = classify_convergence_regime(
        winner_trial_number=winner_trial.optuna_trial_number,
        primary_metrics_by_trial_number=primary_by_trial_number,
    )

    # Winner-only per-query signal — independent of runner-up gate
    # (cycle-2 GPT-5.5 F2 fix; AC-16 1-complete-trial case).
    ci_95 = bootstrap_ci_95(winner_values_for_metric)

    # Comparison-based per-query signal — requires BOTH winner + runner-up
    # to have per_query_metrics (the runner-up's primary_metric alone is
    # not enough to compute deltas).
    per_query_outcomes: PerQueryOutcomesShape | None = None
    if runner_up_trial is not None and winner_per_query and runner_up_trial.per_query_metrics:
        outcome = compute_outcome_summary(
            winner_per_query=winner_per_query,
            comparison_per_query=runner_up_trial.per_query_metrics,
            metric=per_query_key,
        )
        if outcome is not None:
            regressor_rows = build_regressor_rows(
                candidates=outcome.regressor_candidates,
                query_text_by_id=query_text_by_id or {},
            )
            per_query_outcomes = PerQueryOutcomesShape(
                improved=outcome.improved,
                unchanged=outcome.unchanged,
                regressed=outcome.regressed,
                comparison_against="runner_up",  # FR-3 locked for Phase 1
                top_regressors=regressor_rows,
            )

    return ConfidenceShape(
        headline=headline,
        ci_95=ci_95,
        runner_up_gap=runner_up_gap,
        late_trial_stddev=late_trial_stddev,
        convergence=convergence,
        per_query_outcomes=per_query_outcomes,
    )
