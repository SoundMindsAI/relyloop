# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for the PR body's ``## Confidence`` section (Story 1.5).

Covers AC-11 (full-confidence rendering), AC-12 (section omitted on
whole-object null), and the partial-render path (FR-7 / AC-3 mirror).

These call ``_render_pr_body_study_backed`` directly with factory-built
:class:`ConfidenceShape` instances — the renderer signature requires the
typed Pydantic object (cycle-2 GPT-5.5 F3). The seed helper
:func:`make_test_confidence` builds a full shape with sensible defaults
and accepts per-test-case overrides for each sub-field.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.app.domain.study.confidence import (
    CIShape,
    ConfidenceShape,
    ConvergenceShape,
    HeadlineShape,
    LateTrialStddevShape,
    PerQueryOutcomesShape,
    RegressorRowShape,
    RunnerUpGapShape,
)
from backend.workers.git_pr import _render_pr_body_study_backed


def make_test_confidence(**overrides: Any) -> ConfidenceShape:
    """Build a fully-populated ``ConfidenceShape`` for tests.

    Any of the six sub-fields may be overridden by passing the field name
    as a kwarg (e.g. ``make_test_confidence(ci_95=None)``).
    """
    defaults: dict[str, Any] = {
        "headline": HeadlineShape(metric="ndcg", value=0.840, k=10, n_queries=20),
        "ci_95": CIShape(low=0.780, high=0.890, method="bootstrap_n1000", n_samples=20),
        "runner_up_gap": RunnerUpGapShape(
            value=0.002,
            classification="robust_plateau",
            top10_within=0.004,
            runner_up_metric=0.838,
        ),
        "late_trial_stddev": LateTrialStddevShape(
            value=0.012, window_size=20, min_window_required=10
        ),
        "convergence": ConvergenceShape(best_at_trial=387, total_trials=1000, regime="early_held"),
        "per_query_outcomes": PerQueryOutcomesShape(
            improved=14,
            unchanged=4,
            regressed=2,
            comparison_against="runner_up",
            top_regressors=[
                RegressorRowShape(
                    query_id="q1",
                    query_text="vintage acoustic guitar",
                    winner_score=0.41,
                    comparison_score=0.92,
                    delta=-0.51,
                ),
                RegressorRowShape(
                    query_id="q2",
                    query_text="leather wallet",
                    winner_score=0.55,
                    comparison_score=0.78,
                    delta=-0.23,
                ),
            ],
        ),
    }
    defaults.update(overrides)
    return ConfidenceShape(**defaults)


def _make_proposal_and_study() -> tuple[
    SimpleNamespace, SimpleNamespace, SimpleNamespace, dict[str, Any]
]:
    """Build the inputs every test needs (proposal, study, digest, config_diff)."""
    proposal = SimpleNamespace(
        metric_delta={
            "ndcg@10": {"baseline": 0.612, "achieved": 0.840, "delta_pct": 37.3},
        },
    )
    study = SimpleNamespace(id="study-abc", name="prod-en-v1")
    digest = SimpleNamespace(suggested_followups=["Try BM25 k1=1.4"])
    config_diff = {"k1": {"from": 1.2, "to": 1.4}}
    return proposal, study, digest, config_diff


# ---------------------------------------------------------------------------
# AC-11 — full-confidence PR body
# ---------------------------------------------------------------------------


def test_ac11_full_confidence_section_renders_between_metric_delta_and_config_diff() -> None:
    proposal, study, digest, config_diff = _make_proposal_and_study()
    confidence = make_test_confidence()
    body = _render_pr_body_study_backed(
        proposal=proposal,
        study=study,
        digest=digest,
        config_diff=config_diff,
        chart_md="",
        base_url=None,
        confidence=confidence,
    )
    # Section appears.
    assert "## Confidence" in body
    # Section ordering — Confidence falls between Metric delta and Config diff.
    metric_delta_idx = body.index("## Metric delta")
    confidence_idx = body.index("## Confidence")
    config_diff_idx = body.index("## Config diff")
    assert metric_delta_idx < confidence_idx < config_diff_idx
    # CI line shape: metric@k, value, 95% CI low-high, N=queries.
    assert "ndcg@10: 0.840" in body
    assert "95% CI 0.780-0.890" in body
    assert "N=20 queries" in body
    # Per-query line.
    assert "Queries: 14 improved · 4 unchanged · 2 regressed (vs runner_up)" in body
    # Named regressors with text + score arrow.
    assert "`vintage acoustic guitar` (0.920 → 0.410)" in body
    assert "`leather wallet` (0.780 → 0.550)" in body
    # Runner-up gap line.
    assert "Runner-up gap 0.002 (robust_plateau)" in body
    # Late-trial 1σ.
    assert "Late-trial 1σ = 0.012" in body
    # Convergence.
    assert "Convergence: early_held (best at trial 387 of 1000)" in body


# ---------------------------------------------------------------------------
# AC-12 — section omitted when confidence is None
# ---------------------------------------------------------------------------


def test_ac12_confidence_section_omitted_when_confidence_is_none() -> None:
    proposal, study, digest, config_diff = _make_proposal_and_study()
    body = _render_pr_body_study_backed(
        proposal=proposal,
        study=study,
        digest=digest,
        config_diff=config_diff,
        chart_md="",
        base_url=None,
        confidence=None,
    )
    assert "## Confidence" not in body
    # Section ordering reverts to Metric delta → Config diff (no gap).
    metric_delta_idx = body.index("## Metric delta")
    config_diff_idx = body.index("## Config diff")
    assert metric_delta_idx < config_diff_idx
    # The headline link / proposal / config-diff rendering still works.
    assert "| `k1` | `1.2` | `1.4` |" in body


# ---------------------------------------------------------------------------
# Partial render — sub-fields independently null (FR-7 / AC-3 mirror)
# ---------------------------------------------------------------------------


def test_partial_confidence_renders_only_non_null_sub_fields() -> None:
    """Old-study case: ci_95 + per_query_outcomes null; aggregate signals present."""
    proposal, study, digest, config_diff = _make_proposal_and_study()
    confidence = make_test_confidence(
        ci_95=None,
        per_query_outcomes=None,
        headline=HeadlineShape(metric="ndcg", value=0.840, k=10, n_queries=None),
    )
    body = _render_pr_body_study_backed(
        proposal=proposal,
        study=study,
        digest=digest,
        config_diff=config_diff,
        chart_md="",
        base_url=None,
        confidence=confidence,
    )
    # Section heading present.
    assert "## Confidence" in body
    # CI + per-query sub-lines absent.
    assert "95% CI" not in body
    assert "Queries:" not in body
    assert "Queries that regressed:" not in body
    # Aggregate signals still rendered.
    assert "Runner-up gap 0.002 (robust_plateau)" in body
    assert "Late-trial 1σ = 0.012" in body
    assert "Convergence: early_held (best at trial 387 of 1000)" in body


# ---------------------------------------------------------------------------
# Regressors block — omitted when regressed == 0
# ---------------------------------------------------------------------------


def test_regressors_line_omitted_when_no_queries_regressed() -> None:
    """Per-query block present; named-regressors list absent when regressed == 0."""
    proposal, study, digest, config_diff = _make_proposal_and_study()
    confidence = make_test_confidence(
        per_query_outcomes=PerQueryOutcomesShape(
            improved=18,
            unchanged=2,
            regressed=0,
            comparison_against="runner_up",
            top_regressors=[],
        ),
    )
    body = _render_pr_body_study_backed(
        proposal=proposal,
        study=study,
        digest=digest,
        config_diff=config_diff,
        chart_md="",
        base_url=None,
        confidence=confidence,
    )
    assert "Queries: 18 improved · 2 unchanged · 0 regressed (vs runner_up)" in body
    assert "Queries that regressed:" not in body
