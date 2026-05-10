"""Trial repository (feat_study_lifecycle Phase 1, Story 1.3).

Phase 1 ships create + list-for-study. ``create_trial`` is the
single-write hot path consumed by `infra_optuna_eval`'s `run_trial` job
(per spec FR-4: "writes a trials row" — one INSERT per trial, even on
failure). ``list_trials_for_study`` powers Phase 2's
``GET /studies/{id}/trials`` endpoint and the trials_summary aggregation.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Trial


async def create_trial(db: AsyncSession, **fields: object) -> Trial:
    """Stage a new ``Trial`` row. Caller commits.

    Hot path — `infra_optuna_eval`'s `run_trial` Arq job calls this once
    per trial with the final status (``complete | failed | pruned``) and
    the populated ``metrics`` / ``primary_metric`` / ``params`` /
    ``duration_ms`` fields.
    """
    trial = Trial(**fields)
    db.add(trial)
    await db.flush()
    await db.refresh(trial)
    return trial


async def list_trials_for_study(db: AsyncSession, study_id: str) -> Sequence[Trial]:
    """List every trial in a study, ordered by Optuna trial number ASC."""
    stmt = select(Trial).where(Trial.study_id == study_id).order_by(Trial.optuna_trial_number)
    result = await db.execute(stmt)
    return list(result.scalars().all())
