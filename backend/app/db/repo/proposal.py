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
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Digest, Proposal
from backend.app.db.repo._sort import (
    ParsedSort,
    keyset_predicate,
    order_by_clauses,
    parse_sort,
)

_PROPOSAL_SORT_COLUMNS: dict[str, object] = {
    "created_at": Proposal.created_at,
    "status": Proposal.status,
    "pr_state": Proposal.pr_state,
}

# Wire values for `?status=` filter on `GET /api/v1/proposals`.
# Values must match backend/app/db/models/proposal.py CHECK proposals_status_check.
ProposalStatusFilter = Literal["pending", "pr_opened", "pr_merged", "rejected"]
# Per chore_proposals_source_filter_server_side: distinguishes proposals
# derived from a completed study (study_id NOT NULL) from operator-authored
# manual proposals (study_id NULL).
ProposalSourceFilter = Literal["study", "manual"]


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


def _apply_source_filter(stmt: Any, source: ProposalSourceFilter | None) -> Any:
    """Apply the source filter to a Proposal SELECT or COUNT statement.

    ``study`` → ``study_id IS NOT NULL``;
    ``manual`` → ``study_id IS NULL``;
    ``None`` → no filter (caller wants both).
    """
    if source == "study":
        return stmt.where(Proposal.study_id.is_not(None))
    if source == "manual":
        return stmt.where(Proposal.study_id.is_(None))
    return stmt


async def list_proposals_paginated(
    db: AsyncSession,
    *,
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    status: ProposalStatusFilter | None = None,
    cluster_id: str | None = None,
    source: ProposalSourceFilter | None = None,
    template_id: str | None = None,
    study_id: str | None = None,
    sort: str | None = None,
) -> Sequence[Proposal]:
    """Cursor-paginated proposal list. Sort-aware (Story 1.3).

    Default ordering ``created_at DESC, id DESC``. ``?sort=`` switches to
    ``<col>:<dir>`` with explicit NULLS handling. ``template_id``
    filter (Story 1.5) narrows by ``proposals.template_id`` FK.
    ``source`` filter (per chore_proposals_source_filter_server_side)
    is the server-side equivalent of the UI's three-state chip.
    ``study_id`` filter narrows to proposals belonging to a single study
    (used by the study-detail page's pending-proposal lookup).
    """
    parsed_sort: ParsedSort | None = parse_sort(sort, _PROPOSAL_SORT_COLUMNS)
    stmt = select(Proposal)
    if status is not None:
        stmt = stmt.where(Proposal.status == status)
    if cluster_id is not None:
        stmt = stmt.where(Proposal.cluster_id == cluster_id)
    if template_id is not None:
        stmt = stmt.where(Proposal.template_id == template_id)
    if study_id is not None:
        stmt = stmt.where(Proposal.study_id == study_id)
    stmt = _apply_source_filter(stmt, source)
    if cursor is not None:
        cursor_value, cursor_id = cursor
        stmt = stmt.where(
            keyset_predicate(
                parsed_sort,
                cursor_value,
                cursor_id,
                default_col=Proposal.created_at,
                id_col=Proposal.id,
            )
        )
    stmt = stmt.order_by(
        *order_by_clauses(parsed_sort, default_col=Proposal.created_at, id_col=Proposal.id)
    ).limit(min(limit, 200))
    return list((await db.execute(stmt)).scalars().all())


async def count_proposals(
    db: AsyncSession,
    *,
    status: ProposalStatusFilter | None = None,
    cluster_id: str | None = None,
    source: ProposalSourceFilter | None = None,
    template_id: str | None = None,
    study_id: str | None = None,
) -> int:
    """COUNT(*) for the ``X-Total-Count`` header on ``GET /api/v1/proposals``.

    ``template_id`` filter (Story 1.5) narrows by FK. ``study_id`` filter
    narrows to a single study.
    """
    stmt = select(func.count()).select_from(Proposal)
    if status is not None:
        stmt = stmt.where(Proposal.status == status)
    if cluster_id is not None:
        stmt = stmt.where(Proposal.cluster_id == cluster_id)
    if template_id is not None:
        stmt = stmt.where(Proposal.template_id == template_id)
    if study_id is not None:
        stmt = stmt.where(Proposal.study_id == study_id)
    stmt = _apply_source_filter(stmt, source)
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


async def mark_proposal_pr_opened(
    db: AsyncSession,
    proposal_id: str,
    *,
    pr_url: str,
) -> Proposal | None:
    """Conditional UPDATE: pending → pr_opened + populate pr_url + pr_state='open'.

    feat_github_pr_worker Story 1.1 — the worker's final write after a
    successful GitHub PR open. The conditional ``WHERE status='pending'``
    guard mirrors :func:`update_proposal_for_digest`'s cycle-3 F4 pattern:
    if the operator rejected the proposal mid-flight (between the
    worker's preflight and this final UPDATE), zero rows match and we
    return ``None``. The worker then logs
    ``pr_open_proposal_no_longer_pending`` and skips the update — the
    rejection persists, and the operator manually closes the orphan PR
    on GitHub.

    Returns the updated row, or ``None`` if zero rows matched. Caller
    commits. Also clears any prior ``pr_open_error`` so a successful
    retry blanks the stale failure message (per spec FR-4).

    ``pr_url`` MUST be GitHub's ``html_url`` (e.g.
    ``https://github.com/{owner}/{repo}/pull/N``), NOT the API URL or
    the tokenized clone URL (spec FR-5 / AC-7).
    """
    stmt = (
        update(Proposal)
        .where(Proposal.id == proposal_id, Proposal.status == "pending")
        .values(
            pr_url=pr_url,
            pr_state="open",
            status="pr_opened",
            pr_open_error=None,
        )
        .returning(Proposal)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.flush()
    return row


async def set_proposal_pr_open_error(
    db: AsyncSession,
    proposal_id: str,
    *,
    error: str,
) -> Proposal | None:
    """Conditional UPDATE: populate ``pr_open_error`` WHERE status='pending'.

    feat_github_pr_worker Story 1.1 — the worker's failure-path write.
    Same conditional-pending guard as :func:`mark_proposal_pr_opened`:
    if the operator rejected mid-flight, the rejection rationale stays
    in ``rejected_reason`` and we don't overwrite it.

    Returns the updated row, or ``None`` if zero rows matched (the
    proposal is no longer pending). Caller commits.

    The ``error`` string MUST already be token-redacted by the caller —
    this repo function does no redaction (the worker owns the
    redaction filter; this is a pure data path).
    """
    stmt = (
        update(Proposal)
        .where(Proposal.id == proposal_id, Proposal.status == "pending")
        .values(pr_open_error=error)
        .returning(Proposal)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.flush()
    return row


async def mark_proposal_pr_merged(
    db: AsyncSession,
    proposal_id: str,
    *,
    pr_merged_at: datetime,
) -> Proposal | None:
    """Conditional UPDATE: pr_opened+open → pr_merged + populate pr_merged_at.

    feat_github_webhook Story 1.4 — webhook receiver + polling reconciler
    transition on a successful PR merge. ``WHERE status='pr_opened' AND
    pr_state='open'``: if the proposal was already merged via the other
    delivery path (webhook arrived before polling, or vice versa), zero
    rows match and we return ``None``. The caller logs benignly and
    skips. Caller commits.
    """
    stmt = (
        update(Proposal)
        .where(
            Proposal.id == proposal_id,
            Proposal.status == "pr_opened",
            Proposal.pr_state == "open",
        )
        .values(
            status="pr_merged",
            pr_state="merged",
            pr_merged_at=pr_merged_at,
        )
        .returning(Proposal)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.flush()
    return row


async def mark_proposal_pr_closed(
    db: AsyncSession,
    proposal_id: str,
) -> Proposal | None:
    """Conditional UPDATE: pr_opened+open → pr_opened+closed (status stays).

    feat_github_webhook Story 1.4 — PR was closed without being merged.
    Status STAYS ``pr_opened`` so the operator can re-``open_pr`` (spec §11
    downstream-invariant audit). ``WHERE status='pr_opened' AND
    pr_state='open'``: idempotent for repeated closed events; second
    delivery matches zero rows and returns ``None``. Caller commits.
    """
    stmt = (
        update(Proposal)
        .where(
            Proposal.id == proposal_id,
            Proposal.status == "pr_opened",
            Proposal.pr_state == "open",
        )
        .values(pr_state="closed")
        .returning(Proposal)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.flush()
    return row


async def mark_proposal_pr_reopened(
    db: AsyncSession,
    proposal_id: str,
) -> Proposal | None:
    """Conditional UPDATE: pr_opened+closed → pr_opened+open.

    feat_github_webhook Story 1.4 — operator re-opened a previously
    closed PR. ``WHERE status='pr_opened' AND pr_state='closed'``:
    repeat ``reopened`` events match zero rows and return ``None``.
    Caller commits.
    """
    stmt = (
        update(Proposal)
        .where(
            Proposal.id == proposal_id,
            Proposal.status == "pr_opened",
            Proposal.pr_state == "closed",
        )
        .values(pr_state="open")
        .returning(Proposal)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.flush()
    return row


async def lookup_proposal_by_pr_url(
    db: AsyncSession,
    pr_url: str,
) -> Proposal | None:
    """Single-row SELECT keyed on ``pr_url``. Returns the row or ``None``.

    feat_github_webhook Story 1.4 — webhook receiver maps GitHub's
    ``pull_request.html_url`` back to the originating proposal. Uses the
    partial index ``proposals_pr_url_idx`` (Story 1.1) so the lookup is
    sub-millisecond even at 100K proposals.
    """
    stmt = select(Proposal).where(Proposal.pr_url == pr_url)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_pr_opened_proposals_for_reconcile(
    db: AsyncSession,
) -> Sequence[Proposal]:
    """Return ``pr_opened`` + ``open`` proposals newer than 90 days.

    feat_github_webhook Story 1.4 — consumed by ``reconcile_pr_state``
    (Story 3.1). The 90-day window caps polling growth per spec FR-2:
    older stale-pr_opened rows are presumed permanently abandoned and
    require operator triage.
    """
    cutoff = datetime.now(UTC) - timedelta(days=90)
    stmt = (
        select(Proposal)
        .where(
            Proposal.status == "pr_opened",
            Proposal.pr_state == "open",
            Proposal.pr_url.is_not(None),
            Proposal.created_at > cutoff,
        )
        .order_by(Proposal.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


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
