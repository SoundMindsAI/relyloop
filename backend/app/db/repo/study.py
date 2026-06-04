# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Study repository (feat_study_lifecycle Phase 1 Story 1.3 + Phase 2 Story 1.4).

Phase 1 shipped create + get. Phase 2 extends with cursor-paginated list +
status filtering + ``?since=`` filter + count for the X-Total-Count header
+ a running-study-ids helper used by the orchestrator's resume-on-startup
sweep (FR-5).

Cursor pagination matches the ``backend.app.db.repo.cluster`` precedent:
``(created_at, id)`` ordering DESC with row-value comparison hand-rolled
for portability across Postgres / SQLite.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Proposal, Study, Trial
from backend.app.db.repo._fts import fts_predicate
from backend.app.db.repo._sort import (
    ParsedSort,
    keyset_predicate,
    order_by_clauses,
    parse_sort,
)
from backend.app.domain.study.chain_summary import derive_chain_stop_reason

logger = logging.getLogger(__name__)

# Allowlist for ``?sort=<col>:<dir>`` on ``/api/v1/studies``. Keys mirror
# ``StudySortKey`` Literal in ``backend.app.api.v1.schemas``.
_STUDY_SORT_COLUMNS: dict[str, object] = {
    "name": Study.name,
    "created_at": Study.created_at,
    "completed_at": Study.completed_at,
    "best_metric": Study.best_metric,
    "status": Study.status,
}

# Wire values for `?status=` filter on `GET /api/v1/studies`.
# Must match backend/app/db/models/study.py CHECK constraint + the
# StudyStatusWire Literal in backend/app/api/v1/schemas.py.
StudyStatusFilter = Literal["queued", "running", "completed", "cancelled", "failed"]


async def create_study(db: AsyncSession, **fields: object) -> Study:
    """Stage a new ``Study`` row. Caller commits.

    The study row is created via this repo function in tests; production
    creation goes through ``backend/services/study_state.py`` for
    status-mutating operations (Phase 2 FR-7).
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


async def list_studies(
    db: AsyncSession,
    *,
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
    cluster_id: str | None = None,
    target: str | None = None,
    q: str | None = None,
    sort: str | None = None,
) -> Sequence[Study]:
    """Cursor-paginated study list.

    Default ordering: ``created_at DESC, id DESC``. When ``sort`` is non-default
    (e.g. ``name:asc``, ``best_metric:desc``), the ORDER BY + keyset cursor
    predicate are switched accordingly with explicit NULLS handling and
    ``id DESC`` tie-breaker.

    ``since`` filters to ``created_at >= since``. ``status`` filters to a
    single state. ``cluster_id`` scopes to studies belonging to a single
    cluster (used by the cluster detail page's "Studies using this cluster"
    section). ``target`` (feat_index_document_browser FR-5) scopes to studies
    targeting a single index/collection on the cluster — composes with
    ``cluster_id`` to drive the index summary page's "studies targeting this
    index" link. ``q`` is an optional Postgres FTS match against
    ``search_vector`` (studies.name + target). Limit clamped at 200.
    """
    parsed_sort: ParsedSort | None = parse_sort(sort, _STUDY_SORT_COLUMNS)
    stmt = select(Study)
    if status is not None:
        stmt = stmt.where(Study.status == status)
    if since is not None:
        stmt = stmt.where(Study.created_at >= since)
    if cluster_id is not None:
        stmt = stmt.where(Study.cluster_id == cluster_id)
    if target is not None:
        stmt = stmt.where(Study.target == target)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    if cursor is not None:
        cursor_value, cursor_id = cursor
        stmt = stmt.where(
            keyset_predicate(
                parsed_sort,
                cursor_value,
                cursor_id,
                default_col=Study.created_at,
                id_col=Study.id,
            )
        )
    stmt = stmt.order_by(
        *order_by_clauses(parsed_sort, default_col=Study.created_at, id_col=Study.id)
    ).limit(min(limit, 200))
    return list((await db.execute(stmt)).scalars().all())


async def count_studies(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    status: StudyStatusFilter | None = None,
    cluster_id: str | None = None,
    target: str | None = None,
    q: str | None = None,
) -> int:
    """COUNT(*) studies matching the filter (for the X-Total-Count header).

    ``target`` (feat_index_document_browser FR-5) composes with all other
    filters via AND.
    """
    stmt = select(func.count(Study.id))
    if status is not None:
        stmt = stmt.where(Study.status == status)
    if since is not None:
        stmt = stmt.where(Study.created_at >= since)
    if cluster_id is not None:
        stmt = stmt.where(Study.cluster_id == cluster_id)
    if target is not None:
        stmt = stmt.where(Study.target == target)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    return int((await db.execute(stmt)).scalar_one())


async def list_running_study_ids(db: AsyncSession) -> list[str]:
    """Return ids of every study currently in ``status='running'``.

    Consumed by the worker's ``on_startup`` resume sweep (Story 2.3 / FR-5):
    after a worker restart, every running study gets a fresh
    ``resume_study`` Arq job enqueued so the orchestrator loop re-enters.
    """
    stmt = select(Study.id).where(Study.status == "running")
    return list((await db.execute(stmt)).scalars().all())


async def list_queued_study_ids(db: AsyncSession) -> list[str]:
    """Return ids of every study currently in ``status='queued'``.

    Consumed by the worker's ``on_startup`` sweep to pick up studies whose
    ``POST /studies`` enqueue was lost (e.g., the API committed the row
    but the Arq pool was unreachable at the time). Without this, a study
    that the API failed to enqueue would sit at ``queued`` forever — the
    ``running``-only sweep wouldn't re-dispatch it.
    """
    stmt = select(Study.id).where(Study.status == "queued")
    return list((await db.execute(stmt)).scalars().all())


async def list_children_of_study(
    db: AsyncSession,
    parent_study_id: str,
) -> Sequence[Study]:
    """Return DIRECT children of ``parent_study_id`` (Story 1.3, FR-10 + D-13).

    Filters by ``parent_study_id == parent_study_id``. Ordered by
    ``created_at ASC`` so the UI chain panel renders the oldest direct
    child first (chains are linear in v1 so there's at most one child;
    ordering matters only if a future feature lets a single parent fan
    out to multiple children).

    Returns an empty :class:`~collections.abc.Sequence` (not ``None``) for
    a study with no children — the children endpoint returns
    ``{"data": [], "next_cursor": null}`` for childless rather than 404.

    No ``deleted_at`` filter: Study has no soft-delete column in MVP1;
    the only delete path is ``hard_delete_study`` for test-only cleanup
    (so deleted rows are gone, not flagged). If MVP4 adds soft-delete,
    revisit this filter.
    """
    stmt = (
        select(Study)
        .where(Study.parent_study_id == parent_study_id)
        .order_by(Study.created_at.asc(), Study.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# feat_overnight_autopilot Story 1.2 — chain traversal for the rolled-up
# overnight-chain summary (FR-3). Pure read; the router (Story 1.3) feeds the
# result into the chain_summary.py domain helpers (Story 1.1).
# ---------------------------------------------------------------------------

#: Defensive cap on the upward ``parent_study_id`` walk. The chaining engine
#: enforces ``auto_followup_depth <= 5`` (max chain length 6), so a healthy
#: chain never exceeds 6 hops; 10 leaves slack while still terminating on a
#: cyclic graph that should be impossible (spec §9 invariant).
_CHAIN_UPWARD_HOP_CAP = 10

#: Max descendants below the anchor (anchor + 5 = 6 rows max, per D-7).
_CHAIN_MAX_DESCENDANTS = 5


@dataclass(frozen=True)
class ChainTraversalResult:
    """Hydrated linear chain anchored at the root ancestor of a study.

    ``links`` is ordered ``created_at ASC, id ASC`` (anchor first) and is
    length 1..6 under the D-7 linear-chain invariant.
    ``proposal_id_by_link_id`` maps a link id to its selected (newest
    non-rejected) proposal id — a missing key means no surfaceable proposal
    for that link. ``anchor_trials`` is populated ONLY when the anchor's
    ``baseline_metric IS NULL`` (the first-decile fallback input for
    ``compute_cumulative_lift`` / ``derive_chain_stop_reason``).
    """

    anchor_id: str
    links: list[Study]
    proposal_id_by_link_id: dict[str, str]
    anchor_trials: list[Trial] | None


async def get_chain_for_study(
    db: AsyncSession,
    study_id: str,
) -> ChainTraversalResult | None:
    """Traverse the linear study chain anchored at ``study_id``'s root (FR-3).

    Returns ``None`` when ``study_id`` does not exist. Otherwise walks up
    ``parent_study_id`` to the anchor (defensively capped at 10 hops with a
    visited-set cycle guard + WARN log), then walks down one child per parent
    (``LIMIT 1`` ordered ``created_at ASC, id ASC``, capped at 5 descendants,
    WARN-logging any fan-out), hydrates the link rows, resolves each link's
    newest non-rejected proposal, and — only when the anchor lacks an
    explicit baseline — loads the anchor's complete trials for the
    first-decile fallback. Pure read; no mutation.
    """
    # --- 1. Upward walk to the anchor (root ancestor). -----------------
    head = await db.execute(select(Study.id, Study.parent_study_id).where(Study.id == study_id))
    head_row = head.first()
    if head_row is None:
        return None

    anchor_id: str = head_row.id
    parent_id: str | None = head_row.parent_study_id
    visited: set[str] = {anchor_id}
    hops = 0
    while parent_id is not None:
        if hops >= _CHAIN_UPWARD_HOP_CAP or parent_id in visited:
            logger.warning(
                "chain upward walk hit defensive cap or cycle; treating walk-stop point as anchor",
                extra={"study_id": study_id, "hop_count": hops, "stopped_at": anchor_id},
            )
            break
        row = (
            await db.execute(select(Study.id, Study.parent_study_id).where(Study.id == parent_id))
        ).first()
        if row is None:
            break  # dangling parent FK — treat current as anchor
        anchor_id = row.id
        visited.add(anchor_id)
        parent_id = row.parent_study_id
        hops += 1

    # --- 2. Downward walk: one child per parent, capped at 5 descendants.
    # Fresh visited set seeded only with the anchor — the upward-walk
    # ``visited`` set includes the original start node, which IS a legitimate
    # descendant of the anchor and must not be cycle-guarded out.
    link_ids: list[str] = [anchor_id]
    down_visited: set[str] = {anchor_id}
    cur = anchor_id
    descendants = 0
    while descendants < _CHAIN_MAX_DESCENDANTS:
        children = (
            await db.execute(
                select(Study.id)
                .where(Study.parent_study_id == cur)
                .order_by(Study.created_at.asc(), Study.id.asc())
                .limit(2)
            )
        ).all()
        if not children:
            break
        if len(children) > 1:
            logger.warning(
                "chain downward walk found a fan-out (>1 child); taking the first "
                "by (created_at, id) and dropping siblings (linear-chain invariant)",
                extra={"parent_study_id": cur, "child_count": len(children)},
            )
        next_id = children[0].id
        if next_id in down_visited:
            break  # cycle guard on the downward side too
        link_ids.append(next_id)
        down_visited.add(next_id)
        cur = next_id
        descendants += 1

    # --- 3. Hydrate link rows; reorder client-side by (created_at, id). ---
    rows = list((await db.execute(select(Study).where(Study.id.in_(link_ids)))).scalars().all())
    if not rows:
        # Every walked link was hard-deleted between the existence check and
        # this hydration (concurrent-delete race — reachable via the _test
        # hard-delete teardown path). Return None so the router renders a clean
        # 404 STUDY_NOT_FOUND rather than letting the caller hit IndexError on
        # links[0].
        return None
    links = sorted(rows, key=lambda s: (s.created_at, s.id))

    # --- 4. Proposal lookup: newest non-rejected per link. ---------------
    proposal_rows = (
        await db.execute(
            select(Proposal.id, Proposal.study_id)
            .where(Proposal.study_id.in_(link_ids), Proposal.status != "rejected")
            .order_by(
                Proposal.study_id,
                Proposal.created_at.desc(),
                Proposal.id.desc(),
            )
            .distinct(Proposal.study_id)
        )
    ).all()
    proposal_id_by_link_id: dict[str, str] = {
        row.study_id: row.id for row in proposal_rows if row.study_id is not None
    }

    # --- 5. Anchor-trials lookup: ONLY when anchor baseline IS NULL. ------
    anchor = links[0]
    anchor_trials: list[Trial] | None = None
    if anchor.baseline_metric is None:
        anchor_trials = list(
            (
                await db.execute(
                    select(Trial).where(Trial.study_id == anchor.id, Trial.status == "complete")
                )
            )
            .scalars()
            .all()
        )

    return ChainTraversalResult(
        anchor_id=anchor.id,
        links=links,
        proposal_id_by_link_id=proposal_id_by_link_id,
        anchor_trials=anchor_trials,
    )


# ---------------------------------------------------------------------------
# feat_overnight_studies_summary_card Story 1.1 — recent-completed-chains
# discovery feeding the "Ran while you were away" card on /studies (FR-1).
# Pure read; one row per chain (anchor-deduped); terminal-only; length >= 2;
# in-flight defensively excluded; tail-completion-DESC ordering.
# ---------------------------------------------------------------------------


_TERMINAL_STUDY_STATUSES: tuple[str, ...] = ("completed", "cancelled", "failed")


async def list_recent_completed_chains(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    limit: int = 20,
) -> list[ChainTraversalResult]:
    """Return de-duplicated completed overnight chains (length >= 2).

    Newest tail-completion first, capped at ``limit`` distinct chains.

    Algorithm (FR-1):

    1. SELECT candidate member ids — studies that ARE follow-up children
       (``parent_study_id IS NOT NULL``, which guarantees their chain has
       length >= 2) AND have terminated (``completed_at IS NOT NULL`` AND
       ``status IN ('completed','cancelled','failed')``) AND, when
       ``since`` is supplied, completed since that cutoff. Ordered by
       ``completed_at DESC``. Scan-capped at ``limit * _CHAIN_MAX_DESCENDANTS``
       so dedup-to-anchor can still fill ``limit`` distinct chains in the
       worst case where every chain is fully maxed out (anchor + 5
       descendants).
    2. For each candidate (newest first), resolve its anchor via
       :func:`get_chain_for_study` and key into an ordered dict on
       ``anchor_id`` to deduplicate to one row per chain. Skip anchors
       already collected.
    3. Skip any chain whose
       :func:`backend.app.domain.study.chain_summary.derive_chain_stop_reason`
       returns ``"in_flight"`` — step 1 already excludes non-terminal
       tails, but a chain with a still-running *interior* link must also
       be excluded (mirrors the chain panel's terminal-only contract).
    4. Skip any chain whose ``len(links) < 2`` — defensive; the
       ``parent_study_id IS NOT NULL`` candidate filter already implies
       length >= 2, but a concurrent hard-delete of the anchor (no
       ``ondelete='SET NULL'`` on the self-FK, so this is rare) could
       leave a single-row traversal.
    5. Skip candidates whose :func:`get_chain_for_study` returns ``None``
       — the concurrent-delete race where a chain member is hard-deleted
       between the candidate query and the traversal (reachable via the
       ``hard_delete_study`` test teardown path). Mirrors the defensive
       skip already in ``get_chain_for_study`` at the hydration step.
    6. Stop once ``limit`` distinct chains are collected. Return the
       ``ChainTraversalResult`` list in tail-completion-DESC order
       (preserved by the candidate-order traversal — the *first*
       candidate hit for any chain is its newest terminal child, which
       is the chain's tail).
    """
    scan_cap = max(1, limit * _CHAIN_MAX_DESCENDANTS)
    candidate_stmt = (
        select(Study.id)
        .where(
            Study.parent_study_id.is_not(None),
            Study.completed_at.is_not(None),
            Study.status.in_(_TERMINAL_STUDY_STATUSES),
        )
        .order_by(Study.completed_at.desc(), Study.id.desc())
        .limit(scan_cap)
    )
    if since is not None:
        candidate_stmt = candidate_stmt.where(Study.completed_at >= since)
    candidate_ids: list[str] = list((await db.execute(candidate_stmt)).scalars().all())

    # Insertion-ordered dict — first hit per anchor wins, preserving
    # tail-completion-DESC order.
    by_anchor: dict[str, ChainTraversalResult] = {}
    for candidate_id in candidate_ids:
        if len(by_anchor) >= limit:
            break
        traversal = await get_chain_for_study(db, candidate_id)
        if traversal is None:
            # Concurrent hard-delete between candidate query and traversal
            # (e.g. test teardown). Skip silently per Story 1.1 task 5.
            continue
        if traversal.anchor_id in by_anchor:
            continue
        if len(traversal.links) < 2:
            # Defensive; the candidate filter implies length >= 2 unless
            # the anchor was concurrently deleted out of the chain.
            continue
        stop_reason = derive_chain_stop_reason(traversal.links, traversal.anchor_trials)
        if stop_reason == "in_flight":
            # Interior link still running — chain isn't done; exclude.
            continue
        by_anchor[traversal.anchor_id] = traversal

    return list(by_anchor.values())


# ---------------------------------------------------------------------------
# chore_e2e_test_rows_isolation Story 1.1 — hard-delete for test-only cleanup
# ---------------------------------------------------------------------------


async def hard_delete_study(db: AsyncSession, study_id: str) -> bool:
    """Hard-delete the study row for test-only cleanup.

    Trials cascade-delete via the existing ``ondelete='CASCADE'`` FK at
    ``backend/app/db/models/trial.py:60``.

    Returns ``True`` if a row was deleted, ``False`` if no row existed.
    Caller commits. Used ONLY by the test-only `DELETE /api/v1/_test/
    studies/{id}` endpoint per ``chore_e2e_test_rows_isolation`` FR-3.
    The handler is responsible for preflight EXISTS checks against
    ``proposals`` + ``digests`` (non-cascade) and emitting 409 if any
    dependents remain.
    """
    existing = await db.get(Study, study_id)
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True
