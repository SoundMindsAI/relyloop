# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Query-set endpoints (feat_study_lifecycle Phase 2, Story 3.2, FR-3 + AC-8).

Four endpoints under ``/api/v1/query-sets``:

* ``POST   /api/v1/query-sets``                 — register
* ``GET    /api/v1/query-sets``                 — list (cursor-paginated)
* ``GET    /api/v1/query-sets/{id}``            — detail (incl. ``query_count``)
* ``POST   /api/v1/query-sets/{id}/queries``    — bulk JSON or CSV upload

The POST-queries handler dispatches on the ``Content-Type`` header:

* ``application/json`` → Pydantic-parsed via :class:`BulkQueriesJsonRequest`.
* ``text/csv``         → parsed via
  :func:`backend.app.domain.study.csv_parser.parse_queries_csv` (AC-8).
"""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import UTC, datetime
from typing import Annotated

import structlog
import uuid_utils
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.schemas import (
    BulkQueriesJsonRequest,
    BulkQueriesResponse,
    CreateQuerySetRequest,
    JudgmentListRef,
    QueryHasJudgmentsEnvelope,
    QueryListResponse,
    QueryRow,
    QuerySetDetail,
    QuerySetListResponse,
    QuerySetSortKey,
    QuerySetSummary,
    UpdateQueryRequest,
)
from backend.app.db import repo
from backend.app.db.models import Query as QueryModel
from backend.app.db.models import QuerySet
from backend.app.db.repo._fts import rank_active, rank_bucket_of
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
from backend.app.db.repo.query_set import _QUERY_SET_SORT_COLUMNS
from backend.app.db.session import get_db
from backend.app.domain.study.csv_parser import InvalidCsvError, parse_queries_csv

logger = structlog.get_logger(__name__)

router = APIRouter()

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200

# feat_query_inline_crud — UUIDv7 lexical regex (lowercase hex, RFC 9562 shape).
_UUID_HEX_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


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


async def _detail(db: AsyncSession, row: QuerySet) -> QuerySetDetail:
    return QuerySetDetail(
        id=row.id,
        name=row.name,
        description=row.description,
        cluster_id=row.cluster_id,
        query_count=await repo.count_queries_in_set(db, row.id),
        created_at=row.created_at,
    )


def _summary(row: QuerySet, query_count: int) -> QuerySetSummary:
    return QuerySetSummary(
        id=row.id,
        name=row.name,
        cluster_id=row.cluster_id,
        query_count=query_count,
        created_at=row.created_at,
    )


@router.post(
    "/query-sets",
    response_model=QuerySetDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["query-sets"],
)
async def create_query_set(
    body: CreateQuerySetRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuerySetDetail:
    """Register a query set under a cluster (FR-3)."""
    cluster = await repo.get_cluster(db, body.cluster_id)
    if cluster is None:
        raise _err(
            404,
            "CLUSTER_NOT_FOUND",
            f"cluster {body.cluster_id} not found",
            False,
        )

    try:
        row = await repo.create_query_set(
            db,
            id=str(uuid_utils.uuid7()),
            name=body.name,
            description=body.description,
            cluster_id=body.cluster_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _err(
            409,
            "QUERY_SET_NAME_TAKEN",
            f"query set name {body.name!r} already exists",
            False,
        ) from exc
    return await _detail(db, row)


@router.get(
    "/query-sets",
    response_model=QuerySetListResponse,
    tags=["query-sets"],
)
async def list_query_sets(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[QuerySetSortKey | None, Query()] = None,
) -> QuerySetListResponse:
    """List query sets with cursor pagination + X-Total-Count.

    ``?q=`` is FTS match against ``search_vector`` (name). ``?sort=`` is a
    :data:`QuerySetSortKey` value; cursor is sort-aware.
    """
    parsed_sort = parse_sort(sort, _QUERY_SET_SORT_COLUMNS)
    is_rank = rank_active(q, parsed_sort)  # feat_fts_rank_ordering
    parsed_cursor: tuple[object, str] | None = None
    if cursor:
        try:
            parsed_cursor = _sort_decode_cursor(
                cursor,
                value_is_datetime=False if is_rank else cursor_value_is_datetime(parsed_sort),
            )
            if is_rank and not isinstance(parsed_cursor[0], int):
                # A stale non-rank cursor (datetime str) on the rank path would hit
                # the int rank_bucket column -> Postgres type error (500); reject as 422.
                raise ValueError("rank cursor value must be an integer")
        except Exception as exc:
            raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    rows = await repo.list_query_sets(
        db, cursor=parsed_cursor, limit=limit, since=since, q=q, sort=sort
    )
    total = await repo.count_query_sets(db, since=since, q=q)
    response.headers["X-Total-Count"] = str(total)

    next_cursor: str | None = None
    has_more = False
    if rows and len(rows) == limit:
        last = rows[-1]
        if is_rank:
            cursor_value: object = rank_bucket_of(last)
        elif parsed_sort is None:
            cursor_value = last.created_at
        else:
            cursor_value = getattr(last, parsed_sort.col_name)
        next_cursor = _sort_encode_cursor(cursor_value, last.id)
        has_more = True
    # One batched GROUP BY aggregate for the whole page — no per-row
    # count (see QuerySetSummary docstring + repo.count_queries_for_sets).
    counts = await repo.count_queries_for_sets(db, [r.id for r in rows])
    return QuerySetListResponse(
        data=[_summary(r, counts.get(r.id, 0)) for r in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/query-sets/{query_set_id}",
    response_model=QuerySetDetail,
    tags=["query-sets"],
)
async def get_query_set_detail(
    query_set_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuerySetDetail:
    """Return a query set by id (includes ``query_count``)."""
    row = await repo.get_query_set(db, query_set_id)
    if row is None:
        raise _err(
            404,
            "QUERY_SET_NOT_FOUND",
            f"query set {query_set_id} not found",
            False,
        )
    return await _detail(db, row)


@router.post(
    "/query-sets/{query_set_id}/queries",
    response_model=BulkQueriesResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["query-sets"],
)
async def bulk_add_queries(
    query_set_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BulkQueriesResponse:
    """Bulk-add queries to a set (FR-3 + AC-8).

    Dispatches on Content-Type:

    * ``application/json`` → :class:`BulkQueriesJsonRequest` Pydantic-parse.
    * ``text/csv`` → :func:`parse_queries_csv` (AC-8).

    Other content types → 415-equivalent surfaced as 400 ``INVALID_CSV``
    (the documented error code for content-type-mismatch in spec §7.5).
    """
    qs = await repo.get_query_set(db, query_set_id)
    if qs is None:
        raise _err(
            404,
            "QUERY_SET_NOT_FOUND",
            f"query set {query_set_id} not found",
            False,
        )

    content_type = (request.headers.get("content-type") or "").lower().split(";")[0].strip()
    rows: list[dict[str, object]]

    if content_type == "text/csv":
        body_bytes = await request.body()
        try:
            rows = parse_queries_csv(body_bytes)
        except InvalidCsvError as exc:
            raise _err(400, "INVALID_CSV", str(exc), False) from exc
    elif content_type == "application/json":
        raw = await request.json()
        try:
            parsed = BulkQueriesJsonRequest.model_validate(raw)
        except Exception as exc:
            raise _err(422, "VALIDATION_ERROR", str(exc), False) from exc
        rows = [
            {
                "query_text": item.query_text,
                "reference_answer": item.reference_answer,
                "query_metadata": item.query_metadata,
            }
            for item in parsed.queries
        ]
    else:
        raise _err(
            400,
            "INVALID_CSV",
            f"unsupported Content-Type {content_type!r}; expected text/csv or application/json",
            False,
        )

    added = await repo.bulk_create_queries(db, query_set_id, rows)
    await db.commit()
    return BulkQueriesResponse(added=added)


# ===========================================================================
# feat_query_inline_crud — per-query CRUD
# ===========================================================================


def _encode_query_cursor(query_id: str) -> str:
    """Id-only cursor (UUIDv7 is lexically time-ordered — no tuple needed)."""
    return base64.urlsafe_b64encode(json.dumps({"id": query_id}).encode()).decode()


def _decode_query_cursor(raw: str) -> str:
    """Decode + validate the id-only cursor.

    Bad shape, non-string, or non-UUIDv7-hex → 422 ``VALIDATION_ERROR``
    (per spec AC-3 + cycle-1 GPT-5.5 F2: validate the payload, don't
    just base64-decode).
    """
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
    except Exception as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    if not isinstance(decoded, dict):
        raise _err(422, "VALIDATION_ERROR", "cursor must decode to a JSON object", False)
    id_value = decoded.get("id")
    if not isinstance(id_value, str) or not _UUID_HEX_RE.match(id_value):
        raise _err(422, "VALIDATION_ERROR", "cursor.id must be a UUIDv7 string", False)
    return id_value


def _uuidv7_lower_bound_from_iso(since: datetime) -> str:
    """Construct a UUIDv7 lower-bound id from an ISO-8601 timestamp.

    RFC 9562 UUIDv7 = 48-bit ms timestamp + 4-bit version (7) + 12-bit
    rand_a + 2-bit variant (0b10) + 62-bit rand_b. The lower bound at
    timestamp ``T`` is: ``ts_ms`` in the first 48 bits, version 7 nibble,
    zero rand_a, variant nibble, zero rand_b.

    Lexical comparison of two UUIDv7 hex strings is identical to numeric
    comparison of their 128-bit values, so ``id >= :lower_bound``
    correctly filters ``ts_ms >= T``.

    Naive datetimes are interpreted as UTC (Gemini PR #101 review G1 —
    ``datetime.timestamp()`` on a naive value uses the system local time,
    which would produce non-deterministic bounds across deployments).
    """
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    ms = int(since.timestamp() * 1000)
    # Pack: 48 ts bits + 4 version bits = 52 bits.
    # Layout: TTTTTTTT-TTTT-7000-8000-000000000000
    t_high = (ms >> 16) & 0xFFFFFFFF
    t_mid = ms & 0xFFFF
    return f"{t_high:08x}-{t_mid:04x}-7000-8000-000000000000"


def _query_row(row: QueryModel, judgment_count: int) -> QueryRow:
    return QueryRow(
        id=row.id,
        query_text=row.query_text,
        reference_answer=row.reference_answer,
        query_metadata=row.query_metadata,
        judgment_count=judgment_count,
    )


# ---------------------------------------------------------------------------
# Story 1.1 — GET /api/v1/query-sets/{set_id}/queries
# ---------------------------------------------------------------------------


@router.get(
    "/query-sets/{query_set_id}/queries",
    response_model=QueryListResponse,
    tags=["query-sets"],
)
async def list_queries_in_set(
    query_set_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
) -> QueryListResponse:
    """List per-query rows under a query set, with derived ``judgment_count``."""
    qs = await repo.get_query_set(db, query_set_id)
    if qs is None:
        raise _err(
            404,
            "QUERY_SET_NOT_FOUND",
            f"query set {query_set_id} not found",
            False,
        )

    after_id = _decode_query_cursor(cursor) if cursor else None
    since_lb = _uuidv7_lower_bound_from_iso(since) if since else None

    rows = await repo.list_queries_for_set_cursor(
        db,
        query_set_id,
        after_id=after_id,
        limit=limit,
        since_lower_bound_id=since_lb,
    )
    total = await repo.count_queries_for_set(
        db,
        query_set_id,
        since_lower_bound_id=since_lb,
    )
    response.headers["X-Total-Count"] = str(total)

    counts = await repo.count_judgments_per_query(db, [r.id for r in rows])
    data = [_query_row(r, counts.get(r.id, 0)) for r in rows]

    # Cursor: emit when the page filled — matches existing list_query_sets
    # convention (acceptable empty-next-page trade-off for cursor simplicity).
    next_cursor: str | None = None
    has_more = False
    if rows and len(rows) == limit:
        next_cursor = _encode_query_cursor(rows[-1].id)
        has_more = True

    return QueryListResponse(data=data, next_cursor=next_cursor, has_more=has_more)


# ---------------------------------------------------------------------------
# Story 2.1 — PATCH /api/v1/query-sets/{set_id}/queries/{query_id}
# ---------------------------------------------------------------------------


@router.patch(
    "/query-sets/{query_set_id}/queries/{query_id}",
    response_model=QueryRow,
    tags=["query-sets"],
)
async def update_query_endpoint(
    query_set_id: str,
    query_id: str,
    body: UpdateQueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QueryRow:
    """Partial-update a query. Whole-object replace on ``query_metadata``."""
    start = time.monotonic()
    qs = await repo.get_query_set(db, query_set_id)
    if qs is None:
        raise _err(
            404,
            "QUERY_SET_NOT_FOUND",
            f"query set {query_set_id} not found",
            False,
        )

    existing = await repo.get_query(db, query_id)
    if existing is None or existing.query_set_id != query_set_id:
        # Anti-enumeration: cross-set lookups return the same shape as truly missing.
        raise _err(
            404,
            "QUERY_NOT_FOUND",
            f"query {query_id} not found",
            False,
        )

    fields_set = body.model_dump(exclude_unset=True)
    updated = await repo.update_query(db, query_id, fields_set=fields_set)
    if updated is None:
        # Concurrent delete race — treat as if the row was never there.
        raise _err(
            404,
            "QUERY_NOT_FOUND",
            f"query {query_id} not found",
            False,
        )
    await db.commit()

    counts = await repo.count_judgments_per_query(db, [query_id])

    logger.info(
        "query_updated",
        query_set_id=query_set_id,
        query_id=query_id,
        fields_changed=sorted(fields_set.keys()),
        latency_ms=int((time.monotonic() - start) * 1000),
    )
    return _query_row(updated, counts.get(query_id, 0))


# ---------------------------------------------------------------------------
# Story 3.1 — DELETE /api/v1/query-sets/{set_id}/queries/{query_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/query-sets/{query_set_id}/queries/{query_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": QueryHasJudgmentsEnvelope}},
    tags=["query-sets"],
)
async def delete_query_endpoint(
    query_set_id: str,
    query_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Hard-delete a query. FK-guarded — 409 if any judgment references it."""
    start = time.monotonic()
    qs = await repo.get_query_set(db, query_set_id)
    if qs is None:
        raise _err(
            404,
            "QUERY_SET_NOT_FOUND",
            f"query set {query_set_id} not found",
            False,
        )

    existing = await repo.get_query(db, query_id)
    if existing is None or existing.query_set_id != query_set_id:
        raise _err(
            404,
            "QUERY_NOT_FOUND",
            f"query {query_id} not found",
            False,
        )

    try:
        await repo.delete_query(db, query_id)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        refs = await repo.count_and_sample_judgment_refs(db, query_id)
        # Map repo-layer JudgmentListRefRow → API-layer JudgmentListRef.
        wire_lists = [JudgmentListRef(id=r.id, name=r.name) for r in refs.sample_lists]
        overflow_suffix = f" (showing first {len(wire_lists)})" if refs.overflow_count else ""
        message = (
            f"query {query_id} has {refs.judgment_count} judgments across "
            f"{refs.list_count} judgment list(s){overflow_suffix}; "
            f"remove the parent judgment list(s) first"
        )
        logger.info(
            "query_deleted_blocked",
            query_set_id=query_set_id,
            query_id=query_id,
            had_judgments=True,
            list_count=refs.list_count,
            judgment_count=refs.judgment_count,
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "QUERY_HAS_JUDGMENTS",
                "message": message,
                "retryable": False,
                "judgment_lists": [r.model_dump() for r in wire_lists],
                "overflow_count": refs.overflow_count,
            },
        ) from exc

    logger.info(
        "query_deleted",
        query_set_id=query_set_id,
        query_id=query_id,
        had_judgments=False,
        latency_ms=int((time.monotonic() - start) * 1000),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
