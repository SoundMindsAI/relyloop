"""Judgment-list repository (feat_study_lifecycle Phase 1, Story 1.3).

Phase 1 ships create + get (the latter consumed by `infra_optuna_eval`'s
`run_trial` to load the rubric / target / cluster context). Phase 2
extends; `feat_llm_judgments` later adds the LLM-runner that populates
the child ``judgments`` table.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import JudgmentList


async def create_judgment_list(db: AsyncSession, **fields: object) -> JudgmentList:
    """Stage a new ``JudgmentList`` row. Caller commits."""
    judgment_list = JudgmentList(**fields)
    db.add(judgment_list)
    await db.flush()
    await db.refresh(judgment_list)
    return judgment_list


async def get_judgment_list(db: AsyncSession, judgment_list_id: str) -> JudgmentList | None:
    """Fetch a judgment list by id."""
    stmt = select(JudgmentList).where(JudgmentList.id == judgment_list_id)
    return (await db.execute(stmt)).scalar_one_or_none()
