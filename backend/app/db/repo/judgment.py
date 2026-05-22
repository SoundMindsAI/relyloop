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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Judgment, JudgmentList
from backend.app.db.repo._sort import (
    ParsedSort,
    keyset_predicate,
    order_by_clauses,
    parse_sort,
)

# Allowlist for ``?sort=<col>:<dir>`` on
# ``/api/v1/judgment-lists/{id}/judgments``. Keys mirror ``JudgmentRowSortKey``.
_JUDGMENT_ROW_SORT_COLUMNS: dict[str, object] = {
    "created_at": Judgment.created_at,
    "rating": Judgment.rating,
    "source": Judgment.source,
}


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
    upsert_stmt = (
        insert_stmt.on_conflict_do_update(
            index_elements=["judgment_list_id", "query_id", "doc_id"],
            set_={
                "rating": insert_stmt.excluded.rating,
                "source": insert_stmt.excluded.source,
                "rater_ref": insert_stmt.excluded.rater_ref,
                "confidence": insert_stmt.excluded.confidence,
                "notes": insert_stmt.excluded.notes,
                "created_at": insert_stmt.excluded.created_at,
            },
        )
        .returning(Judgment)
        # ``populate_existing=True`` forces SQLAlchemy to overwrite any
        # existing identity-map entry with the columns returned by RETURNING.
        # Without it the caller would see the cached (pre-update) values
        # when the DO UPDATE branch fires on an already-loaded row — bug
        # surfaced in CI on the override-replace tests.
        .execution_options(populate_existing=True)
    )

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
    cursor: tuple[object, str] | None = None,
    limit: int = 50,
    source: str | None = None,
    sort: str | None = None,
) -> list[Judgment]:
    """Cursor-paginated list of judgments for one judgment list.

    Sort-aware (feat_data_table_primitive Story 1.3). Default ordering
    ``created_at DESC, id DESC``. ``?sort=<col>:<dir>`` where ``<col>`` is
    one of ``created_at | rating | source`` switches to that column with
    NULLS handling + ``id DESC`` tie-breaker.

    ``source`` filter is one of ``"llm"`` / ``"human"`` (rejected at the
    router layer for ``"click"``; see :data:`JudgmentSourceFilterWire`).
    """
    parsed_sort: ParsedSort | None = parse_sort(sort, _JUDGMENT_ROW_SORT_COLUMNS)
    stmt = select(Judgment).where(Judgment.judgment_list_id == judgment_list_id)
    if source is not None:
        stmt = stmt.where(Judgment.source == source)
    if cursor is not None:
        cursor_value, cursor_id = cursor
        stmt = stmt.where(
            keyset_predicate(
                parsed_sort,
                cursor_value,
                cursor_id,
                default_col=Judgment.created_at,
                id_col=Judgment.id,
            )
        )
    stmt = stmt.order_by(
        *order_by_clauses(parsed_sort, default_col=Judgment.created_at, id_col=Judgment.id)
    ).limit(limit)
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


async def list_doc_ids_for_list_and_query(
    db: AsyncSession,
    judgment_list_id: str,
    query_id: str,
    *,
    limit: int,
) -> list[str]:
    """Return up to ``limit`` judged ``doc_id`` values for ``(judgment_list_id, query_id)``.

    Result is ordered ``doc_id ASC`` for deterministic, replayable probes.

    Required keyword ``limit`` — there is no default. Callers must pass an explicit
    cap (the preflight overlap probe passes ``limit=MAX_PROBED_DOCS=200`` from
    ``feat_study_preflight_overlap_probe``). Deterministic ordering keeps the
    probe replayable.

    The ``UniqueConstraint("judgment_list_id", "query_id", "doc_id")`` at
    ``judgments_unique_key`` guarantees rows are already distinct per
    ``(list, qid)``; no ``DISTINCT`` keyword needed.
    """
    stmt = (
        select(Judgment.doc_id)
        .where(Judgment.judgment_list_id == judgment_list_id)
        .where(Judgment.query_id == query_id)
        .order_by(Judgment.doc_id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


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


# ---------------------------------------------------------------------------
# feat_query_inline_crud Story 1.3 — batch per-query judgment-count helper
# ---------------------------------------------------------------------------


async def count_judgments_per_query(
    db: AsyncSession,
    query_ids: Sequence[str],
) -> dict[str, int]:
    """Return ``{query_id: count}`` for every id in ``query_ids``.

    Single ``GROUP BY query_id`` over the paginated page (typically 50
    rows max), backed by ``judgments_list_query_idx``. Missing keys
    (queries with zero judgments) are post-filled to ``0`` here so the
    router never has to.

    Empty input → ``{}`` short-circuit.
    """
    if not query_ids:
        return {}
    stmt = (
        select(Judgment.query_id, func.count())
        .where(Judgment.query_id.in_(list(query_ids)))
        .group_by(Judgment.query_id)
    )
    rows = (await db.execute(stmt)).all()
    counts: dict[str, int] = {qid: int(c) for qid, c in rows}
    # Post-fill zero counts so callers always get every requested id.
    for qid in query_ids:
        counts.setdefault(qid, 0)
    return counts


# ---------------------------------------------------------------------------
# feat_query_inline_crud Story 3.2 — FK-guard sample helper for 409 envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgmentListRefRow:
    """Repo-layer row shape for the FK-guard sample.

    Distinct from the API-layer ``JudgmentListRef`` Pydantic model so the
    repo doesn't depend on ``backend/app/api/``. Mapped to the wire model
    at the router boundary.
    """

    id: str
    name: str


@dataclass(frozen=True)
class JudgmentRefCounts:
    """Return shape of :func:`count_and_sample_judgment_refs`.

    Constructs the 409 ``QUERY_HAS_JUDGMENTS`` envelope: ``judgment_count``
    + ``list_count`` feed ``detail.message``; ``sample_lists`` feeds
    ``detail.judgment_lists`` (alphabetised by name, capped at the
    requested ``sample_limit``); ``overflow_count`` is
    ``max(0, list_count - sample_limit)``.
    """

    judgment_count: int
    list_count: int
    sample_lists: list[JudgmentListRefRow] = field(default_factory=list)
    overflow_count: int = 0


async def count_and_sample_judgment_refs(
    db: AsyncSession,
    query_id: str,
    *,
    sample_limit: int = 10,
) -> JudgmentRefCounts:
    """Aggregate + sample the judgment lists referencing ``query_id``.

    Two SQL statements (helper is called only on the 409 cold path after
    an ``IntegrityError`` rollback, so the two-query cost is paid only
    when the operator actually hit a 409):

    1. **Aggregate** — ``COUNT(*)`` + ``COUNT(DISTINCT judgment_list_id)``
       to populate ``judgment_count`` and ``list_count``.
    2. **Sample** — alphabetised ``DISTINCT judgment_list_id, name`` join
       limited to ``sample_limit``. Feeds ``sample_lists``.

    ``overflow_count = max(0, list_count - sample_limit)``.
    """
    # Aggregate.
    agg_stmt = select(
        func.count().label("judgment_count"),
        func.count(Judgment.judgment_list_id.distinct()).label("list_count"),
    ).where(Judgment.query_id == query_id)
    agg = (await db.execute(agg_stmt)).one()
    judgment_count = int(agg.judgment_count)
    list_count = int(agg.list_count)

    if list_count == 0:
        return JudgmentRefCounts(
            judgment_count=judgment_count,
            list_count=0,
            sample_lists=[],
            overflow_count=0,
        )

    # Sample — alphabetised, capped.
    sample_stmt = (
        select(JudgmentList.id, JudgmentList.name)
        .join(Judgment, Judgment.judgment_list_id == JudgmentList.id)
        .where(Judgment.query_id == query_id)
        .group_by(JudgmentList.id, JudgmentList.name)
        .order_by(JudgmentList.name.asc())
        .limit(sample_limit)
    )
    sample_rows = (await db.execute(sample_stmt)).all()
    sample_lists = [JudgmentListRefRow(id=str(r.id), name=str(r.name)) for r in sample_rows]
    overflow_count = max(0, list_count - sample_limit)

    return JudgmentRefCounts(
        judgment_count=judgment_count,
        list_count=list_count,
        sample_lists=sample_lists,
        overflow_count=overflow_count,
    )
