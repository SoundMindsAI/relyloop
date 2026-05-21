"""Test-only seeding helper for E2E coverage of completed-study surfaces.

Drives a study deterministically through ``queued → running → completed`` and
populates the digest + a pending proposal so the frontend's digest panel
(seven InfoTooltip placements + AC-7 body content + the Open PR enabled
button) renders against real backend rows instead of mocked component data.

**Production-safe by construction.** The router that exposes this helper
(``backend/app/api/v1/_test.py``) gates on ``Settings.environment ==
"development"`` and returns 404 otherwise; the helper module itself has no
auth check — its sole caller is the gated router. Do not import this from
any production code path.

Origin: ``infra_e2e_seed_completed_study/idea.md`` (option 1 — API-direct
insertion path; alternative options 2/3 rejected for non-determinism and
brittleness).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import uuid_utils
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.services import study_state


@dataclass(frozen=True)
class SeededStudyTriple:
    """IDs returned by :func:`seed_study_completed_with_digest`."""

    study_id: str
    digest_id: str
    proposal_id: str | None


async def seed_study_completed_with_digest(  # pragma: no cover  - integration only
    db: AsyncSession,
    *,
    cluster_id: str,
    query_set_id: str,
    template_id: str,
    judgment_list_id: str,
    with_pending_proposal: bool = True,
    winner_per_query: dict[str, dict[str, Any]] | None = None,
    runner_up_per_query: dict[str, dict[str, Any]] | None = None,
) -> SeededStudyTriple:
    """Insert a complete study + 2 trials + digest (+ optional pending proposal).

    Drives the study through the legal state-machine transitions
    (``queued → running → completed``) via :mod:`study_state` so the
    FR-7 protection listener does not raise. Trials, digest, and proposal
    rows are inserted directly via the repo layer — they have no state
    machine.

    Caller is responsible for committing. The router commits once at the
    end of its handler.

    Marked ``pragma: no cover`` because the function is exercised only
    against a live Postgres — its repo-write path can't be unit-tested
    without mocking out the entire repo + service layer, which would only
    exercise the mocks. The integration test at
    ``backend/tests/integration/test_test_seeding.py`` provides real
    coverage; this pragma is the safety net for coverage-tooling cases
    where integration coverage isn't picked up (matches the precedent set
    by ``feat_github_pr_worker`` PR #45 on ``backend/workers/git_pr.py``).
    """
    study_id = str(uuid_utils.uuid7())

    await repo.create_study(
        db,
        id=study_id,
        name=f"e2e-seed-{study_id[:8]}",
        cluster_id=cluster_id,
        target="products",
        template_id=template_id,
        query_set_id=query_set_id,
        judgment_list_id=judgment_list_id,
        search_space={
            "params": {
                "title.boost": {"type": "float", "low": 0.5, "high": 5.0, "log": False},
            },
        },
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config={"max_trials": 2, "sampler": "tpe", "pruner": "none"},
        status="queued",
        optuna_study_name=study_id,
    )

    # Transition queued → running BEFORE inserting trials so the seeded data
    # mirrors the real orchestrator flow (study starts, then run_trial writes
    # rows as trials execute) per Gemini feedback on PR #130. start_study
    # returns the Study row with ``started_at`` stamped; we anchor trial
    # timestamps off that so they're internally consistent with the study.
    study = await study_state.start_study(db, study_id)
    started = study.started_at or datetime.now(UTC)

    # Trial 1 (winner): begins at study start, runs for 1200ms.
    # Trial 2 (loser):  begins 100ms after trial 1 ends, runs for 1100ms.
    # ``ended_at - started_at`` matches the stored ``duration_ms`` so any
    # downstream code that re-derives duration from the timestamp pair gets
    # the same answer the orchestrator's writer would have produced.
    winning_trial_id = str(uuid_utils.uuid7())
    losing_trial_id = str(uuid_utils.uuid7())
    # feat_pr_metric_confidence Story 2.3: when both per_query dicts are
    # supplied, attach them so the ConfidencePanel + PR body confidence
    # section render against real backend rows. None defaults preserve the
    # pre-feature behavior (NULL per_query_metrics, partial ConfidenceShape).
    winner_kwargs: dict[str, Any] = {}
    runner_up_kwargs: dict[str, Any] = {}
    if winner_per_query is not None:
        winner_kwargs["per_query_metrics"] = winner_per_query
    if runner_up_per_query is not None:
        runner_up_kwargs["per_query_metrics"] = runner_up_per_query

    await repo.create_trial(
        db,
        id=winning_trial_id,
        study_id=study_id,
        optuna_trial_number=0,
        params={"title.boost": 2.5},
        primary_metric=0.487,
        metrics={"ndcg@10": 0.487, "map": 0.412, "p@10": 0.5},
        duration_ms=1200,
        status="complete",
        error=None,
        started_at=started,
        ended_at=started + timedelta(milliseconds=1200),
        **winner_kwargs,
    )
    await repo.create_trial(
        db,
        id=losing_trial_id,
        study_id=study_id,
        optuna_trial_number=1,
        params={"title.boost": 0.8},
        primary_metric=0.412,
        metrics={"ndcg@10": 0.412, "map": 0.351, "p@10": 0.4},
        duration_ms=1100,
        status="complete",
        error=None,
        started_at=started + timedelta(milliseconds=1300),
        ended_at=started + timedelta(milliseconds=2400),
        **runner_up_kwargs,
    )

    await study_state.complete_study(
        db,
        study_id,
        best_metric=0.487,
        best_trial_id=winning_trial_id,
        stop_reason="max_trials_reached",
    )

    digest_id = str(uuid_utils.uuid7())
    await repo.create_digest(
        db,
        id=digest_id,
        study_id=study_id,
        narrative=(
            "Seeded digest narrative for E2E coverage. Tuning `title.boost` from 1.0 to "
            "2.5 lifted ndcg@10 from 0.412 (baseline) to 0.487 (+18.2%). The winning "
            "configuration is recommended for production rollout."
        ),
        parameter_importance={"title.boost": 1.0},
        recommended_config={"title.boost": 2.5},
        suggested_followups=[
            "Try varying `description.boost` next.",
            "Run with a larger query set to confirm the lift holds.",
        ],
        generated_by="local:e2e_seed",
    )

    proposal_id: str | None = None
    if with_pending_proposal:
        proposal_id = str(uuid_utils.uuid7())
        await repo.create_proposal(
            db,
            id=proposal_id,
            study_id=study_id,
            study_trial_id=winning_trial_id,
            cluster_id=cluster_id,
            template_id=template_id,
            config_diff={"title.boost": {"from": 1.0, "to": 2.5}},
            metric_delta={"ndcg@10": {"baseline": 0.412, "achieved": 0.487, "delta_pct": 18.2}},
            status="pending",
        )

    return SeededStudyTriple(
        study_id=study_id,
        digest_id=digest_id,
        proposal_id=proposal_id,
    )
