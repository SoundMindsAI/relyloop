# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Chain-rollup service — supersede non-winning chain links' proposals.

feat_overnight_final_solution_phase3 Story 2.1 (FR-2).

Walks the chain anchored at a given study, identifies the winner via
:func:`select_best_link` (Phase 1 infra), and delegates the loser
supersession to :func:`repo.bulk_mark_superseded`. Returns the
``(superseded_count, superseded_ids)`` tuple so the caller can emit the
``chain_proposals_superseded`` structlog event AFTER its commit succeeds
(spec D-19). Does NOT commit; caller commits per the service-layer
convention.

The service is chain-scoped, not proposal-scoped — landing under
``services/`` rather than appending to ``agent_proposals_dispatch.py``
keeps it usable by both the autopilot path (``_stop`` in
``backend/workers/orchestrator.py``) and any future chat-agent surface
(spec D-4 / Q5 locked).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db import repo
from backend.app.db.repo import ChainTraversalResult
from backend.app.domain.study.chain_summary import (
    derive_chain_stop_reason,
    select_best_link,
)


async def mark_non_winning_chain_proposals_superseded(
    db: AsyncSession,
    *,
    study_id: str,
    traversal: ChainTraversalResult | None = None,
) -> tuple[int, list[str]]:
    """Supersede ``pending`` proposals of all chain links other than the winner.

    Walks the chain anchored at the study root of ``study_id`` and, when
    the chain has terminated with at least 2 completed links and a clear
    best link, conditional-UPDATEs all sibling losers' ``pending``
    proposals to ``superseded`` (via :func:`repo.bulk_mark_superseded`).

    Returns ``(count, ids)`` — the count and IDs actually transitioned —
    so the caller can emit the post-commit ``chain_proposals_superseded``
    structlog event with the full IDs payload per spec D-19.

    ``traversal`` is an optional pre-fetched
    :class:`~backend.app.db.repo.ChainTraversalResult`. When the caller
    has already walked the chain (e.g. ``_stop`` reads it to capture the
    anchor + winner for its log payload), passing it here avoids a
    duplicate ``get_chain_for_study`` round-trip. When ``None`` the
    function fetches it itself.

    Idempotent. Re-running on the same chain after a successful first
    call returns ``(0, [])`` (the losers are now ``superseded`` and the
    repo helper's ``WHERE status='pending'`` clause excludes them).

    Early-returns ``(0, [])`` when:
        a. the chain is missing (study not found).
        b. The chain has fewer than 2 links (single-link chain has no
           siblings to supersede).
        c. The derived ``stop_reason == "in_flight"`` (chain still
           running; rollup deferred until termination).
        d. :func:`select_best_link` returns ``None`` (no completed link →
           no winner → nothing to supersede against).

    Does NOT commit. Caller commits as part of its own transaction
    boundary (e.g., ``_stop`` commits the link's ``pending`` proposal
    insert and the rollup in the same transaction).
    """
    if traversal is None:
        traversal = await repo.get_chain_for_study(db, study_id)
    if traversal is None:
        return (0, [])
    if len(traversal.links) < 2:
        return (0, [])
    stop_reason = derive_chain_stop_reason(traversal.links, traversal.anchor_trials)
    if stop_reason == "in_flight":
        return (0, [])
    best_link_id = select_best_link(traversal.links)
    if best_link_id is None:
        return (0, [])
    loser_ids = [link.id for link in traversal.links if link.id != best_link_id]
    transitioned = await repo.bulk_mark_superseded(db, study_ids=loser_ids)
    return (len(transitioned), transitioned)
