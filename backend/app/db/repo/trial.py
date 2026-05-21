"""Trial repository (feat_study_lifecycle Phase 1 Story 1.3 + Phase 2 Story 1.4).

Phase 1 shipped create + list-for-study (Optuna-trial-number ordered).
Phase 2 extends with:

- :func:`list_trials_paginated` — cursor-paginated, sortable by 5 wire
  values per spec §7.4 (``primary_metric_desc | primary_metric_asc |
  ended_at_desc | ended_at_asc | optuna_trial_number_asc``).
- :func:`count_trials` — COUNT(*) for the X-Total-Count header (FR-6).
- :func:`aggregate_trials_summary` — single-query aggregation for
  ``GET /studies/{id}.trials_summary`` per FR-1.

The ``trials_study_metric`` index from Phase 1 covers the
``primary_metric_*`` sort variants. The other variants fall back to a
sequential scan (acceptable for MVP1 study sizes).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Trial

# Wire values for `?sort=` on `GET /api/v1/studies/{id}/trials`.
# Must match backend/app/api/v1/schemas.py TrialSortKey Literal.
TrialSortKey = Literal[
    "primary_metric_desc",
    "primary_metric_asc",
    "ended_at_desc",
    "ended_at_asc",
    "optuna_trial_number_asc",
]


@dataclass(frozen=True)
class TrialsSummary:
    """Aggregation result for ``GET /studies/{id}.trials_summary``."""

    total: int
    complete: int
    failed: int
    pruned: int
    best_primary_metric: float | None
    best_trial_id: str | None


async def create_trial(db: AsyncSession, **fields: object) -> Trial:
    """Stage a new ``Trial`` row. Caller commits.

    Hot path — ``infra_optuna_eval``'s ``run_trial`` Arq job calls this
    once per trial with the final status (``complete | failed | pruned``)
    and the populated metrics / primary_metric / params / duration_ms.
    """
    trial = Trial(**fields)
    db.add(trial)
    await db.flush()
    await db.refresh(trial)
    return trial


async def get_trial(db: AsyncSession, trial_id: str) -> Trial | None:
    """Fetch a single trial by primary key. Returns ``None`` if not found.

    Parallel to :func:`backend.app.db.repo.study.get_study`. Added in
    ``feat_agent_propose_search_space`` Story 2.1 so the
    ``propose_search_space`` agent tool can fetch a prior study's winning
    trial via ``Study.best_trial_id → repo.get_trial``.
    """
    stmt = select(Trial).where(Trial.id == trial_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_trials_for_study(db: AsyncSession, study_id: str) -> Sequence[Trial]:
    """List every trial in a study, ordered by Optuna trial number ASC.

    Phase 1 helper retained for ``run_trial``'s ``trials_summary`` -less
    contract path. Phase 2's API consumes :func:`list_trials_paginated`.
    """
    stmt = select(Trial).where(Trial.study_id == study_id).order_by(Trial.optuna_trial_number)
    return list((await db.execute(stmt)).scalars().all())


async def list_trials_paginated(
    db: AsyncSession,
    study_id: str,
    *,
    cursor: tuple[Any, str] | None = None,
    limit: int = 50,
    sort_key: TrialSortKey = "primary_metric_desc",
    since: datetime | None = None,
) -> Sequence[Trial]:
    """Cursor-paginated trials list, sortable by 5 wire values.

    Cursor shape depends on ``sort_key``:

    - ``primary_metric_*`` → ``(primary_metric: float | None, id: str)``
    - ``ended_at_*``       → ``(ended_at: datetime, id: str)``
    - ``optuna_trial_number_asc`` → ``(number: int, id: str)``

    The router encodes / decodes the cursor with the appropriate shape
    based on ``sort_key`` (Story 3.4 handler).

    ``since`` filters by ``trials.ended_at >= since`` when present; trials
    have no ``created_at`` column — ``ended_at`` is the only timestamp,
    and ``ended_at_*`` is what the api-conventions
    ``?since=`` filter actually wants for accumulator queries.
    """
    from sqlalchemy.sql.elements import UnaryExpression

    stmt = select(Trial).where(Trial.study_id == study_id)
    if since is not None:
        stmt = stmt.where(Trial.ended_at >= since)

    order: tuple[UnaryExpression[Any], UnaryExpression[Any]]
    if sort_key == "primary_metric_desc":
        # NULLS LAST matches the trials_study_metric index in migration 0003.
        # NULL-pagination correctness (E1-F3 cycle-1 fix): if the cursor's
        # primary_metric is non-null, the next page includes rows with a
        # smaller metric AND all NULL-metric rows (failed/pruned trials).
        # If the cursor is on a NULL row, only later NULL rows by id.
        order = (Trial.primary_metric.desc().nulls_last(), Trial.id.desc())
        if cursor is not None:
            cval, cid = cursor
            if cval is not None:
                stmt = stmt.where(
                    or_(
                        Trial.primary_metric < cval,
                        Trial.primary_metric.is_(None),
                        and_(Trial.primary_metric == cval, Trial.id < cid),
                    )
                )
            else:
                # Within the NULL-metric block, paginate by id only.
                stmt = stmt.where(and_(Trial.primary_metric.is_(None), Trial.id < cid))
    elif sort_key == "primary_metric_asc":
        order = (Trial.primary_metric.asc().nulls_last(), Trial.id.asc())
        if cursor is not None:
            cval, cid = cursor
            if cval is not None:
                stmt = stmt.where(
                    or_(
                        Trial.primary_metric > cval,
                        Trial.primary_metric.is_(None),
                        and_(Trial.primary_metric == cval, Trial.id > cid),
                    )
                )
            else:
                stmt = stmt.where(and_(Trial.primary_metric.is_(None), Trial.id > cid))
    elif sort_key == "ended_at_desc":
        # Sort by ended_at (when the trial finished). Renamed from
        # created_at_* to match the actual underlying column per
        # chore_spec_trial_created_at_drift (no created_at column exists).
        order = (Trial.ended_at.desc().nulls_last(), Trial.id.desc())
        if cursor is not None:
            cval, cid = cursor
            stmt = stmt.where(
                or_(
                    Trial.ended_at < cval if cval is not None else False,
                    and_(Trial.ended_at == cval, Trial.id < cid),
                )
            )
    elif sort_key == "ended_at_asc":
        order = (Trial.ended_at.asc().nulls_last(), Trial.id.asc())
        if cursor is not None:
            cval, cid = cursor
            stmt = stmt.where(
                or_(
                    Trial.ended_at > cval if cval is not None else False,
                    and_(Trial.ended_at == cval, Trial.id > cid),
                )
            )
    else:  # optuna_trial_number_asc
        order = (Trial.optuna_trial_number.asc(), Trial.id.asc())
        if cursor is not None:
            cval, cid = cursor
            stmt = stmt.where(
                or_(
                    Trial.optuna_trial_number > cval,
                    and_(Trial.optuna_trial_number == cval, Trial.id > cid),
                )
            )

    stmt = stmt.order_by(*order).limit(min(limit, 200))
    return list((await db.execute(stmt)).scalars().all())


async def count_trials(
    db: AsyncSession,
    study_id: str,
    *,
    since: datetime | None = None,
) -> int:
    """COUNT(*) trials in a study (X-Total-Count header on Story 3.4)."""
    stmt = select(func.count(Trial.id)).where(Trial.study_id == study_id)
    if since is not None:
        stmt = stmt.where(Trial.ended_at >= since)
    return int((await db.execute(stmt)).scalar_one())


async def aggregate_trials_summary(db: AsyncSession, study_id: str) -> TrialsSummary:
    """Single-query aggregation for ``GET /studies/{id}.trials_summary``.

    Returns counts grouped by status + the best (max) primary_metric +
    the trial id achieving it. A CTE-style single SELECT (per spec §13
    contract for ``aggregate_trials_summary``): the summary aggregates
    join a correlated scalar subquery that picks the winner id using
    ``MAX(primary_metric) FILTER (...) `` from the outer aggregation.
    Wall-clock target <100ms p99.

    Replaces the previous 2-query implementation (chore_trial_summary_single_query).
    """
    summary = (
        select(
            func.count(Trial.id).label("total"),
            func.count(Trial.id).filter(Trial.status == "complete").label("complete"),
            func.count(Trial.id).filter(Trial.status == "failed").label("failed"),
            func.count(Trial.id).filter(Trial.status == "pruned").label("pruned"),
            func.max(Trial.primary_metric).filter(Trial.status == "complete").label("best"),
        )
        .where(Trial.study_id == study_id)
        .cte("summary")
    )

    winner = (
        select(Trial.id)
        .where(Trial.study_id == study_id)
        .where(Trial.status == "complete")
        .where(Trial.primary_metric == summary.c.best)
        .order_by(Trial.optuna_trial_number)  # deterministic tiebreak
        .limit(1)
        .correlate(summary)
        .scalar_subquery()
    )

    stmt = select(
        summary.c.total,
        summary.c.complete,
        summary.c.failed,
        summary.c.pruned,
        summary.c.best,
        winner.label("best_trial_id"),
    )
    row = (await db.execute(stmt)).one()
    best = row.best
    return TrialsSummary(
        total=int(row.total),
        complete=int(row.complete),
        failed=int(row.failed),
        pruned=int(row.pruned),
        best_primary_metric=float(best) if best is not None else None,
        best_trial_id=row.best_trial_id,
    )
