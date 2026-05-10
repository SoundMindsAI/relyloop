"""Trial repository (feat_study_lifecycle Phase 1 Story 1.3 + Phase 2 Story 1.4).

Phase 1 shipped create + list-for-study (Optuna-trial-number ordered).
Phase 2 extends with:

- :func:`list_trials_paginated` — cursor-paginated, sortable by 5 wire
  values per spec §7.4 (``primary_metric_desc | primary_metric_asc |
  created_at_desc | created_at_asc | optuna_trial_number_asc``).
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

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Trial

# Wire values for `?sort=` on `GET /api/v1/studies/{id}/trials`.
# Must match backend/app/api/v1/schemas.py TrialSortKey Literal.
TrialSortKey = Literal[
    "primary_metric_desc",
    "primary_metric_asc",
    "created_at_desc",
    "created_at_asc",
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
    - ``created_at_*``     → ``(created_at: datetime, id: str)``
    - ``optuna_trial_number_asc`` → ``(number: int, id: str)``

    The router encodes / decodes the cursor with the appropriate shape
    based on ``sort_key`` (Story 3.4 handler).

    ``since`` filters by ``trials.ended_at >= since`` when present; trials
    have no separate ``created_at`` column — ``ended_at`` is the closest
    "when did this trial finish" timestamp and is what the api-conventions
    ``?since=`` filter actually wants for accumulator queries.
    """
    from sqlalchemy.sql.elements import UnaryExpression

    stmt = select(Trial).where(Trial.study_id == study_id)
    if since is not None:
        stmt = stmt.where(Trial.ended_at >= since)

    order: tuple[UnaryExpression[Any], UnaryExpression[Any]]
    if sort_key == "primary_metric_desc":
        # NULLS LAST matches the trials_study_metric index in migration 0003.
        order = (Trial.primary_metric.desc().nulls_last(), Trial.id.desc())
        if cursor is not None:
            cval, cid = cursor
            stmt = stmt.where(
                or_(
                    Trial.primary_metric < cval
                    if cval is not None
                    else Trial.primary_metric.is_(None),
                    and_(Trial.primary_metric == cval, Trial.id < cid),
                )
            )
    elif sort_key == "primary_metric_asc":
        order = (Trial.primary_metric.asc().nulls_last(), Trial.id.asc())
        if cursor is not None:
            cval, cid = cursor
            stmt = stmt.where(
                or_(
                    Trial.primary_metric > cval if cval is not None else False,
                    and_(Trial.primary_metric == cval, Trial.id > cid),
                )
            )
    elif sort_key == "created_at_desc":
        # Trials don't have created_at; use ended_at as proxy for "when did
        # the trial finish" (the user-meaningful timestamp).
        order = (Trial.ended_at.desc().nulls_last(), Trial.id.desc())
        if cursor is not None:
            cval, cid = cursor
            stmt = stmt.where(
                or_(
                    Trial.ended_at < cval if cval is not None else False,
                    and_(Trial.ended_at == cval, Trial.id < cid),
                )
            )
    elif sort_key == "created_at_asc":
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
    the trial id achieving it. One SELECT with FILTER clauses + a
    correlated subquery for the winner id. Wall-clock target <100ms p99
    per spec §13.
    """
    counts_stmt = select(
        func.count(Trial.id).label("total"),
        func.count(case((Trial.status == "complete", 1))).label("complete"),
        func.count(case((Trial.status == "failed", 1))).label("failed"),
        func.count(case((Trial.status == "pruned", 1))).label("pruned"),
        func.max(case((Trial.status == "complete", Trial.primary_metric))).label("best"),
    ).where(Trial.study_id == study_id)
    counts_row = (await db.execute(counts_stmt)).one()
    best = counts_row.best
    best_trial_id: str | None = None
    if best is not None:
        winner_stmt = (
            select(Trial.id)
            .where(Trial.study_id == study_id)
            .where(Trial.status == "complete")
            .where(Trial.primary_metric == best)
            .order_by(Trial.optuna_trial_number)  # deterministic tiebreak
            .limit(1)
        )
        best_trial_id = (await db.execute(winner_stmt)).scalar_one_or_none()
    return TrialsSummary(
        total=int(counts_row.total),
        complete=int(counts_row.complete),
        failed=int(counts_row.failed),
        pruned=int(counts_row.pruned),
        best_primary_metric=float(best) if best is not None else None,
        best_trial_id=best_trial_id,
    )
