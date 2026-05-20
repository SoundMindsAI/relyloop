"""Judgment endpoints (feat_llm_judgments Epic 3, Stories 3.1 – 3.5).

Seven endpoints under ``/api/v1``:

* ``POST /judgments/generate`` — Story 3.1; preflight (config / capability /
  pricing / budget peek / FK / oversized query set) + INSERT + best-effort
  Arq enqueue.
* ``POST /judgment-lists/import`` — Story 3.2; tutorial no-OpenAI path.
* ``GET /judgment-lists`` — Story 3.3; cursor-paginated list.
* ``GET /judgment-lists/{id}`` — Story 3.3; detail with judgment_count +
  source_breakdown + calibration.
* ``GET /judgment-lists/{id}/judgments`` — Story 3.3; paginated rows with
  optional ``?source=`` filter.
* ``PATCH /judgment-lists/{id}/judgments/{judgment_id}`` — Story 3.4;
  human override (UPSERT-replace via the UNIQUE constraint).
* ``POST /judgment-lists/{id}/calibration`` — Story 3.5; Cohen's + weighted
  kappa from human samples.

The handlers share three private helpers (``_err``, ``_encode_cursor``,
``_decode_cursor``) copied from :mod:`backend.app.api.v1.studies` — see
the lean-refactor §5.2 note in the implementation plan: the hoist to
``_cursor.py`` / ``_errors.py`` is deferred to ``chore_router_helpers_hoist``
since blocking this PR on the refactor doesn't pay off the time.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.schemas import (
    CalibrationResponse,
    CalibrationSamplesRequest,
    CreateJudgmentListGenerateRequest,
    GenerateJudgmentsResponse,
    ImportJudgmentListRequest,
    JudgmentListDetail,
    JudgmentListJudgmentsResponse,
    JudgmentListListResponse,
    JudgmentListSortKey,
    JudgmentListStatusWire,
    JudgmentListSummary,
    JudgmentRow,
    JudgmentRowSortKey,
    JudgmentSourceFilterWire,
    OverrideJudgmentRequest,
    _SourceBreakdown,
)
from backend.app.core.logging import get_logger
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.models import Judgment, JudgmentList
from backend.app.db.repo._sort import (
    cursor_value_is_datetime,
    parse_sort,
)
from backend.app.db.repo._sort import (
    decode_cursor as _sort_decode_cursor,
)
from backend.app.db.repo._sort import (
    encode_cursor as _sort_encode_cursor,
)
from backend.app.db.repo.judgment_list import _JUDGMENT_LIST_SORT_COLUMNS
from backend.app.db.session import get_db
from backend.app.eval.calibration import compute_calibration
from backend.app.services.agent_judgments_dispatch import (
    JudgmentGenerationRequest,
    start_judgment_generation,
)

router = APIRouter()
logger = get_logger(__name__)

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


def _encode_cursor(created_at: datetime, row_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([created_at.isoformat(), row_id]).encode()).decode()


def _decode_cursor(raw: str) -> tuple[datetime, str]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        created_at = datetime.fromisoformat(decoded[0])
        row_id = str(decoded[1])
    except Exception as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    return created_at, row_id


async def _open_redis() -> Redis:
    """Per-request Redis client. Kept tiny so the lifespan stays simple."""
    client: Redis = Redis.from_url(get_settings().redis_url, decode_responses=False)
    return client


def _summary(row: JudgmentList) -> JudgmentListSummary:
    return JudgmentListSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        query_set_id=row.query_set_id,
        cluster_id=row.cluster_id,
        status=row.status,  # str narrowed via CHECK constraint
        created_at=row.created_at,
    )


async def _detail(db: AsyncSession, row: JudgmentList) -> JudgmentListDetail:
    judgment_count = await repo.count_judgments_for_list(db, row.id)
    breakdown = await repo.source_breakdown_for_list(db, row.id)
    return JudgmentListDetail(
        id=row.id,
        name=row.name,
        description=row.description,
        query_set_id=row.query_set_id,
        cluster_id=row.cluster_id,
        target=row.target,
        current_template_id=row.current_template_id,
        rubric=row.rubric,
        status=row.status,
        failed_reason=row.failed_reason,
        judgment_count=judgment_count,
        source_breakdown=_SourceBreakdown(
            llm=breakdown.get("llm", 0),
            human=breakdown.get("human", 0),
        ),
        calibration=row.calibration,
        created_at=row.created_at,
    )


def _judgment_row(row: Judgment) -> JudgmentRow:
    return JudgmentRow(
        id=row.id,
        judgment_list_id=row.judgment_list_id,
        query_id=row.query_id,
        doc_id=row.doc_id,
        rating=row.rating,
        source=row.source,
        rater_ref=row.rater_ref,
        confidence=row.confidence,
        notes=row.notes,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/judgments/generate  (Story 3.1, FR-3 + AC-5 + AC-7)
# ---------------------------------------------------------------------------


@router.post(
    "/judgments/generate",
    response_model=GenerateJudgmentsResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["judgments"],
)
async def generate_judgments(
    body: CreateJudgmentListGenerateRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GenerateJudgmentsResponse:
    """Create a judgment_lists row + enqueue the worker.

    Delegates the full preflight + INSERT + Arq enqueue to
    :func:`backend.app.services.agent_judgments_dispatch.start_judgment_generation`
    so the chat-agent ``generate_judgments_llm`` tool reuses the exact same
    checks (no duplicated preflight). Wire behavior is identical — same error
    codes, same status codes, same response shape.
    """
    settings = get_settings()
    arq_pool = getattr(request.app.state, "arq_pool", None)
    redis_client: Redis | None = None

    try:
        redis_client = await _open_redis()
        result = await start_judgment_generation(
            db=db,
            redis=redis_client,
            arq_pool=arq_pool,
            settings=settings,
            req=JudgmentGenerationRequest(
                name=body.name,
                description=body.description,
                query_set_id=body.query_set_id,
                cluster_id=body.cluster_id,
                target=body.target,
                current_template_id=body.current_template_id,
                rubric=body.rubric,
            ),
        )
        return GenerateJudgmentsResponse(
            judgment_list_id=result.judgment_list_id,
            status=result.status,
        )
    finally:
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.debug("redis close raised in generate_judgments handler", error=str(exc))


# ---------------------------------------------------------------------------
# POST /api/v1/judgment-lists/import  (Story 3.2, FR-3b — tutorial path)
# ---------------------------------------------------------------------------


@router.post(
    "/judgment-lists/import",
    response_model=JudgmentListDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["judgments"],
)
async def import_judgment_list(
    body: ImportJudgmentListRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JudgmentListDetail:
    """Create a judgment_lists row with status='complete' + bulk-insert judgments.

    Tutorial path; no OpenAI involvement. Every supplied judgment must
    reference a ``query_id`` that exists in ``body.query_set_id`` —
    mismatches → 400 ``QUERY_NOT_IN_SET``.
    """
    cluster = await repo.get_cluster(db, body.cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {body.cluster_id} not found", False)
    query_set = await repo.get_query_set(db, body.query_set_id)
    if query_set is None:
        raise _err(404, "QUERY_SET_NOT_FOUND", f"query set {body.query_set_id} not found", False)
    # Consistency: query_set must belong to the supplied cluster (cycle-9 C9-F1).
    if query_set.cluster_id != body.cluster_id:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"query_set {body.query_set_id} belongs to cluster "
            f"{query_set.cluster_id!r}, not {body.cluster_id!r}",
            False,
        )

    queries = await repo.list_queries_for_set(db, body.query_set_id)
    valid_query_ids = {q.id for q in queries}
    seen_pairs: set[tuple[str, str]] = set()
    for item in body.judgments:
        if item.query_id not in valid_query_ids:
            raise _err(
                400,
                "QUERY_NOT_IN_SET",
                f"query_id {item.query_id!r} not in query_set {body.query_set_id!r}",
                False,
            )
        # Reject duplicate (query_id, doc_id) pairs in the payload — without
        # this pre-check, bulk_create_judgments would silently drop them via
        # ON CONFLICT DO NOTHING and the 201 response would lie about the
        # imported count (per GPT-5.5 final review F3).
        pair = (item.query_id, item.doc_id)
        if pair in seen_pairs:
            raise _err(
                400,
                "VALIDATION_ERROR",
                f"duplicate (query_id, doc_id) pair in import payload: "
                f"({item.query_id!r}, {item.doc_id!r})",
                False,
            )
        seen_pairs.add(pair)

    judgment_list_id = str(uuid.uuid4())
    try:
        await repo.create_judgment_list(
            db,
            id=judgment_list_id,
            name=body.name,
            description=body.description,
            query_set_id=body.query_set_id,
            cluster_id=body.cluster_id,
            target=body.target,
            current_template_id=None,
            rubric=body.rubric,
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        rows = [
            {
                "id": str(uuid.uuid4()),
                "judgment_list_id": judgment_list_id,
                "query_id": item.query_id,
                "doc_id": item.doc_id,
                "rating": item.rating,
                "source": "human",
                "rater_ref": "import",
                "notes": item.notes,
            }
            for item in body.judgments
        ]
        await repo.bulk_create_judgments(db, rows)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _err(
            409,
            "JUDGMENT_LIST_NAME_TAKEN",
            f"judgment list name {body.name!r} already exists",
            False,
        ) from exc

    row = await repo.get_judgment_list(db, judgment_list_id)
    assert row is not None  # just inserted  # noqa: S101
    return await _detail(db, row)


# ---------------------------------------------------------------------------
# GET /api/v1/judgment-lists  (Story 3.3, FR-6 list)
# ---------------------------------------------------------------------------


@router.get(
    "/judgment-lists",
    response_model=JudgmentListListResponse,
    tags=["judgments"],
)
async def list_judgment_lists_endpoint(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[JudgmentListSortKey | None, Query()] = None,
    query_set_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    cluster_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> JudgmentListListResponse:
    """List judgment lists, newest-first with cursor pagination.

    ``?since=`` filters by ``created_at >= since`` (Story 1.5). ``?q=`` FTS
    match against ``search_vector`` (name + target). ``?sort=`` is a
    :data:`JudgmentListSortKey` value with sort-aware cursor (Story 1.3).
    ``?query_set_id`` / ``?cluster_id`` filter to lists belonging to the
    supplied parent (``bug_judgment_lists_listing_ignores_query_set_filter``
    — required by the create-study modal's Step-2 dropdown so the user
    can only pick judgment-lists valid for the chosen query-set + cluster;
    without these filters the modal returns all rows and the user can
    pick a mismatched pair, which the ``POST /api/v1/studies`` cross-
    entity integrity check then rejects at create time with a confusing
    422 ``VALIDATION_ERROR: "judgment_list query_set_id does not match
    study query_set_id"``).
    """
    parsed_sort = parse_sort(sort, _JUDGMENT_LIST_SORT_COLUMNS)
    decoded_cursor: tuple[object, str] | None = None
    if cursor:
        try:
            decoded_cursor = _sort_decode_cursor(
                cursor, value_is_datetime=cursor_value_is_datetime(parsed_sort)
            )
        except Exception as exc:
            raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    rows = await repo.list_judgment_lists(
        db,
        cursor=decoded_cursor,
        limit=limit + 1,
        since=since,
        q=q,
        sort=sort,
        query_set_id=query_set_id,
        cluster_id=cluster_id,
    )
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    total = await repo.count_judgment_lists(
        db, since=since, q=q, query_set_id=query_set_id, cluster_id=cluster_id
    )
    response.headers["X-Total-Count"] = str(total)
    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        if parsed_sort is None:
            cursor_value: object = last.created_at
        else:
            cursor_value = getattr(last, parsed_sort.col_name)
        next_cursor = _sort_encode_cursor(cursor_value, last.id)
    return JudgmentListListResponse(
        data=[_summary(r) for r in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/judgment-lists/{id}  (Story 3.3, FR-6 detail)
# ---------------------------------------------------------------------------


@router.get(
    "/judgment-lists/{judgment_list_id}",
    response_model=JudgmentListDetail,
    tags=["judgments"],
)
async def get_judgment_list_endpoint(
    judgment_list_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JudgmentListDetail:
    row = await repo.get_judgment_list(db, judgment_list_id)
    if row is None:
        raise _err(
            404,
            "JUDGMENT_LIST_NOT_FOUND",
            f"judgment list {judgment_list_id} not found",
            False,
        )
    return await _detail(db, row)


# ---------------------------------------------------------------------------
# GET /api/v1/judgment-lists/{id}/judgments  (Story 3.3, FR-6 paginated)
# ---------------------------------------------------------------------------


@router.get(
    "/judgment-lists/{judgment_list_id}/judgments",
    response_model=JudgmentListJudgmentsResponse,
    tags=["judgments"],
)
async def list_judgments_endpoint(
    judgment_list_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    source: Annotated[JudgmentSourceFilterWire | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    sort: Annotated[JudgmentRowSortKey | None, Query()] = None,
) -> JudgmentListJudgmentsResponse:
    """List per-list judgments with cursor pagination.

    ``?sort=`` is :data:`JudgmentRowSortKey` with sort-aware cursor
    (feat_data_table_primitive Story 1.3).
    """
    from backend.app.db.repo.judgment import _JUDGMENT_ROW_SORT_COLUMNS

    row = await repo.get_judgment_list(db, judgment_list_id)
    if row is None:
        raise _err(
            404,
            "JUDGMENT_LIST_NOT_FOUND",
            f"judgment list {judgment_list_id} not found",
            False,
        )
    parsed_sort = parse_sort(sort, _JUDGMENT_ROW_SORT_COLUMNS)
    decoded_cursor: tuple[object, str] | None = None
    if cursor:
        try:
            decoded_cursor = _sort_decode_cursor(
                cursor, value_is_datetime=cursor_value_is_datetime(parsed_sort)
            )
        except Exception as exc:
            raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    rows = await repo.list_judgments_paginated(
        db,
        judgment_list_id,
        cursor=decoded_cursor,
        limit=limit + 1,
        source=source,
        sort=sort,
    )
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    total = await repo.count_judgments_for_list(db, judgment_list_id, source=source)
    response.headers["X-Total-Count"] = str(total)
    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        if parsed_sort is None:
            cursor_value: object = last.created_at
        else:
            cursor_value = getattr(last, parsed_sort.col_name)
        next_cursor = _sort_encode_cursor(cursor_value, last.id)
    return JudgmentListJudgmentsResponse(
        data=[_judgment_row(r) for r in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}  (Story 3.4 / FR-4)
# ---------------------------------------------------------------------------


@router.patch(
    "/judgment-lists/{judgment_list_id}/judgments/{judgment_id}",
    response_model=JudgmentRow,
    tags=["judgments"],
)
async def override_judgment(
    judgment_list_id: str,
    judgment_id: str,
    body: OverrideJudgmentRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JudgmentRow:
    """Replace an LLM rating with a human override (UPSERT-replace)."""
    if body.rating not in (0, 1, 2, 3):
        raise _err(400, "INVALID_RATING", f"rating must be 0..3 (got {body.rating})", False)

    parent = await repo.get_judgment_list(db, judgment_list_id)
    if parent is None:
        raise _err(
            404,
            "JUDGMENT_LIST_NOT_FOUND",
            f"judgment list {judgment_list_id} not found",
            False,
        )
    if parent.status == "generating":
        raise _err(
            409,
            "LIST_NOT_READY",
            f"judgment list {judgment_list_id} is still generating",
            True,
        )

    target = await repo.get_judgment(db, judgment_id)
    if target is None or target.judgment_list_id != judgment_list_id:
        raise _err(
            404,
            "JUDGMENT_NOT_FOUND",
            f"judgment {judgment_id} not found in list {judgment_list_id}",
            False,
        )

    overridden = await repo.upsert_judgment_human_override(
        db,
        judgment_list_id=judgment_list_id,
        query_id=target.query_id,
        doc_id=target.doc_id,
        rating=body.rating,
        rater_ref="operator",
        notes=body.notes,
    )
    await db.commit()
    return _judgment_row(overridden)


# ---------------------------------------------------------------------------
# POST /api/v1/judgment-lists/{id}/calibration  (Story 3.5, FR-5 + AC-3)
# ---------------------------------------------------------------------------


@router.post(
    "/judgment-lists/{judgment_list_id}/calibration",
    response_model=CalibrationResponse,
    tags=["judgments"],
)
async def calibrate_judgment_list(
    judgment_list_id: str,
    body: CalibrationSamplesRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CalibrationResponse:
    """Compute Cohen's + weighted kappa from supplied human samples.

    Pairs are built by joining each sample with the existing
    ``source='llm'`` judgment at ``(query_id, doc_id)`` — overridden rows
    (``source='human'``) are excluded (per spec FR-5 + GPT-5.5 cycle 1 F12).
    """
    parent = await repo.get_judgment_list(db, judgment_list_id)
    if parent is None:
        raise _err(
            404,
            "JUDGMENT_LIST_NOT_FOUND",
            f"judgment list {judgment_list_id} not found",
            False,
        )

    # Reject duplicate (query_id, doc_id) submissions before counting.
    # Without this, an operator could submit the same sample 10 times to
    # satisfy the threshold and distort the kappa (per GPT-5.5 cycle-9
    # C9-F2). Distinct pairs only.
    seen_pairs: set[tuple[str, str]] = set()
    for sample in body.human_samples:
        pair = (sample.query_id, sample.doc_id)
        if pair in seen_pairs:
            raise _err(
                400,
                "VALIDATION_ERROR",
                f"duplicate (query_id, doc_id) sample in calibration payload: "
                f"({sample.query_id!r}, {sample.doc_id!r})",
                False,
            )
        seen_pairs.add(pair)

    if len(body.human_samples) < 10:
        raise _err(
            400,
            "INSUFFICIENT_SAMPLES",
            f"need at least 10 human samples to compute kappa; got {len(body.human_samples)}",
            False,
        )

    # Build pairs by looking up the LLM judgment for each (query_id, doc_id).
    # Filter to source='llm' so an operator who overrode some judgments
    # before running calibration doesn't compare humans-to-humans (cycle 1 F12).
    from sqlalchemy import select as _select

    pairs: list[tuple[int, int]] = []
    for sample in body.human_samples:
        stmt = _select(Judgment).where(
            Judgment.judgment_list_id == judgment_list_id,
            Judgment.query_id == sample.query_id,
            Judgment.doc_id == sample.doc_id,
            Judgment.source == "llm",
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            logger.info(
                "calibration: dropping sample (no matching LLM rating)",
                judgment_list_id=judgment_list_id,
                query_id=sample.query_id,
                doc_id=sample.doc_id,
            )
            continue
        pairs.append((sample.rating, row.rating))

    if len(pairs) < 10:
        raise _err(
            400,
            "INSUFFICIENT_SAMPLES",
            f"insufficient LLM-rated samples to compute kappa: "
            f"{len(pairs)} matched of {len(body.human_samples)} submitted, 10 required",
            False,
        )

    result = compute_calibration(pairs)
    # Persist on the parent row.
    await repo.update_judgment_list_calibration(db, judgment_list_id, dict(result))
    await db.commit()

    return CalibrationResponse(
        cohens_kappa=result["cohens_kappa"],
        weighted_kappa=result["weighted_kappa"],
        per_class=result["per_class"],
        n_samples=result["n_samples"],
        warning=result["warning"],
    )


# Re-exported for tests that introspect the router module.
__all__ = [
    "router",
    "JudgmentListStatusWire",
]
