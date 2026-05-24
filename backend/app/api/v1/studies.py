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
    StudySortKey,
    StudyStatusWire,
    StudySummary,
    TrialDetail,
    TrialListResponse,
    TrialsSummaryShape,
)
from backend.app.db import repo
from backend.app.db.models import Study
from backend.app.db.session import get_db
from backend.app.domain.study.search_space import (
    MissingDeclaredParamError,
    SearchSpace,
    UnknownSearchSpaceParamError,
    validate_against_template,
)
from backend.app.services import study_state
from backend.app.services.study_confidence import fetch_study_confidence
from backend.app.services.study_preflight import MIN_OVERLAP, probe_judgment_overlap

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
    confidence = await fetch_study_confidence(db, row)
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
        confidence=confidence,
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

    # Validate search_space keys against template.declared_params at create time
    # (chore_create_study_wizard_polish FR-2 + FR-3). Without this, typo'd / missing
    # param keys would fail later inside adapter.render at trial-1 (see
    # backend/app/adapters/elastic.py:493-495).
    try:
        validate_against_template(
            SearchSpace.model_validate(body.search_space),
            template.declared_params,
            template.name,
        )
    except UnknownSearchSpaceParamError as exc:
        raise _err(400, "SEARCH_SPACE_UNKNOWN_PARAM", str(exc), False) from exc
    except MissingDeclaredParamError as exc:
        raise _err(400, "SEARCH_SPACE_MISSING_DECLARED_PARAM", str(exc), False) from exc

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

    # 3a. judgment_list ↔ cluster consistency (feat_study_target_judgment_mismatch_guard
    # FR-1b). Doc IDs are scoped to the cluster they were authored on; same
    # target name on two clusters still produces zero overlap. Fires BEFORE
    # the target check (3b) because cluster mismatch is the broader failure.
    if judgment_list.cluster_id != body.cluster_id:
        raise _err(
            422,
            "JUDGMENT_CLUSTER_MISMATCH",
            (
                f"judgment_list cluster_id={judgment_list.cluster_id!r} does not "
                f"match study cluster_id={body.cluster_id!r}; judgments are scoped "
                f"to the cluster they were authored on. Pick a judgment list "
                f"created against cluster {body.cluster_id!r} or change the "
                f"study's cluster."
            ),
            False,
        )

    # 3b. judgment_list ↔ target consistency (feat_study_target_judgment_mismatch_guard
    # FR-1). When targets differ, judgment doc IDs cannot overlap with search
    # results from the study's target — every trial scores 0 by construction.
    # Closes the literal study2 incident (1000 trials, 0 signal).
    if judgment_list.target != body.target:
        raise _err(
            422,
            "JUDGMENT_TARGET_MISMATCH",
            (
                f"judgment_list target={judgment_list.target!r} does not match "
                f"study target={body.target!r}; judgments would have no overlap "
                f"with search results from the study's target. Use a judgment "
                f"list generated against {body.target!r} or change study.target "
                f"to {judgment_list.target!r}."
            ),
            False,
        )

    # 3c. Preflight overlap probe (feat_study_preflight_overlap_probe FR-1).
    # Single ids-existence search against the study's target. On insufficient
    # overlap, reject 422 INSUFFICIENT_JUDGMENT_OVERLAP. On probe-skip (cluster
    # unreachable, timeout, invalid DSL), fall through silently — the probe
    # function already emitted a WARN log per FR-4.
    probe_result = await probe_judgment_overlap(
        db,
        cluster,
        judgment_list_id=body.judgment_list_id,
        query_set_id=body.query_set_id,
        target=body.target,
    )
    if probe_result is not None:
        required = min(MIN_OVERLAP, max(probe_result.judged_doc_count, 1))
        if probe_result.overlap_size < required:
            raise _err(
                422,
                "INSUFFICIENT_JUDGMENT_OVERLAP",
                (
                    f"judgment_list {judgment_list.name!r}: representative "
                    f"query_id={probe_result.representative_query_id!r} has "
                    f"{probe_result.overlap_size} of "
                    f"{probe_result.probed_doc_count} probed doc IDs present "
                    f"in cluster {cluster.name!r} target {body.target!r} "
                    f"(judged_doc_count={probe_result.judged_doc_count}). "
                    f"This is a strong signal of corpus/judgment mismatch "
                    f"(e.g., the target index was re-indexed or rotated since "
                    f"the judgments were authored) — ir_measures will likely "
                    f"score 0 on every trial. Regenerate judgments against "
                    f"the current index, or rebuild the index from the "
                    f"snapshot the judgments were authored on."
                ),
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
    cluster_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[StudySortKey | None, Query()] = None,
) -> StudyListResponse:
    """List studies with cursor pagination + X-Total-Count.

    ``?status=`` is typed as :data:`StudyStatusWire` so FastAPI returns
    422 ``VALIDATION_ERROR`` for unsupported values. ``?q=`` is a Postgres
    FTS match against ``search_vector`` (name + target). ``?sort=`` is a
    :data:`StudySortKey` value (``<col>:<asc|desc>``); the cursor is
    sort-aware (feat_data_table_primitive Stories 1.2 + 1.3).
    """
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
    from backend.app.db.repo.study import _STUDY_SORT_COLUMNS

    parsed_sort = parse_sort(sort, _STUDY_SORT_COLUMNS)
    parsed_cursor: tuple[object, str] | None = None
    if cursor:
        try:
            parsed_cursor = _sort_decode_cursor(
                cursor, value_is_datetime=cursor_value_is_datetime(parsed_sort)
            )
        except Exception as exc:
            raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    status_filter: Any = study_status if study_status else None
    rows = await repo.list_studies(
        db,
        cursor=parsed_cursor,
        limit=limit,
        since=since,
        status=status_filter,
        cluster_id=cluster_id,
        q=q,
        sort=sort,
    )
    total = await repo.count_studies(
        db, since=since, status=status_filter, cluster_id=cluster_id, q=q
    )
    response.headers["X-Total-Count"] = str(total)

    next_cursor: str | None = None
    has_more = False
    if rows and len(rows) == limit:
        last = rows[-1]
        if parsed_sort is None:
            cursor_value: object = last.created_at
        else:
            cursor_value = getattr(last, parsed_sort.col_name)
        next_cursor = _sort_encode_cursor(cursor_value, last.id)
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


def _parse_cascade(cascade: str = Query(default="true")) -> bool:
    """Parse the ``?cascade=`` query param case-insensitively.

    feat_auto_followup_studies Story 2.3, FR-8. Custom parser instead of
    a Pydantic ``bool`` to override FastAPI's default 422 envelope for
    parse failures — we want the project's canonical
    ``INVALID_CASCADE_PARAM`` (400) per spec §8.5.
    """
    normalized = cascade.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise _err(
        400,
        "INVALID_CASCADE_PARAM",
        "?cascade= must be one of: true, false (case-insensitive)",
        False,
    )


@router.post(
    "/studies/{study_id}/cancel",
    response_model=StudyDetail,
    tags=["studies"],
)
async def cancel_study(
    study_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    cascade: Annotated[bool, Depends(_parse_cascade)] = True,
) -> StudyDetail:
    """Cancel a study (Story 2.3, FR-8 + AC-8/AC-9).

    Optionally cascades to in-flight chain children.

    ``?cascade=true`` (default): routes through
    :func:`services.study_state.cancel_study_with_chain_cascade` —
    cancels the parent (if in-flight) AND recursively cancels in-flight
    descendants. Tolerates terminal parents (recurses through completed
    intermediates to reach an in-flight grandchild).

    ``?cascade=false``: routes through the original
    :func:`services.study_state.cancel_study` — single-study cancel,
    preserves the existing 409 error contract on terminal parents
    (AC-9 wire contract).
    """
    try:
        if cascade:
            row = await study_state.cancel_study_with_chain_cascade(db, study_id, cascade=True)
        else:
            row = await study_state.cancel_study(db, study_id)
        await db.commit()
    except study_state.StudyNotFound as exc:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False) from exc
    except study_state.InvalidStateTransition as exc:
        await db.rollback()
        raise _err(409, "INVALID_STATE_TRANSITION", str(exc), False) from exc
    return await _detail(db, row)


@router.get(
    "/studies/{study_id}/children",
    response_model=StudyListResponse,
    tags=["studies"],
)
async def list_study_children(
    study_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StudyListResponse:
    """List direct child studies of a parent (FR-10 + D-13).

    Returns ``{"data": [], "next_cursor": null}`` for a study with no
    children — empty data array, NOT 404. 404 only fires when the parent
    study itself is missing.

    Per D-13 (direct-children-only): does NOT return transitive
    descendants. The chain panel renders parent ↑ + direct children ↓;
    operators walk lineage one hop per page navigation.
    """
    parent = await repo.get_study(db, study_id)
    if parent is None:
        raise _err(404, "STUDY_NOT_FOUND", f"study {study_id} not found", False)
    children = await repo.list_children_of_study(db, study_id)
    # Direct children of any single parent are at most 1 (linear chains in v1),
    # so we never paginate this endpoint. has_more is always False.
    return StudyListResponse(
        data=[_summary(c) for c in children],
        next_cursor=None,
        has_more=False,
    )


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
