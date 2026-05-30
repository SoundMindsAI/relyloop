# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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
from backend.app.db.repo._sort import (
    ParsedSort,
    keyset_predicate,
    order_by_clauses,
    parse_sort,
)

_JUDGMENT_LIST_SORT_COLUMNS: dict[str, object] = {
    "name": JudgmentList.name,
    "created_at": JudgmentList.created_at,
    "status": JudgmentList.status,
}


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
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
    sort: str | None = None,
    query_set_id: str | None = None,
    cluster_id: str | None = None,
    target: str | None = None,
) -> list[JudgmentList]:
    """Cursor-paginated list of judgment lists, sort-aware (Story 1.3).

    Default ordering ``created_at DESC, id DESC``. ``?sort=`` switches
    to ``<col>:<dir>`` with explicit NULLS handling. ``since`` filters
    by ``created_at >= since``. ``q`` is FTS match against
    ``search_vector`` (name + target). ``query_set_id`` / ``cluster_id``
    / ``target`` filter to judgment lists that belong to the supplied
    parent and/or share the exact target index name
    (``bug_judgment_lists_listing_ignores_query_set_filter`` for the
    first two; ``feat_study_target_judgment_mismatch_guard`` FR-2 for
    ``target``). The create-study modal's Step-2 dropdown relies on
    all three so it surfaces only the judgment lists valid for the
    chosen study cluster + query set + target — without these filters
    the modal lets the user pick a mismatched pair and ``POST
    /api/v1/studies`` then rejects at create time with a confusing 422.
    """
    parsed_sort: ParsedSort | None = parse_sort(sort, _JUDGMENT_LIST_SORT_COLUMNS)
    stmt = select(JudgmentList)
    if since is not None:
        stmt = stmt.where(JudgmentList.created_at >= since)
    if query_set_id is not None:
        stmt = stmt.where(JudgmentList.query_set_id == query_set_id)
    if cluster_id is not None:
        stmt = stmt.where(JudgmentList.cluster_id == cluster_id)
    if target is not None:
        stmt = stmt.where(JudgmentList.target == target)
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
                default_col=JudgmentList.created_at,
                id_col=JudgmentList.id,
            )
        )
    stmt = stmt.order_by(
        *order_by_clauses(
            parsed_sort,
            default_col=JudgmentList.created_at,
            id_col=JudgmentList.id,
        )
    ).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def count_judgment_lists(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    q: str | None = None,
    query_set_id: str | None = None,
    cluster_id: str | None = None,
    target: str | None = None,
) -> int:
    """Total count for ``X-Total-Count`` header on ``GET /api/v1/judgment-lists``.

    ``query_set_id`` / ``cluster_id`` / ``target`` mirror
    :func:`list_judgment_lists` so the header count and the row count stay
    consistent under the same filters.
    """
    from sqlalchemy import func as _func

    stmt = select(_func.count()).select_from(JudgmentList)
    if since is not None:
        stmt = stmt.where(JudgmentList.created_at >= since)
    if query_set_id is not None:
        stmt = stmt.where(JudgmentList.query_set_id == query_set_id)
    if cluster_id is not None:
        stmt = stmt.where(JudgmentList.cluster_id == cluster_id)
    if target is not None:
        stmt = stmt.where(JudgmentList.target == target)
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


# ---------------------------------------------------------------------------
# chore_e2e_test_rows_isolation Story 1.1 — hard-delete for test-only cleanup
# ---------------------------------------------------------------------------


async def hard_delete_judgment_list(db: AsyncSession, judgment_list_id: str) -> bool:
    """Hard-delete the judgment_list row for test-only cleanup.

    Judgments cascade-delete via the existing ``ondelete='CASCADE'`` FK
    at ``backend/app/db/models/judgment.py:61``.

    Returns ``True`` if a row was deleted, ``False`` if no row existed.
    Caller commits. Used ONLY by the test-only `DELETE /api/v1/_test/
    judgment-lists/{id}` endpoint per ``chore_e2e_test_rows_isolation`` FR-4.
    The handler is responsible for preflight EXISTS check against
    ``studies`` (non-cascade) and emitting 409 if a study still references
    the judgment_list.
    """
    existing = await db.get(JudgmentList, judgment_list_id)
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True
