"""Study repository (feat_study_lifecycle Phase 1, Story 1.3).

Phase 1 ships create + get (the latter consumed by `infra_optuna_eval`'s
`run_trial` to load the cluster_id + template_id + judgment_list_id +
search_space + objective). Phase 2 extends with cursor-paginated list +
status filtering + the orchestrator's status-mutation helpers (which
will go through the service layer per FR-7).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Study


async def create_study(db: AsyncSession, **fields: object) -> Study:
    """Stage a new ``Study`` row. Caller commits.

    The study row is created via this repo function in tests; production
    creation goes through ``backend/services/study_state.py:create_study()``
    (Phase 2) which enforces the state-machine invariants.
    """
    study = Study(**fields)
    db.add(study)
    await db.flush()
    await db.refresh(study)
    return study


async def get_study(db: AsyncSession, study_id: str) -> Study | None:
    """Fetch a study by id."""
    stmt = select(Study).where(Study.id == study_id)
    return (await db.execute(stmt)).scalar_one_or_none()
