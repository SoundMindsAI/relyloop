"""Proposal repository (feat_study_lifecycle Phase 1 + feat_digest_proposal Story 1.2).

Phase 1 (feat_study_lifecycle) shipped ``create_proposal`` + ``get_proposal``.
feat_digest_proposal extends with:

* :func:`update_proposal_for_digest` — conditional UPDATE on the pending
  row (cycle-3 F4 — ``WHERE id=:id AND status='pending'`` so an
  operator-rejected proposal isn't silently overwritten mid-LLM-call).
* :func:`list_proposals_paginated` — cursor + status + cluster_id filter.
* :func:`count_proposals` — ``X-Total-Count`` header.
* :func:`reject_proposal` — ``pending → rejected`` transition; raises
  ``InvalidStateTransition`` if the proposal is not pending.
* :func:`list_pending_proposals_for_boot_scan` — study_ids of pending
  proposals lacking a digest, for the FR-2b on_startup sweep.

Downstream consumers:
- ``feat_digest_proposal`` worker calls ``update_proposal_for_digest`` after
  computing the deterministic ``recommended_config`` (per the cycle-1 F5 /
  cycle-2 F1 design).
- ``feat_github_pr_worker`` (future) will add ``mark_proposal_pr_opened`` /
  ``mark_proposal_pr_merged`` for the ``pending → pr_opened → pr_merged``
  transitions.
- ``feat_chat_agent`` (future) calls ``create_proposal`` for hand-crafted
  proposals (study_id + study_trial_id + metric_delta all NULL).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Digest, Proposal

# Wire values for `?status=` filter on `GET /api/v1/proposals`.
# Values must match backend/app/db/models/proposal.py CHECK proposals_status_check.
ProposalStatusFilter = Literal["pending", "pr_opened", "pr_merged", "rejected"]


class InvalidStateTransition(RuntimeError):
    """Raised by :func:`reject_proposal` when the target row is not ``pending``.

    The service / API layer translates this to HTTP 409
    ``INVALID_STATE_TRANSITION`` per spec §8.5. Carries the proposal id +
    the current status so the caller can render a precise error message.
    """

    def __init__(self, proposal_id: str, current_status: str) -> None:
        """Capture the proposal id + current status for the 409 error envelope."""
        super().__init__(
            f"proposal {proposal_id!r} is in status {current_status!r}; "
            "only 'pending' proposals can be rejected"
        )
        self.proposal_id = proposal_id
        self.current_status = current_status


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


# ---------------------------------------------------------------------------
# feat_digest_proposal Story 1.2 extensions
# ---------------------------------------------------------------------------


async def update_proposal_for_digest(
    db: AsyncSession,
    proposal_id: str,
    *,
    config_diff: dict[str, Any],
    metric_delta: dict[str, Any] | None,
) -> Proposal | None:
    """Conditional UPDATE: populate ``config_diff`` + ``metric_delta`` on a pending row.

    Cycle-3 F4: the UPDATE is gated on ``WHERE status='pending'``. If the
    proposal was rejected between the worker's pre-LLM read and this
    post-LLM call, the UPDATE matches zero rows and this function returns
    ``None``. The worker logs ``digest_proposal_no_longer_pending`` and
    persists the digest anyway — the digest is per-study, not per-proposal,
    so the rejected proposal doesn't invalidate the narrative.

    Returns the updated ``Proposal`` row, or ``None`` if no row matched.
    Caller commits.
    """
    stmt = (
        update(Proposal)
        .where(Proposal.id == proposal_id, Proposal.status == "pending")
        .values(config_diff=config_diff, metric_delta=metric_delta)
        .returning(Proposal)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.flush()
    return row


async def list_proposals_paginated(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    status: ProposalStatusFilter | None = None,
    cluster_id: str | None = None,
) -> Sequence[Proposal]:
    """Cursor-paginated proposal list, newest first by ``created_at``.

    Order: ``created_at DESC, id DESC`` — mirrors
    :func:`backend.app.db.repo.study.list_studies` row-value comparison
    pattern. Limit clamped at 200 per api-conventions.md.
    """
    stmt = select(Proposal)
    if status is not None:
        stmt = stmt.where(Proposal.status == status)
    if cluster_id is not None:
        stmt = stmt.where(Proposal.cluster_id == cluster_id)
    if cursor is not None:
        cursor_at, cursor_id = cursor
        stmt = stmt.where(
            or_(
                Proposal.created_at < cursor_at,
                and_(Proposal.created_at == cursor_at, Proposal.id < cursor_id),
            )
        )
    stmt = stmt.order_by(Proposal.created_at.desc(), Proposal.id.desc()).limit(min(limit, 200))
    return list((await db.execute(stmt)).scalars().all())


async def count_proposals(
    db: AsyncSession,
    *,
    status: ProposalStatusFilter | None = None,
    cluster_id: str | None = None,
) -> int:
    """COUNT(*) for the ``X-Total-Count`` header on ``GET /api/v1/proposals``."""
    stmt = select(func.count()).select_from(Proposal)
    if status is not None:
        stmt = stmt.where(Proposal.status == status)
    if cluster_id is not None:
        stmt = stmt.where(Proposal.cluster_id == cluster_id)
    return int((await db.execute(stmt)).scalar_one())


async def reject_proposal(
    db: AsyncSession,
    proposal_id: str,
    *,
    reason: str | None,
) -> Proposal:
    """Transition ``pending → rejected``; populate ``rejected_reason``.

    Raises :class:`InvalidStateTransition` if the proposal is not in
    ``pending`` status (the API translates to HTTP 409). Raises
    ``LookupError`` if the proposal id does not exist (the API has
    already SELECT'd it to return 404; this is defense-in-depth).
    Caller commits.
    """
    row = await get_proposal(db, proposal_id)
    if row is None:
        raise LookupError(f"proposal {proposal_id!r} not found")
    if row.status != "pending":
        raise InvalidStateTransition(proposal_id, row.status)
    row.status = "rejected"
    row.rejected_reason = reason
    await db.flush()
    return row


async def list_pending_proposals_for_boot_scan(db: AsyncSession) -> list[str]:
    """Return study_ids of pending proposals lacking a digest (FR-2b).

    Used by :func:`backend.workers.all.on_startup` to re-enqueue
    ``generate_digest`` for any study whose ``complete_study`` transaction
    committed (pending proposal exists) but whose digest hasn't been
    written yet — covers the case where the worker was down between the
    orchestrator's commit and its fast-path Arq enqueue at
    ``orchestrator.py:370``.

    Query: ``SELECT p.study_id FROM proposals p
            LEFT JOIN digests d ON d.study_id = p.study_id
            WHERE p.status = 'pending' AND p.study_id IS NOT NULL
                  AND d.id IS NULL``.

    Manual proposals (``study_id IS NULL``) are excluded — they have no
    associated study and no digest is expected.
    """
    stmt = (
        select(Proposal.study_id)
        .outerjoin(Digest, Digest.study_id == Proposal.study_id)
        .where(Proposal.status == "pending")
        .where(Proposal.study_id.is_not(None))
        .where(Digest.id.is_(None))
    )
    return [row for row in (await db.execute(stmt)).scalars().all() if row is not None]
