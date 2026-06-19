# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Query-template endpoints (feat_study_lifecycle Phase 2, Story 3.1, FR-2).

Three endpoints under ``/api/v1/query-templates``:

* ``POST   /api/v1/query-templates``           — register (create-time validate)
* ``GET    /api/v1/query-templates``           — list (cursor-paginated)
* ``GET    /api/v1/query-templates/{id}``      — detail

The POST handler invokes
:func:`backend.app.domain.study.template_validator.validate_template_body`
for the spec FR-2 + AC-7 checks. Validator exceptions map to the spec
§7.5 error codes via :func:`_err`. UNIQUE ``(name, version)`` collisions
surface as 409 ``TEMPLATE_NAME_TAKEN``.

Shared API helpers provide the standard error envelope and keep this router
aligned with sibling v1 endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import uuid_utils
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1._cursor import (
    decode_sort_cursor as _sort_decode_cursor,
)
from backend.app.api.v1._cursor import (
    encode_sort_cursor as _sort_encode_cursor,
)
from backend.app.api.v1._errors import _err
from backend.app.api.v1.schemas import (
    CreateQueryTemplateRequest,
    EngineTypeWire,
    QueryTemplateDetail,
    QueryTemplateListResponse,
    QueryTemplateSortKey,
    QueryTemplateSummary,
)
from backend.app.db import repo
from backend.app.db.models import QueryTemplate
from backend.app.db.repo._fts import rank_active, rank_bucket_of
from backend.app.db.repo._sort import (
    cursor_value_is_datetime,
    parse_sort,
)
from backend.app.db.repo.query_template import _QUERY_TEMPLATE_SORT_COLUMNS
from backend.app.db.session import get_db
from backend.app.domain.study.template_validator import (
    DeclaredParamUnused,
    InvalidTemplateSyntax,
    ReservedParamReferenced,
    UndeclaredParamUsed,
    validate_template_body,
)

router = APIRouter()

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


def _detail(row: QueryTemplate) -> QueryTemplateDetail:
    return QueryTemplateDetail(
        id=row.id,
        name=row.name,
        engine_type=row.engine_type,
        body=row.body,
        declared_params=row.declared_params,
        version=row.version,
        parent_id=row.parent_id,
        created_at=row.created_at,
    )


def _summary(row: QueryTemplate) -> QueryTemplateSummary:
    return QueryTemplateSummary(
        id=row.id,
        name=row.name,
        engine_type=row.engine_type,
        version=row.version,
        # declared_params is a JSONB column already loaded on the row, so
        # len() is free — no extra query, no N+1 (see QueryTemplateSummary).
        param_count=len(row.declared_params),
        created_at=row.created_at,
    )


@router.post(
    "/query-templates",
    response_model=QueryTemplateDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["query-templates"],
)
async def create_query_template(
    body: CreateQueryTemplateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QueryTemplateDetail:
    """Register a query template (FR-2 + AC-7).

    AC-7: a body containing ``{{ os.system('rm -rf /') }}`` surfaces as
    400 ``INVALID_TEMPLATE_SYNTAX`` (the AST walk catches the ``Call``
    node before reaching the meta-vars cross-check that would otherwise
    classify ``os`` as ``UndeclaredParamUsed``).
    """
    try:
        validate_template_body(body.body, body.declared_params)
    except InvalidTemplateSyntax as exc:
        raise _err(400, "INVALID_TEMPLATE_SYNTAX", str(exc), False) from exc
    except UndeclaredParamUsed as exc:
        raise _err(400, "UNDECLARED_PARAM_USED", str(exc), False) from exc
    except DeclaredParamUnused as exc:
        raise _err(400, "DECLARED_PARAM_UNUSED", str(exc), False) from exc
    except ReservedParamReferenced as exc:
        raise _err(400, "RESERVED_PARAM_REFERENCED", str(exc), False) from exc

    try:
        row = await repo.create_query_template(
            db,
            id=str(uuid_utils.uuid7()),
            name=body.name,
            engine_type=body.engine_type,
            body=body.body,
            declared_params=body.declared_params,
            version=1,
            parent_id=body.parent_id,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _err(
            409,
            "TEMPLATE_NAME_TAKEN",
            f"query template name {body.name!r} version 1 already exists",
            False,
        ) from exc
    return _detail(row)


@router.get(
    "/query-templates",
    response_model=QueryTemplateListResponse,
    tags=["query-templates"],
)
async def list_query_templates(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[QueryTemplateSortKey | None, Query()] = None,
    engine_type: Annotated[EngineTypeWire | None, Query()] = None,
) -> QueryTemplateListResponse:
    """List query templates with cursor pagination + X-Total-Count header.

    ``?q=`` FTS match (name). ``?sort=`` sort-aware cursor (Story 1.3).
    ``?engine_type=`` filters by engine (Story 1.4).
    """
    parsed_sort = parse_sort(sort, _QUERY_TEMPLATE_SORT_COLUMNS)
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
    rows = await repo.list_query_templates(
        db,
        cursor=parsed_cursor,
        limit=limit,
        since=since,
        q=q,
        sort=sort,
        engine_type=engine_type,
    )
    total = await repo.count_query_templates(db, since=since, q=q, engine_type=engine_type)
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
    return QueryTemplateListResponse(
        data=[_summary(r) for r in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/query-templates/{template_id}",
    response_model=QueryTemplateDetail,
    tags=["query-templates"],
)
async def get_query_template_detail(
    template_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QueryTemplateDetail:
    """Return a query template by id."""
    row = await repo.get_query_template(db, template_id)
    if row is None:
        raise _err(
            404,
            "TEMPLATE_NOT_FOUND",
            f"query template {template_id} not found",
            False,
        )
    return _detail(row)
