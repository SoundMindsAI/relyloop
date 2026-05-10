"""Proposal repository (feat_study_lifecycle Phase 1, Story 1.3).

Phase 1 ships create + get. Downstream consumers:
- ``feat_digest_proposal`` calls ``create_proposal`` after generating a
  study digest (winning trial → config_diff + metric_delta).
- ``feat_github_pr_worker`` calls ``get_proposal`` + status-update helpers
  (added in that feature) to open the PR + stamp ``pr_url`` / ``pr_state``.
- ``feat_chat_agent`` calls ``create_proposal`` for hand-crafted proposals
  (study_id + study_trial_id + metric_delta all NULL).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Proposal


async def create_proposal(db: AsyncSession, **fields: object) -> Proposal:
    """Stage a new ``Proposal`` row. Caller commits."""
    proposal = Proposal(**fields)
    db.add(proposal)
    await db.flush()
    await db.refresh(proposal)
    return proposal


async def get_proposal(db: AsyncSession, proposal_id: str) -> Proposal | None:
    """Fetch a proposal by id."""
    stmt = select(Proposal).where(Proposal.id == proposal_id)
    return (await db.execute(stmt)).scalar_one_or_none()
