"""Cluster CRUD + schema + run_query router (Stories 3.2, 3.3, 3.4).

Endpoints (per spec §7.1, FR-5/FR-4/FR-6):

* ``POST   /api/v1/clusters``                       — register
* ``GET    /api/v1/clusters``                       — list (cursor-paginated)
* ``GET    /api/v1/clusters/{cluster_id}``          — detail
* ``DELETE /api/v1/clusters/{cluster_id}``          — soft-delete
* ``GET    /api/v1/clusters/{cluster_id}/schema``   — schema introspection
* ``GET    /api/v1/clusters/{cluster_id}/targets``  — list indices/collections
* ``POST   /api/v1/clusters/{cluster_id}/run_query``— ad-hoc DSL execution
* ``GET    /api/v1/clusters/{cluster_id}/targets/{target}/documents``
                                                      — paginated documents list
                                                        (feat_index_document_browser FR-3)
* ``GET    /api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id:path}``
                                                      — single document detail
                                                        (feat_index_document_browser FR-4)

Service exceptions are translated into the spec §7.5 error envelope here
via ``HTTPException(detail={...})`` so the existing
``backend.app.api.errors.http_exception_handler`` passes the structured
detail through unchanged.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
    TargetNotFoundError,
    TargetsForbiddenError,
)
from backend.app.adapters.protocol import Document, HealthStatus
from backend.app.adapters.protocol import Schema as AdapterSchema
from backend.app.api.health import get_redis_client
from backend.app.api.v1._documents_cursor import (
    decode_documents_cursor,
    encode_documents_cursor,
)
from backend.app.api.v1._documents_fields import parse_fields_csv
from backend.app.api.v1._errors import _err as _err  # noqa: F401 — re-export
from backend.app.api.v1._strict_query_params import strict_unknown_query_params
from backend.app.api.v1.schemas import (
    ClusterDetail,
    ClusterListResponse,
    ClusterSortKey,
    ClusterSummary,
    CreateClusterRequest,
    DocumentListResponse,
    DocumentSummary,
    EngineTypeWire,
    Environment,
    HealthCheckResult,
    RunQueryHit,
    RunQueryRequest,
    RunQueryResponse,
    TargetListResponse,
    UbiReadinessResponse,
)
from backend.app.db import repo
from backend.app.db.models import Cluster
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
from backend.app.db.session import get_db
from backend.app.services import cluster as cluster_svc
from backend.app.services._target_filter import check_target_visible
from backend.app.services.cluster import (
    AuthKindNotSupported,
    ClusterNameTaken,
    ClusterUnreachable,
    EngineTypeNotSupported,
    dispatch_run_query,
)
from backend.app.services.documents import truncate_source_for_list
from backend.app.services.ubi_readiness import classify_rung

router = APIRouter()
logger = structlog.get_logger(__name__)

# Sort allowlist is owned by the repo layer (single source of truth across
# every list endpoint in this PR). Import inside the handler to avoid a
# module-level import cycle.

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200
DEFAULT_RUN_QUERY_TIMEOUT_S = 5.0
MAX_RUN_QUERY_TIMEOUT_S = 30.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encode_cursor(created_at: datetime, cluster_id: str) -> str:
    """Base64-JSON encoding of ``(created_at_iso, id)`` for cursor pagination."""
    return base64.urlsafe_b64encode(
        json.dumps([created_at.isoformat(), cluster_id]).encode()
    ).decode()


def _decode_cursor(raw: str) -> tuple[datetime, str]:
    """Reverse of ``_encode_cursor``; raises 422 ``VALIDATION_ERROR`` on parse failure."""
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        created_at = datetime.fromisoformat(decoded[0])
        cluster_id = str(decoded[1])
    except Exception as exc:
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    return created_at, cluster_id


def _summary(cluster: Cluster, health: HealthStatus) -> ClusterSummary:
    return ClusterSummary(
        id=cluster.id,
        name=cluster.name,
        engine_type=cluster.engine_type,
        environment=cluster.environment,
        base_url=cluster.base_url,
        auth_kind=cluster.auth_kind,
        target_filter=cluster.target_filter,
        created_at=cluster.created_at,
        health_check=HealthCheckResult.model_validate(health.model_dump()),
    )


def _detail(cluster: Cluster, health: HealthStatus) -> ClusterDetail:
    return ClusterDetail(
        id=cluster.id,
        name=cluster.name,
        engine_type=cluster.engine_type,
        environment=cluster.environment,
        base_url=cluster.base_url,
        auth_kind=cluster.auth_kind,
        engine_config=cluster.engine_config,
        notes=cluster.notes,
        target_filter=cluster.target_filter,
        created_at=cluster.created_at,
        health_check=HealthCheckResult.model_validate(health.model_dump()),
    )


# ---------------------------------------------------------------------------
# POST / GET-list / GET-detail / DELETE
# ---------------------------------------------------------------------------


@router.post(
    "/clusters",
    response_model=ClusterDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["clusters"],
)
async def create_cluster(
    body: CreateClusterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> ClusterDetail:
    """Register a cluster (FR-5 / AC-1)."""
    try:
        cluster, health = await cluster_svc.register_cluster(
            db,
            redis,
            name=body.name,
            engine_type=body.engine_type,
            environment=body.environment,
            base_url=body.base_url,
            auth_kind=body.auth_kind,
            credentials_ref=body.credentials_ref,
            engine_config=body.engine_config,
            notes=body.notes,
            target_filter=body.target_filter,
        )
    except EngineTypeNotSupported as exc:
        raise _err(400, "ENGINE_NOT_SUPPORTED", str(exc), False) from exc
    except AuthKindNotSupported as exc:
        raise _err(400, "AUTH_KIND_NOT_SUPPORTED", str(exc), False) from exc
    except ClusterNameTaken as exc:
        raise _err(409, "CLUSTER_NAME_TAKEN", f"name {exc} is already registered", False) from exc
    except ClusterUnreachable as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc
    return _detail(cluster, health)


@router.get(
    "/clusters",
    response_model=ClusterListResponse,
    tags=["clusters"],
)
async def list_clusters(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis_client)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
    sort: Annotated[ClusterSortKey | None, Query()] = None,
    engine_type: Annotated[EngineTypeWire | None, Query()] = None,
    environment: Annotated[Environment | None, Query()] = None,
) -> ClusterListResponse:
    """List clusters with cursor pagination + ``X-Total-Count`` header.

    ``?q=`` is a Postgres FTS match against the cluster's ``search_vector``
    (name + base_url); 2–200 chars. Filter-only — ordering unchanged per
    spec FR-1. ``?sort=`` is one of the values in
    :data:`~backend.app.api.v1.schemas.ClusterSortKey`; the cursor is
    sort-aware so the keyset predicate matches the active ORDER BY
    (feat_data_table_primitive Stories 1.2 + 1.3).
    """
    from backend.app.db.repo.cluster import _CLUSTER_SORT_COLUMNS

    parsed_sort = parse_sort(sort, _CLUSTER_SORT_COLUMNS)
    parsed_cursor: tuple[object, str] | None = None
    if cursor:
        try:
            parsed_cursor = _sort_decode_cursor(
                cursor, value_is_datetime=cursor_value_is_datetime(parsed_sort)
            )
        except Exception as exc:
            raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
    rows = await repo.list_clusters(
        db,
        cursor=parsed_cursor,
        limit=limit,
        since=since,
        q=q,
        sort=sort,
        engine_type=engine_type,
        environment=environment,
    )
    total = await repo.count_clusters(
        db, since=since, q=q, engine_type=engine_type, environment=environment
    )
    response.headers["X-Total-Count"] = str(total)

    summaries: list[ClusterSummary] = []
    for c in rows:
        h = await cluster_svc.get_or_probe_health(redis, c)
        summaries.append(_summary(c, h))

    next_cursor: str | None = None
    has_more = False
    if rows and len(rows) == limit:
        last = rows[-1]
        # Compute the value-half of the next cursor from the active sort col.
        if parsed_sort is None:
            cursor_value: object = last.created_at
        else:
            cursor_value = getattr(last, parsed_sort.col_name)
        next_cursor = _sort_encode_cursor(cursor_value, last.id)
        has_more = True
    return ClusterListResponse(data=summaries, next_cursor=next_cursor, has_more=has_more)


@router.get(
    "/clusters/{cluster_id}",
    response_model=ClusterDetail,
    tags=["clusters"],
)
async def get_cluster_detail(
    cluster_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> ClusterDetail:
    """Return cluster row + cached/fresh health probe."""
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id} not found", False)
    health = await cluster_svc.get_or_probe_health(redis, cluster)
    return _detail(cluster, health)


@router.delete(
    "/clusters/{cluster_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["clusters"],
)
async def delete_cluster(
    cluster_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Soft-delete a cluster (AC-8). Returns 204 with no body."""
    cluster = await cluster_svc.soft_delete_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id} not found", False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Story 3.3 — Schema introspection
# ---------------------------------------------------------------------------


@router.get(
    "/clusters/{cluster_id}/schema",
    response_model=AdapterSchema,
    tags=["clusters"],
)
async def get_cluster_schema(
    cluster_id: str,
    target: Annotated[str, Query(..., min_length=1, max_length=256)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdapterSchema:
    """Return the field schema for ``target`` (FR-4 / AC-2)."""
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id} not found", False)
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            return await adapter.get_schema(target)
    except TargetNotFoundError as exc:
        raise _err(404, "TARGET_NOT_FOUND", f"target {exc.target!r} not found", False) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc


# ---------------------------------------------------------------------------
# feat_create_study_target_autocomplete Story B2 — Target list
# ---------------------------------------------------------------------------


@router.get(
    "/clusters/{cluster_id}/ubi-readiness",
    response_model=UbiReadinessResponse,
    tags=["clusters"],
)
async def get_cluster_ubi_readiness(
    cluster_id: str,
    query_set_id: Annotated[str, Query(..., min_length=1, max_length=36)],
    target: Annotated[str, Query(..., min_length=1, max_length=256)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> UbiReadinessResponse:
    """Classify ``(cluster, query_set, target)`` on the UBI rung ladder.

    feat_ubi_judgments FR-7.

    Required query params: ``query_set_id`` + ``target`` (Spec FR-7 +
    cycle-3 D-10c: the endpoint MUST 422 without them — the classifier
    can't compute a per-target rung without an application filter).

    Error envelopes (all per spec §7.5):
    * ``404 CLUSTER_NOT_FOUND`` — cluster row missing or soft-deleted.
    * ``404 QUERY_SET_NOT_FOUND`` — query set row missing.
    * ``422 VALIDATION_ERROR`` — missing required query params (FastAPI's
      built-in handler, surfaces via ``api/errors.py``).
    * ``503 CLUSTER_UNREACHABLE`` — adapter cannot reach the cluster.

    The result is cached for 60 s in Redis per
    ``(cluster_id, query_set_id, target)`` so back-to-back dialog-open
    and dialog-submit calls don't re-probe.
    """
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id} not found", False)
    query_set = await repo.get_query_set(db, query_set_id)
    if query_set is None:
        raise _err(
            404,
            "QUERY_SET_NOT_FOUND",
            f"query set {query_set_id} not found",
            False,
        )

    # Consistency: the query set must belong to the requested cluster
    # (GPT-5.5 PR #317 finding #3, sub-point) — otherwise the rung is
    # computed against a target the query set was never run on.
    if query_set.cluster_id != cluster_id:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"query_set {query_set_id} belongs to cluster "
            f"{query_set.cluster_id!r}, not {cluster_id!r}",
            False,
        )

    # NOTE: we do NOT pass RelyLoop's internal queries.id values as a
    # query_id filter. UBI's ubi_events.query_id is the plugin's own UUID,
    # not queries.id — filtering on the internal ids would match nothing
    # and silently under-report every cluster to rung_1 (GPT-5.5 PR #317
    # finding #3). Mapping internal → UBI ids needs the user_query join,
    # which the readiness probe deliberately skips (it must complete in
    # <2s per spec §6). The rung is therefore a target-level signal — same
    # approximation as the dispatcher's U-D2 count.
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            snapshot = await classify_rung(
                adapter=adapter,
                cluster_id=cluster_id,
                query_set_id=query_set_id,
                query_set_query_ids=[],
                target=target,
                redis=redis,
            )
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc

    return UbiReadinessResponse(
        rung=snapshot.rung,
        covered_pairs_pct=snapshot.covered_pairs_pct,
        head_covered=snapshot.head_covered,
        checked_at=snapshot.checked_at,
    )


@router.get(
    "/clusters/{cluster_id}/targets",
    response_model=TargetListResponse,
    tags=["clusters"],
)
async def list_cluster_targets(
    cluster_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TargetListResponse:
    """List targets (indices/collections) on the cluster (FR-1 / AC-1).

    Thin passthrough to ``ElasticAdapter.list_targets()`` (which filters out
    system indices whose names start with ``.``). Mirrors the ``get_cluster_schema``
    pattern: ``get_cluster`` → ``acquire_adapter`` async context → adapter call
    → translate exceptions via the ``_err()`` helper to the spec §7.5 envelope.

    Error mapping:
    * cluster missing or soft-deleted → 404 ``CLUSTER_NOT_FOUND`` (retryable=false)
    * adapter raises ``TargetsForbiddenError`` (ACL 401/403) → 403
      ``TARGETS_FORBIDDEN`` (retryable=false) — frontend auto-engages manual mode
    * adapter raises ``ClusterUnreachableError`` (5xx / connection failure) → 503
      ``CLUSTER_UNREACHABLE`` (retryable=true)
    """
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id} not found", False)
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            # feat_cluster_target_filter FR-3: when the cluster has a stored
            # target_filter, scope list_targets() to matching index names.
            targets = await adapter.list_targets(target_filter=cluster.target_filter)
            return TargetListResponse(data=targets)
    except TargetsForbiddenError as exc:
        raise _err(403, "TARGETS_FORBIDDEN", str(exc), False) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc


# ---------------------------------------------------------------------------
# Story 3.4 — Run-query
# ---------------------------------------------------------------------------


@router.post(
    "/clusters/{cluster_id}/run_query",
    response_model=RunQueryResponse,
    tags=["clusters"],
)
async def run_query(
    cluster_id: str,
    body: RunQueryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    timeout_s: Annotated[
        float,
        Query(ge=1.0, le=MAX_RUN_QUERY_TIMEOUT_S),
    ] = DEFAULT_RUN_QUERY_TIMEOUT_S,
) -> RunQueryResponse:
    """Execute one query DSL fragment against the cluster (FR-6 / AC-3)."""
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id} not found", False)
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            hits = await dispatch_run_query(
                adapter,
                target=body.target,
                query_dsl=body.query_dsl,
                top_k=body.top_k,
                timeout_s=timeout_s,
            )
    except InvalidQueryDSLError as exc:
        raise _err(400, "INVALID_QUERY_DSL", str(exc), False) from exc
    except QueryTimeoutError as exc:
        raise _err(504, "QUERY_TIMEOUT", str(exc), True) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc
    return RunQueryResponse(
        hits=[RunQueryHit(doc_id=h.doc_id, score=h.score, source=h.source) for h in hits]
    )


# ---------------------------------------------------------------------------
# feat_index_document_browser — documents browse endpoints
#
# Spec FR-3 (list) / FR-4 (detail). Error envelope catalog for this surface:
# CLUSTER_NOT_FOUND (404), TARGET_NOT_FOUND (404), DOCUMENT_NOT_FOUND (404 —
# NEW, detail endpoint only), TARGETS_FORBIDDEN (403), CLUSTER_UNREACHABLE
# (503), VALIDATION_ERROR (422 — incl. unknown-query-param + wildcard
# fields). Per CLAUDE.md Absolute Rule #4 the engine-specific HTTP lives in
# the adapter; this router composes adapter methods + service helpers.
# ---------------------------------------------------------------------------


_DOCUMENTS_LIST_ALLOWED_PARAMS = {"cursor", "limit", "fields"}


@router.get(
    "/clusters/{cluster_id}/targets/{target}/documents",
    response_model=DocumentListResponse,
    tags=["clusters"],
)
async def list_target_documents(
    cluster_id: str,
    target: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    fields: Annotated[str | None, Query(max_length=2048)] = None,
    _strict: Annotated[
        None,
        Depends(strict_unknown_query_params(_DOCUMENTS_LIST_ALLOWED_PARAMS)),
    ] = None,
) -> DocumentListResponse:
    """Paginated _id + truncated _source preview for a target (FR-3).

    The endpoint asks the adapter for ``limit + 1`` rows so it can detect
    end-of-data exactly (no extra round-trip). Only the first ``limit`` rows
    are returned; ``next_cursor`` encodes the ES ``hits[i].sort`` of the
    last visible row when ``has_more`` is True. ``X-Total-Count`` header
    carries the engine's ``hits.total.value``.
    """
    # Validate query-string format before DB I/O so malformed input always
    # surfaces as 422 VALIDATION_ERROR (matching the contract-level promise
    # to the frontend) regardless of whether the cluster_id is valid.
    parsed_fields = parse_fields_csv(fields)  # raises 422 on wildcard
    search_after = decode_documents_cursor(cursor) if cursor else None

    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id!r} not found", False)
    if not check_target_visible(cluster, target):
        raise _err(404, "TARGET_NOT_FOUND", f"target {target!r} not found", False)

    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            page = await adapter.list_documents(
                target,
                search_after=search_after,
                limit=limit + 1,  # overfetch one for has_more detection
                fields=parsed_fields,
            )
    except TargetNotFoundError as exc:
        raise _err(404, "TARGET_NOT_FOUND", f"target {exc.target!r} not found", False) from exc
    except TargetsForbiddenError as exc:
        raise _err(403, "TARGETS_FORBIDDEN", str(exc), False) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc

    visible_hits = page.hits[:limit]
    has_more = len(page.hits) > limit
    next_cursor = (
        encode_documents_cursor(visible_hits[-1].sort) if has_more and visible_hits else None
    )

    response.headers["X-Total-Count"] = str(page.total)
    logger.info(
        "documents.list_requested",
        cluster_id=cluster_id,
        target=target,
        cursor_present=cursor is not None,
        limit=limit,
        status="ok",
    )
    return DocumentListResponse(
        data=[
            DocumentSummary(doc_id=h.doc_id, source=truncate_source_for_list(h.source))
            for h in visible_hits
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/clusters/{cluster_id}/targets/{target}/documents/{doc_id:path}",
    response_model=Document,
    tags=["clusters"],
)
async def get_target_document(
    cluster_id: str,
    target: str,
    doc_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Document:
    """Fetch one document by ``_id`` (FR-4).

    FastAPI's ``{doc_id:path}`` converter round-trips slashes verbatim, so
    operator IDs containing ``/`` are supported (D-17 / AC-16). Returns the
    adapter ``Document`` shape directly; on ``found: false`` returns 404
    ``DOCUMENT_NOT_FOUND`` (distinct from ``TARGET_NOT_FOUND``).
    """
    cluster = await repo.get_cluster(db, cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {cluster_id!r} not found", False)
    if not check_target_visible(cluster, target):
        raise _err(404, "TARGET_NOT_FOUND", f"target {target!r} not found", False)
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            doc = await adapter.get_document(target, doc_id)
    except TargetNotFoundError as exc:
        raise _err(404, "TARGET_NOT_FOUND", f"target {exc.target!r} not found", False) from exc
    except TargetsForbiddenError as exc:
        raise _err(403, "TARGETS_FORBIDDEN", str(exc), False) from exc
    except (ClusterUnreachable, ClusterUnreachableError) as exc:
        raise _err(503, "CLUSTER_UNREACHABLE", str(exc), True) from exc
    if doc is None:
        raise _err(
            404,
            "DOCUMENT_NOT_FOUND",
            f"document {doc_id!r} not found in {target!r}",
            False,
        )
    logger.info(
        "documents.get_requested",
        cluster_id=cluster_id,
        target=target,
        doc_id=doc_id,
        status="ok",
    )
    return doc
