"""Judgment-list repository.

Phase 1 (feat_study_lifecycle) shipped ``create_judgment_list`` +
``get_judgment_list`` (the latter consumed by `infra_optuna_eval`'s
``run_trial`` to load the rubric / target / cluster context).

feat_llm_judgments Story 1.2 extends with the cursor-pagination + status /
calibration update functions required by FR-3 / FR-5 / FR-6 endpoints,
plus the ``list_generating_judgment_list_ids`` sweep used by the worker
``WorkerSettings.on_startup`` resume path (addresses GPT-5.5 cycle 1 F14
+ cycle 2 F1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import JudgmentList
from backend.app.db.repo._fts import fts_predicate


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


# ---------------------------------------------------------------------------
# feat_llm_judgments Story 1.2 extensions
# ---------------------------------------------------------------------------


async def list_judgment_lists(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
) -> list[JudgmentList]:
    """Cursor-paginated list of judgment lists, newest first by ``created_at``.

    Cursor shape ``(created_at, id)`` mirrors the studies pagination pattern in
    :func:`backend.app.db.repo.study.list_studies`. ``since`` filters by
    ``created_at >= since`` (Story 1.5 — closes api-conventions.md drift).
    ``q`` is an optional Postgres FTS match against ``search_vector``
    (judgment_lists.name + target). ``limit`` is clamped at the router layer
    (default 50, max 200 per api-conventions.md).
    """
    stmt = select(JudgmentList).order_by(JudgmentList.created_at.desc(), JudgmentList.id.desc())
    if since is not None:
        stmt = stmt.where(JudgmentList.created_at >= since)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    if cursor is not None:
        created_at, row_id = cursor
        stmt = stmt.where(
            (JudgmentList.created_at < created_at)
            | ((JudgmentList.created_at == created_at) & (JudgmentList.id < row_id))
        )
    stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def count_judgment_lists(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    q: str | None = None,
) -> int:
    """Total count for ``X-Total-Count`` header on ``GET /api/v1/judgment-lists``."""
    from sqlalchemy import func as _func

    stmt = select(_func.count()).select_from(JudgmentList)
    if since is not None:
        stmt = stmt.where(JudgmentList.created_at >= since)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    return int((await db.execute(stmt)).scalar_one())


async def update_judgment_list_status(
    db: AsyncSession,
    judgment_list_id: str,
    *,
    status: str,
    failed_reason: str | None = None,
) -> JudgmentList:
    """Flip a judgment list's terminal status. Caller commits.

    Used by the worker (``status='complete' | 'failed'`` per FR-2) and by
    the import endpoint (``status='complete'`` set at insert time, never
    via this helper). Raises ``LookupError`` if the row vanished between
    the worker's ``get_judgment_list`` and this call (operationally unlikely).
    """
    row = await get_judgment_list(db, judgment_list_id)
    if row is None:
        raise LookupError(f"judgment_list {judgment_list_id!r} not found")
    row.status = status
    if failed_reason is not None:
        row.failed_reason = failed_reason
    await db.flush()
    return row


async def update_judgment_list_calibration(
    db: AsyncSession,
    judgment_list_id: str,
    calibration: dict[str, Any],
) -> JudgmentList:
    """Persist calibration JSONB on a judgment list (FR-5). Caller commits.

    Overwrites prior calibration — re-running calibration replaces the
    advisory data rather than versioning it. Raises ``LookupError`` if the
    list vanished.
    """
    row = await get_judgment_list(db, judgment_list_id)
    if row is None:
        raise LookupError(f"judgment_list {judgment_list_id!r} not found")
    row.calibration = calibration
    await db.flush()
    return row


async def list_generating_judgment_list_ids(db: AsyncSession) -> list[str]:
    """``SELECT id FROM judgment_lists WHERE status = 'generating'``.

    Consumed by :func:`backend.workers.all.on_startup` to re-enqueue every
    in-flight judgment-generation job at worker boot — covers the case
    where the API's ``arq_pool.enqueue_job`` raised mid-call (durable row
    in Postgres, no boot signal to a running worker). Mirror of
    :func:`backend.app.db.repo.study.list_running_study_ids` and
    :func:`backend.app.db.repo.study.list_queued_study_ids`.

    Addresses GPT-5.5 cycle 1 F14 + cycle 2 F1.
    """
    stmt = select(JudgmentList.id).where(JudgmentList.status == "generating")
    return list((await db.execute(stmt)).scalars().all())
