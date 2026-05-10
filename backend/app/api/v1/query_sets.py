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
from datetime import datetime
from typing import Annotated

import uuid_utils
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.schemas import (
    BulkQueriesJsonRequest,
    BulkQueriesResponse,
    CreateQuerySetRequest,
    QuerySetDetail,
    QuerySetListResponse,
    QuerySetSummary,
)
from backend.app.db import repo
from backend.app.db.models import QuerySet
from backend.app.db.session import get_db
from backend.app.domain.study.csv_parser import InvalidCsvError, parse_queries_csv

router = APIRouter()

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


async def _detail(db: AsyncSession, row: QuerySet) -> QuerySetDetail:
    return QuerySetDetail(
        id=row.id,
        name=row.name,
        description=row.description,
        cluster_id=row.cluster_id,
        query_count=await repo.count_queries_in_set(db, row.id),
        created_at=row.created_at,
    )


def _summary(row: QuerySet) -> QuerySetSummary:
    return QuerySetSummary(
        id=row.id,
        name=row.name,
        cluster_id=row.cluster_id,
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
) -> QuerySetListResponse:
    """List query sets with cursor pagination + X-Total-Count."""
    parsed_cursor = _decode_cursor(cursor) if cursor else None
    rows = await repo.list_query_sets(db, cursor=parsed_cursor, limit=limit, since=since)
    total = await repo.count_query_sets(db, since=since)
    response.headers["X-Total-Count"] = str(total)

    next_cursor: str | None = None
    has_more = False
    if rows and len(rows) == limit:
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)
        has_more = True
    return QuerySetListResponse(
        data=[_summary(r) for r in rows],
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
