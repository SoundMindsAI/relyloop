"""Cluster CRUD + schema + run_query router (Stories 3.2, 3.3, 3.4).

Endpoints (per spec §7.1, FR-5/FR-4/FR-6):

* ``POST   /api/v1/clusters``                       — register
* ``GET    /api/v1/clusters``                       — list (cursor-paginated)
* ``GET    /api/v1/clusters/{cluster_id}``          — detail
* ``DELETE /api/v1/clusters/{cluster_id}``          — soft-delete
* ``GET    /api/v1/clusters/{cluster_id}/schema``   — schema introspection
* ``POST   /api/v1/clusters/{cluster_id}/run_query``— ad-hoc DSL execution

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

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
    TargetNotFoundError,
)
from backend.app.adapters.protocol import HealthStatus
from backend.app.adapters.protocol import Schema as AdapterSchema
from backend.app.api.health import get_redis_client
from backend.app.api.v1.schemas import (
    ClusterDetail,
    ClusterListResponse,
    ClusterSortKey,
    ClusterSummary,
    CreateClusterRequest,
    EngineTypeWire,
    Environment,
    HealthCheckResult,
    RunQueryHit,
    RunQueryRequest,
    RunQueryResponse,
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
from backend.app.services.cluster import (
    AuthKindNotSupported,
    ClusterNameTaken,
    ClusterUnreachable,
    EngineTypeNotSupported,
    dispatch_run_query,
)

router = APIRouter()

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


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    """Build the spec §7.5 error envelope as an HTTPException detail dict."""
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


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
