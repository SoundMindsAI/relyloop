# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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


@dataclass(frozen=True)
class TrialCounts:
    """Per-study trial counts for the studies-list response.

    ``total`` mirrors :class:`TrialsSummary.total` (non-baseline rows —
    ``is_baseline.is_(False)``, matching :func:`aggregate_trials_summary`'s
    parity target) so the list's ``trial_count`` equals the detail's
    ``trials_summary.total`` exactly.

    ``complete`` mirrors :func:`list_complete_optuna_trials_for_study`'s
    own filter (``status == "complete" AND is_baseline.is_not(True)``), so
    the list's count-gate decision (``< 5`` / ``< 50`` / ``≥ 50``) keys
    off the same row set the classifier would see. Per D-17 in
    ``feat_studies_convergence_visibility/feature_spec.md`` —
    ``trials.is_baseline`` is ``BOOLEAN NOT NULL DEFAULT FALSE`` (model
    ``trial.py:114``; migration ``0020``) so ``is_(False)`` ≡
    ``is_not(True)`` today; pinning each predicate to its parity target
    keeps the contract unambiguous if the column ever becomes nullable.
    """

    total: int
    complete: int


async def count_trials_for_studies(
    db: AsyncSession, study_ids: Sequence[str]
) -> dict[str, TrialCounts]:
    """Batched non-baseline trial counts for a page of studies.

    One ``GROUP BY study_id`` aggregate returning ``(total, complete)``
    per study, both non-baseline. Powers the studies-list
    ``trial_count`` field + the convergence verdict's count gate
    (``feat_studies_convergence_visibility`` Story 1.1, FR-1/FR-3).

    Studies whose ID is in the input but have zero trials yet (e.g.,
    ``queued``) are returned with ``TrialCounts(0, 0)``. Empty input
    returns an empty dict (no query issued).
    """
    if not study_ids:
        return {}
    # Pin BOTH predicates to ``is_(False)`` — the only divergent case
    # would be a NULL ``is_baseline`` row, which cannot exist (NOT NULL
    # column). ``complete`` further filters by status. This keeps the
    # aggregate's row-set identical to the parity sources documented in
    # the TrialCounts docstring.
    stmt = (
        select(
            Trial.study_id.label("study_id"),
            func.count(Trial.id).filter(Trial.is_baseline.is_(False)).label("total"),
            func.count(Trial.id)
            .filter(Trial.is_baseline.is_(False), Trial.status == "complete")
            .label("complete"),
        )
        .where(Trial.study_id.in_(list(study_ids)))
        .group_by(Trial.study_id)
    )
    rows = (await db.execute(stmt)).all()
    result: dict[str, TrialCounts] = {
        row.study_id: TrialCounts(total=int(row.total), complete=int(row.complete)) for row in rows
    }
    # Backfill zero-trial studies so callers can index by id without
    # checking for KeyError.
    for sid in study_ids:
        result.setdefault(sid, TrialCounts(total=0, complete=0))
    return result


async def list_complete_optuna_trials_for_studies(
    db: AsyncSession, study_ids: Sequence[str]
) -> dict[str, list[Trial]]:
    """Batched sibling of :func:`list_complete_optuna_trials_for_study`.

    One ``SELECT ... WHERE study_id IN (...)`` with the same filter set
    (``status == "complete" AND is_baseline.is_not(True) AND
    primary_metric IS NOT NULL``), ordered by ``study_id`` then
    ``optuna_trial_number ASC``, grouped in Python.

    Called once per studies-list request — only for the subset of
    studies with ``complete >= STUDIES_TPE_WARMUP_FLOOR`` (50), which
    saves us from per-study trial loads in the common low-trial case
    (FR-3 / D-14).
    """
    if not study_ids:
        return {}
    stmt = (
        select(Trial)
        .where(Trial.study_id.in_(list(study_ids)))
        .where(Trial.status == "complete")
        .where(Trial.is_baseline.is_not(True))
        .where(Trial.primary_metric.is_not(None))
        .order_by(Trial.study_id, Trial.optuna_trial_number)
    )
    grouped: dict[str, list[Trial]] = {sid: [] for sid in study_ids}
    for trial in (await db.execute(stmt)).scalars().all():
        grouped[trial.study_id].append(trial)
    return grouped


async def list_complete_optuna_trials_for_study(db: AsyncSession, study_id: str) -> Sequence[Trial]:
    """List trials usable by the convergence classifier.

    Returns only complete, non-baseline Optuna trials whose
    ``primary_metric`` is set, ordered by ``optuna_trial_number ASC``.
    Pushes the same filter into SQL that
    :func:`backend.app.domain.study.convergence.classify_convergence`
    re-applies defensively at the domain layer.

    Baseline predicate is ``is_baseline IS NOT TRUE`` (matches FALSE
    *and* NULL) rather than ``IS FALSE`` so it mirrors the domain
    classifier's ``not getattr(trial, "is_baseline", False)`` semantics
    exactly — only an explicit ``TRUE`` is excluded. The column is
    ``NOT NULL DEFAULT FALSE`` in practice (no NULL rows exist), so this
    is behaviourally identical today; the change keeps the two layers
    genuinely consistent and future-proofs a hypothetical nullable
    column (GPT-5.5 PR #352 finding).

    Added for ``feat_study_convergence_indicator`` Story 2.1. Distinct
    from :func:`list_trials_for_study` (returns *every* row including
    failed/pruned/baseline) and :func:`list_trials_paginated` (cursor +
    sort variants for the trials API).
    """
    stmt = (
        select(Trial)
        .where(Trial.study_id == study_id)
        .where(Trial.status == "complete")
        .where(Trial.is_baseline.is_not(True))
        .where(Trial.primary_metric.is_not(None))
        .order_by(Trial.optuna_trial_number)
    )
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
        .where(Trial.is_baseline.is_(False))  # FR-11: exclude baseline from aggregates
        .cte("summary")
    )

    winner = (
        select(Trial.id)
        .where(Trial.study_id == study_id)
        .where(Trial.is_baseline.is_(False))  # FR-11
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
