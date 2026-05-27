"""Async glue for the pure-Python confidence orchestrator (feat_pr_metric_confidence Story 1.4).

:mod:`backend.app.domain.study.confidence` keeps the analytics pure (no DB,
no I/O). This module owns the 4-query read pattern from spec FR-2 and
adapts the results into the pure orchestrator's keyword arguments.

Consumers:

* :func:`backend.app.api.v1.studies._detail` — enriches ``StudyDetail``
  (Story 1.4).
* :func:`backend.workers.git_pr.open_pr` — populates the PR body's
  ``## Confidence`` section (Story 1.5).
* :func:`backend.workers.digest.generate_digest` — serializes the shape
  into the ``<confidence>`` / ``<per_query_outcomes>`` Jinja blocks
  (Story 1.6).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.models import Query, Study, Trial
from backend.app.domain.study.confidence import (
    ConfidenceShape,
    compute_outcome_summary,
    compute_study_confidence,
)
from backend.app.eval.scoring import objective_metric_key


async def fetch_study_confidence(db: AsyncSession, study: Study) -> ConfidenceShape | None:
    """Run the 4-query read pattern from FR-2 and assemble ``ConfidenceShape``.

    Returns ``None`` whole-object when ``study.best_trial_id`` is unset or
    points at a missing row (FR-7 / AC-3a). Otherwise hands off to
    :func:`compute_study_confidence` with all data pre-fetched.

    The Q4 ``queries`` lookup runs ONLY when ``compute_outcome_summary``
    identifies regressor candidates — most studies skip Q4 entirely.
    """
    if study.best_trial_id is None:
        return None

    # Q1: winner trial (full row — need .per_query_metrics + .optuna_trial_number).
    winner = await repo.get_trial(db, study.best_trial_id)
    if winner is None:
        return None

    # Q1a: baseline trial (feat_study_baseline_trial FR-4). Only fetched
    # when the study has baseline_trial_id stamped — i.e., the baseline
    # phase ran AND succeeded AND was stamped via FR-12.
    baseline_trial: Trial | None = None
    if study.baseline_trial_id is not None:
        baseline_trial = await repo.get_trial(db, study.baseline_trial_id)

    # Q2: runner-up trial — 2nd-best complete trial by primary_metric.
    # FR-11: exclude baseline rows so the runner-up classification compares
    # ONLY against Optuna trials (the baseline lives under its own surface).
    runner_up_stmt = (
        select(Trial)
        .where(
            Trial.study_id == study.id,
            Trial.is_baseline.is_(False),
            Trial.status == "complete",
            Trial.id != winner.id,
        )
        .order_by(Trial.primary_metric.desc().nulls_last())
        .limit(1)
    )
    runner_up = (await db.execute(runner_up_stmt)).scalar_one_or_none()

    # Q3: complete-trials projection — (primary_metric, optuna_trial_number).
    # FR-11: exclude baseline rows from convergence/late-stddev aggregates.
    summary_stmt = (
        select(Trial.primary_metric, Trial.optuna_trial_number)
        .where(
            Trial.study_id == study.id,
            Trial.is_baseline.is_(False),
            Trial.status == "complete",
        )
        .order_by(Trial.optuna_trial_number.asc())
    )
    summary_rows = (await db.execute(summary_stmt)).all()
    complete_trials_summary: list[tuple[float, int]] = [
        (row[0], row[1]) for row in summary_rows if row[0] is not None
    ]

    # Q4 (conditional): query_text for regressor candidates.
    # The pure orchestrator runs compute_outcome_summary again internally —
    # the second call is cheap (dict-key iteration on ≤100 queries) and keeps
    # the pure-helper contract clean for unit tests. The per-query lookup key
    # must match what backend.app.eval.scoring.score persists (user-facing
    # @<k>-suffixed tokens), not the bare metric base name.
    query_text_by_id: dict[str, str] = {}
    study_objective = study.objective if isinstance(study.objective, dict) else {}
    if runner_up is not None and winner.per_query_metrics and runner_up.per_query_metrics:
        try:
            per_query_key = objective_metric_key(study_objective)
        except ValueError:
            per_query_key = None
        if per_query_key is not None:
            outcome = compute_outcome_summary(
                winner_per_query=winner.per_query_metrics,
                comparison_per_query=runner_up.per_query_metrics,
                metric=per_query_key,
            )
            if outcome is not None and (
                outcome.regressor_candidates or outcome.improver_candidates
            ):
                qids = [
                    qid
                    for (qid, *_) in (
                        *outcome.regressor_candidates,
                        *outcome.improver_candidates,
                    )
                ]
                q_stmt = select(Query.id, Query.query_text).where(Query.id.in_(qids))
                for qid, qtext in (await db.execute(q_stmt)).all():
                    query_text_by_id[qid] = qtext

    return compute_study_confidence(
        study_objective=study_objective,
        study_best_metric=study.best_metric,
        winner_trial=winner,
        runner_up_trial=runner_up,
        baseline_trial=baseline_trial,
        complete_trials_summary=complete_trials_summary,
        query_text_by_id=query_text_by_id,
    )
