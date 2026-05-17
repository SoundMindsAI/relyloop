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
from datetime import UTC, datetime

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


async def seed_study_completed_with_digest(
    db: AsyncSession,
    *,
    cluster_id: str,
    query_set_id: str,
    template_id: str,
    judgment_list_id: str,
    with_pending_proposal: bool = True,
) -> SeededStudyTriple:
    """Insert a complete study + 2 trials + digest (+ optional pending proposal).

    Drives the study through the legal state-machine transitions
    (``queued → running → completed``) via :mod:`study_state` so the
    FR-7 protection listener does not raise. Trials, digest, and proposal
    rows are inserted directly via the repo layer — they have no state
    machine.

    Caller is responsible for committing. The router commits once at the
    end of its handler.
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

    # Insert two trials before transitioning to ``completed`` so the
    # state machine's denormalized ``best_trial_id`` FK has a real row to
    # reference (``best_trial_id`` is not a formal FK at the DB level but
    # the orchestrator's invariant is that it points to an existing trial).
    winning_trial_id = str(uuid_utils.uuid7())
    losing_trial_id = str(uuid_utils.uuid7())
    started = datetime.now(UTC)
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
        ended_at=started,
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
        started_at=started,
        ended_at=started,
    )

    await study_state.start_study(db, study_id)
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
