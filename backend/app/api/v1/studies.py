"""Study endpoints (feat_study_lifecycle Phase 2, Story 3.3 + 3.4).

Five endpoints under ``/api/v1/studies``:

* ``POST   /api/v1/studies``                — create + enqueue start_study
* ``GET    /api/v1/studies``                — list (cursor-paginated)
* ``GET    /api/v1/studies/{id}``           — detail (incl. trials_summary)
* ``POST   /api/v1/studies/{id}/cancel``    — service-layer cancel
* ``GET    /api/v1/studies/{id}/trials``    — Story 3.4 (cursor + sort + since)

The POST handler:

1. Validates ``search_space`` via
   :class:`backend.app.domain.study.search_space.SearchSpace.model_validate`
   — failure → 400 ``INVALID_SEARCH_SPACE``.
2. Resolves cluster / template / query_set / judgment_list — each
   absent → its ``*_NOT_FOUND`` code.
3. Verifies judgment_list.query_set_id matches request.query_set_id —
   mismatch → 422 ``VALIDATION_ERROR`` (spec §11 edge/error flows).
4. Serializes ``config`` with ``exclude_none + exclude_unset`` so absent
   keys stay absent (key-omission contract from Story 1.5 + spec FR-2
   pruner key-presence semantics).
5. Inserts the study row with ``status='queued'`` and
   ``optuna_study_name=str(study_id)``.
6. Enqueues ``start_study(study_id)`` against the FastAPI app-state
   Arq pool (set in main.py:lifespan).

The cancel handler routes through
:func:`backend.app.services.study_state.cancel_study`; the orchestrator
detects the new status on its next poll tick and drains.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Any

import uuid_utils
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.v1.schemas import (
    CreateStudyRequest,
    StudyDetail,
    StudyListResponse,
    StudyStatusWire,
    StudySummary,
    TrialDetail,
    TrialListResponse,
    TrialsSummaryShape,
)
from backend.app.db import repo
from backend.app.db.models import Study
from backend.app.db.session import get_db
from backend.app.domain.study.search_space import SearchSpace
from backend.app.services import study_state

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


def _encode_trial_cursor(value: Any, row_id: str) -> str:
    """Sort-key-agnostic cursor encoder. ``value`` may be float / datetime / int / None."""
    if isinstance(value, datetime):
        encoded_value: Any = value.isoformat()
    else:
        encoded_value = value
    return base64.urlsafe_b64encode(json.dumps([encoded_value, row_id]).encode()).decode()


def _decode_trial_cursor(raw: str, sort_key: str) -> tuple[Any, str]:
    """Decode a trial cursor; the value-half shape depends on ``sort_key``."""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        raw_value = decoded[0]
        row_id = str(decoded[1])
    except Exception as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    if sort_key.startswith("ended_at"):
        value: Any = datetime.fromisoformat(raw_value) if raw_value is not None else None
    else:
        value = raw_value
    return value, row_id


async def _detail(db: AsyncSession, row: Study) -> StudyDetail:
    summary = await repo.aggregate_trials_summary(db, row.id)
    return StudyDetail(
        id=row.id,
        name=row.name,
        cluster_id=row.cluster_id,
        target=row.target,
        template_id=row.template_id,
        query_set_id=row.query_set_id,
        judgment_list_id=row.judgment_list_id,
        search_space=row.search_space,
        objective=row.objective,
        config=row.config,
        status=row.status,
        failed_reason=row.failed_reason,
        optuna_study_name=row.optuna_study_name,
        parent_study_id=row.parent_study_id,
        baseline_metric=row.baseline_metric,
        best_metric=row.best_metric,
        best_trial_id=row.best_trial_id,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        trials_summary=TrialsSummaryShape(
            total=summary.total,
            complete=summary.complete,
            failed=summary.failed,
            pruned=summary.pruned,
            best_primary_metric=summary.best_primary_metric,
        ),
    )


def _summary(row: Study) -> StudySummary:
    return StudySummary(
        id=row.id,
        name=row.name,
        cluster_id=row.cluster_id,
        status=row.status,
        best_metric=row.best_metric,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


async def _enqueue_start_study(request: Request, study_id: str) -> None:
    """Enqueue start_study via the app-state Arq pool when present.

    The pool is wired in ``main.py:lifespan``; under TestClient or in
    tests that boot the app without the lifespan we tolerate a missing
    pool by logging a warning rather than failing the POST. Operators
    must boot the worker process to actually drive the study lifecycle
    (documented in `docs/03_runbooks/study-lifecycle-debugging.md` from
    Story 4.1).
    """
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        return
    await arq_pool.enqueue_job("start_study", study_id)


# ---------------------------------------------------------------------------
# POST /api/v1/studies
# ---------------------------------------------------------------------------


@router.post(
    "/studies",
    response_model=StudyDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["studies"],
)
async def create_study(
    body: CreateStudyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudyDetail:
    """Create a study (FR-1 + AC-1) and enqueue the orchestrator job."""
    # 1. SearchSpace validation.
    try:
        SearchSpace.model_validate(body.search_space)
    except ValidationError as exc:
        raise _err(400, "INVALID_SEARCH_SPACE", str(exc), False) from exc

    # 2. FK resolution.
    cluster = await repo.get_cluster(db, body.cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {body.cluster_id} not found", False)
    template = await repo.get_query_template(db, body.template_id)
    if template is None:
        raise _err(404, "TEMPLATE_NOT_FOUND", f"template {body.template_id} not found", False)
    query_set = await repo.get_query_set(db, body.query_set_id)
    if query_set is None:
        raise _err(404, "QUERY_SET_NOT_FOUND", f"query set {body.query_set_id} not found", False)
    judgment_list = await repo.get_judgment_list(db, body.judgment_list_id)
    if judgment_list is None:
        raise _err(
            404,
            "JUDGMENT_LIST_NOT_FOUND",
            f"judgment list {body.judgment_list_id} not found",
            False,
        )

    # 3. judgment_list ↔ query_set consistency (spec §11 edge/error flows).
    if judgment_list.query_set_id != body.query_set_id:
        raise _err(
            422,
            "VALIDATION_ERROR",
            "judgment_list query_set_id does not match study query_set_id",
            False,
        )

    # 4. Serialize config with exclude_none + exclude_unset (C3-F1 + Story 1.5).
    config_payload = body.config.model_dump(exclude_none=True, exclude_unset=True)

    # 5. UUIDv7 + INSERT + commit.
    study_id = str(uuid_utils.uuid7())
    row = await repo.create_study(
        db,
        id=study_id,
        name=body.name,
        cluster_id=body.cluster_id,
        target=body.target,
        template_id=body.template_id,
        query_set_id=body.query_set_id,
        judgment_list_id=body.judgment_list_id,
        search_space=body.search_space,
        objective=body.objective.model_dump(),
        config=config_payload,
        status="queued",
        optuna_study_name=study_id,
    )
    await db.commit()

    # 6. Best-effort Arq enqueue.
    await _enqueue_start_study(request, study_id)

    return await _detail(db, row)


# ---------------------------------------------------------------------------
# GET /api/v1/studies
# ---------------------------------------------------------------------------


@router.get(
    "/studies",
    response_model=StudyListResponse,
    tags=["studies"],
)
async def list_studies(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
    study_status: Annotated[StudyStatusWire | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
) -> StudyListResponse:
    """List studies with cursor pagination + X-Total-Count.

    ``?status=`` is typed as :data:`StudyStatusWire` so FastAPI returns
    422 ``VALIDATION_ERROR`` for unsupported values rather than silently
    returning an empty list (C3-F2 GPT-5.5 cycle-3 fix). ``?q=`` is a
    Postgres FTS match against ``search_vector`` (name + target);
    2-200 chars. Filter-only — ordering unchanged per spec FR-1
    (feat_data_table_primitive Story 1.2).
    """
    parsed_cursor = _decode_cursor(cursor) if cursor else None
    status_filter: Any = study_status if study_status else None
    rows = await repo.list_studies(
        db,
        cursor=parsed_cursor,
        limit=limit,
        since=since,
        status=status_filter,
        q=q,
    )
    total = await repo.count_studies(db, since=since, status=status_filter, q=q)
    response.headers["X-Total-Count"] = str(total)

    next_cursor: str | None = None
    has_more = False
    if rows and len(rows) == limit:
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)
        has_more = True
    return StudyListResponse(
        data=[_summary(r) for r in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/studies/{id}
# ---------------------------------------------------------------------------


@router.get(
    "/studies/{study_id}",
    response_model=StudyDetail,
    tags=["studies"],
)
async def get_study_detail(
    study_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudyDetail:
    """Return a study by id (includes ``trials_summary``)."""
    row = await repo.get_study(db, study_id)
    if row is None:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False)
    return await _detail(db, row)


# ---------------------------------------------------------------------------
# POST /api/v1/studies/{id}/cancel
# ---------------------------------------------------------------------------


@router.post(
    "/studies/{study_id}/cancel",
    response_model=StudyDetail,
    tags=["studies"],
)
async def cancel_study(
    study_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudyDetail:
    """Cancel a study (FR-1 + AC-3).

    Routes through :func:`services.study_state.cancel_study`. The
    orchestrator detects the new status on its next poll tick and drains
    in-flight trials. Cancelling an already-terminal study (completed /
    cancelled / failed) raises ``InvalidStateTransition`` → 409.
    """
    try:
        row = await study_state.cancel_study(db, study_id)
        await db.commit()
    except study_state.StudyNotFound as exc:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False) from exc
    except study_state.InvalidStateTransition as exc:
        await db.rollback()
        raise _err(409, "INVALID_STATE_TRANSITION", str(exc), False) from exc
    return await _detail(db, row)


# ---------------------------------------------------------------------------
# GET /api/v1/studies/{id}/trials  (Story 3.4 — FR-6)
# ---------------------------------------------------------------------------


_ALLOWED_SORT_KEYS = frozenset(
    {
        "primary_metric_desc",
        "primary_metric_asc",
        "ended_at_desc",
        "ended_at_asc",
        "optuna_trial_number_asc",
    }
)


@router.get(
    "/studies/{study_id}/trials",
    response_model=TrialListResponse,
    tags=["trials"],
)
async def list_study_trials(
    study_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
    sort: Annotated[str, Query()] = "primary_metric_desc",
) -> TrialListResponse:
    """List trials in a study (FR-6).

    Sort variants per spec §7.4: ``primary_metric_desc`` (default),
    ``primary_metric_asc``, ``ended_at_desc``, ``ended_at_asc``,
    ``optuna_trial_number_asc``.
    """
    if sort not in _ALLOWED_SORT_KEYS:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"unsupported sort key {sort!r}; allowed: {sorted(_ALLOWED_SORT_KEYS)}",
            False,
        )

    study = await repo.get_study(db, study_id)
    if study is None:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False)

    parsed_cursor = _decode_trial_cursor(cursor, sort) if cursor else None
    rows = await repo.list_trials_paginated(
        db,
        study_id,
        cursor=parsed_cursor,
        limit=limit,
        sort_key=sort,  # type: ignore[arg-type]
        since=since,
    )
    total = await repo.count_trials(db, study_id, since=since)
    response.headers["X-Total-Count"] = str(total)

    next_cursor: str | None = None
    has_more = False
    if rows and len(rows) == limit:
        last = rows[-1]
        cursor_value: Any
        if sort.startswith("primary_metric"):
            cursor_value = last.primary_metric
        elif sort.startswith("ended_at"):
            cursor_value = last.ended_at
        else:  # optuna_trial_number_asc
            cursor_value = last.optuna_trial_number
        next_cursor = _encode_trial_cursor(cursor_value, last.id)
        has_more = True

    return TrialListResponse(
        data=[
            TrialDetail(
                id=t.id,
                study_id=t.study_id,
                optuna_trial_number=t.optuna_trial_number,
                params=t.params,
                primary_metric=t.primary_metric,
                metrics=t.metrics,
                duration_ms=t.duration_ms,
                status=t.status,
                error=t.error,
                started_at=t.started_at,
                ended_at=t.ended_at,
            )
            for t in rows
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )
