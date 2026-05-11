"""Judgment repository (feat_llm_judgments Story 1.2).

Backs every read/write the API + worker performs against the ``judgments``
child table created by the ``0004_judgments`` migration. All functions
take ``db: AsyncSession`` first; the caller commits.

Three notable design decisions:

* **Bulk insert is idempotent.** :func:`bulk_create_judgments` uses
  ``INSERT ... ON CONFLICT DO NOTHING`` keyed on the UNIQUE constraint so
  a worker resume can safely re-emit the same rows. The per-query
  resume-skip in :mod:`backend.workers.judgments` is the primary
  mechanism to avoid re-spending OpenAI dollars (per GPT-5.5 cycle 2 F5);
  this is the secondary safety net at the DB layer.
* **Human override is UPSERT-replace.** :func:`upsert_judgment_human_override`
  uses ``ON CONFLICT ... DO UPDATE`` so the existing LLM row is mutated
  in place — the row keeps its ``id`` but flips ``source='human'``,
  ``rater_ref='operator'``, fresh ``rating``/``notes``, ``confidence=NULL``,
  and ``created_at=now()`` (spec FR-4 / AC-2).
* **Source breakdown folds ``click`` into ``human``.** Per spec FR-6 the
  response shape names only ``llm`` and ``human``; the invariant
  ``llm + human == judgment_count`` is held by deterministically folding
  reserved ``click`` rows into ``human`` (no ``click`` rows exist in MVP1
  but the contract is locked now per GPT-5.5 cycle 2 F6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Judgment


async def create_judgment(db: AsyncSession, **fields: object) -> Judgment:
    """Stage a single new ``Judgment`` row. Caller commits.

    Used by tests and the (rare) single-row insert path. The worker prefers
    :func:`bulk_create_judgments`; the override endpoint prefers
    :func:`upsert_judgment_human_override`.
    """
    judgment = Judgment(**fields)
    db.add(judgment)
    await db.flush()
    await db.refresh(judgment)
    return judgment


async def bulk_create_judgments(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Bulk-insert judgments with ``ON CONFLICT DO NOTHING``. Caller commits.

    ``rows`` is a list of dicts whose keys match the ``judgments`` columns
    (``id``, ``judgment_list_id``, ``query_id``, ``doc_id``, ``rating``,
    ``source``, ``rater_ref``, ``notes``; ``created_at`` is server-default).
    The UNIQUE ``(judgment_list_id, query_id, doc_id)`` collision causes
    the conflicting row to be skipped — this makes worker retry / resume
    safe at the DB layer (the primary defense is the per-query resume-skip
    check in :mod:`backend.workers.judgments` — addresses GPT-5.5 cycle 2 F5).

    Returns the number of rows that actually inserted (i.e., excluding
    conflicts).
    """
    if not rows:
        return 0
    stmt = (
        pg_insert(Judgment)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["judgment_list_id", "query_id", "doc_id"],
        )
    )
    result = await db.execute(stmt)
    await db.flush()
    # rowcount reflects rows actually inserted (excluding conflicts) on Postgres.
    # mypy: SQLAlchemy's Result[Any] doesn't surface rowcount on its public type,
    # but the CursorResult subclass returned by INSERT statements does — use
    # getattr to keep mypy happy without an explicit cast.
    return int(getattr(result, "rowcount", 0) or 0)


async def upsert_judgment_human_override(
    db: AsyncSession,
    *,
    judgment_list_id: str,
    query_id: str,
    doc_id: str,
    rating: int,
    rater_ref: str = "operator",
    notes: str | None = None,
) -> Judgment:
    """Replace any existing rating with a human override. Caller commits.

    Per spec FR-4 / AC-2 the LLM row at ``(judgment_list_id, query_id, doc_id)``
    is REPLACED in place (not appended):
    the row keeps its ``id`` but the columns flip to ``source='human'``,
    ``rater_ref`` (default ``'operator'``), the supplied ``rating`` and
    ``notes``, ``confidence=NULL`` (LLM confidence is not meaningful for
    a human rating), and ``created_at=now()`` (override timestamp).
    """
    # Pre-generate an id for the INSERT half of the UPSERT — the existing
    # row will keep its own id via DO UPDATE.
    from uuid import uuid4

    new_id = str(uuid4())
    now = datetime.now(UTC)

    insert_stmt = pg_insert(Judgment).values(
        id=new_id,
        judgment_list_id=judgment_list_id,
        query_id=query_id,
        doc_id=doc_id,
        rating=rating,
        source="human",
        rater_ref=rater_ref,
        confidence=None,
        notes=notes,
        created_at=now,
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["judgment_list_id", "query_id", "doc_id"],
        set_={
            "rating": insert_stmt.excluded.rating,
            "source": insert_stmt.excluded.source,
            "rater_ref": insert_stmt.excluded.rater_ref,
            "confidence": insert_stmt.excluded.confidence,
            "notes": insert_stmt.excluded.notes,
            "created_at": insert_stmt.excluded.created_at,
        },
    ).returning(Judgment)

    row = (await db.execute(upsert_stmt)).scalar_one()
    await db.flush()
    return row


async def get_judgment(db: AsyncSession, judgment_id: str) -> Judgment | None:
    """Fetch a single judgment by id (used by the PATCH override path)."""
    stmt = select(Judgment).where(Judgment.id == judgment_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_judgments_paginated(
    db: AsyncSession,
    judgment_list_id: str,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
    source: str | None = None,
) -> list[Judgment]:
    """Cursor-paginated list of judgments for one judgment list (FR-6).

    Cursor shape ``(created_at, id)`` mirrors :func:`list_judgment_lists`.
    ``source`` filter is one of ``"llm"`` / ``"human"`` (rejected at the
    router layer for ``"click"``; see :data:`JudgmentSourceFilterWire`).
    """
    stmt = select(Judgment).where(Judgment.judgment_list_id == judgment_list_id)
    if source is not None:
        stmt = stmt.where(Judgment.source == source)
    stmt = stmt.order_by(Judgment.created_at.desc(), Judgment.id.desc())
    if cursor is not None:
        created_at, row_id = cursor
        stmt = stmt.where(
            (Judgment.created_at < created_at)
            | ((Judgment.created_at == created_at) & (Judgment.id < row_id))
        )
    stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def count_judgments_for_list(
    db: AsyncSession,
    judgment_list_id: str,
    *,
    source: str | None = None,
) -> int:
    """Total judgment count for ``X-Total-Count`` + ``JudgmentListDetail.judgment_count``."""
    stmt = (
        select(func.count())
        .select_from(Judgment)
        .where(Judgment.judgment_list_id == judgment_list_id)
    )
    if source is not None:
        stmt = stmt.where(Judgment.source == source)
    return int((await db.execute(stmt)).scalar_one())


async def count_judgments_for_list_and_query(
    db: AsyncSession,
    judgment_list_id: str,
    query_id: str,
) -> int:
    """Per-query count of existing judgments (worker resume-skip helper).

    Addresses GPT-5.5 cycle 2 F5: if this count is ``>= top_k`` (=50 in
    MVP1), the worker skips the LLM call for that query entirely so a
    resumed worker doesn't re-spend OpenAI dollars on already-judged rows.
    """
    stmt = (
        select(func.count())
        .select_from(Judgment)
        .where(Judgment.judgment_list_id == judgment_list_id)
        .where(Judgment.query_id == query_id)
    )
    return int((await db.execute(stmt)).scalar_one())


async def source_breakdown_for_list(
    db: AsyncSession,
    judgment_list_id: str,
) -> dict[str, int]:
    """``{'llm': N, 'human': M}`` — used by ``JudgmentListDetail.source_breakdown``.

    Per spec FR-6 the response shape names only ``llm`` and ``human``. Per
    GPT-5.5 cycle 2 F6 the invariant ``llm + human == judgment_count`` is
    held by deterministically folding reserved ``click`` rows into the
    ``human`` bucket. No ``click`` rows exist in MVP1; the contract is
    fixed forward-compat.
    """
    stmt = (
        select(Judgment.source, func.count())
        .where(Judgment.judgment_list_id == judgment_list_id)
        .group_by(Judgment.source)
    )
    rows = (await db.execute(stmt)).all()
    out: dict[str, int] = {"llm": 0, "human": 0}
    for source, count in rows:
        if source == "llm":
            out["llm"] += int(count)
        else:
            # 'human' AND 'click' both fold into 'human' per the cycle 2 F6 contract.
            out["human"] += int(count)
    return out
