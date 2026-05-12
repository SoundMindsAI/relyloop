"""``run_query`` tool — execute one ad-hoc Query DSL fragment against a cluster."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
)
from backend.app.agent.context import ToolContext
from backend.app.db.repo import cluster as cluster_repo
from backend.app.services import cluster as cluster_svc

DEFAULT_TIMEOUT_S = 5.0
MAX_TIMEOUT_S = 30.0
DEFAULT_TOP_K = 10
MAX_TOP_K = 100


class RunQueryArgs(BaseModel):
    """Arguments for the ``run_query`` tool."""

    cluster_id: UUID = Field(description="Cluster to execute against.")
    target: str = Field(min_length=1, max_length=256, description="Index/collection name.")
    query_dsl: dict[str, Any] = Field(
        description=(
            "Engine-native query DSL (the value of ES/OpenSearch's `query:` key, "
            'e.g. `{"match": {"title": "running shoes"}}`).'
        ),
    )
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S, ge=1.0, le=MAX_TIMEOUT_S)


async def run_query_impl(args: RunQueryArgs, ctx: ToolContext) -> dict[str, Any]:
    """Execute one ad-hoc query against a cluster and return the top hits.

    No mutation. Mirrors ``POST /api/v1/clusters/{id}/run_query`` — same
    timeouts, same error codes (``CLUSTER_NOT_FOUND`` 404, ``INVALID_QUERY_DSL``
    400, ``QUERY_TIMEOUT`` 504, ``CLUSTER_UNREACHABLE`` 503). Use this to
    sanity-check a query before wiring it into a study or to inspect what an
    engine returns for a particular template.
    """
    cluster = await cluster_repo.get_cluster(ctx.db, str(args.cluster_id))
    if cluster is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "CLUSTER_NOT_FOUND",
                "message": f"cluster {args.cluster_id} not found",
                "retryable": False,
            },
        )
    try:
        async with cluster_svc.acquire_adapter(cluster) as adapter:
            hits = await cluster_svc.dispatch_run_query(
                adapter,
                target=args.target,
                query_dsl=args.query_dsl,
                top_k=args.top_k,
                timeout_s=args.timeout_s,
            )
    except InvalidQueryDSLError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_QUERY_DSL",
                "message": str(exc),
                "retryable": False,
            },
        ) from exc
    except QueryTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error_code": "QUERY_TIMEOUT",
                "message": str(exc),
                "retryable": True,
            },
        ) from exc
    except (cluster_svc.ClusterUnreachable, ClusterUnreachableError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "CLUSTER_UNREACHABLE",
                "message": str(exc),
                "retryable": True,
            },
        ) from exc
    return {
        "hits": [{"doc_id": h.doc_id, "score": h.score, "source": h.source} for h in hits],
    }


_DESCRIPTION = (run_query_impl.__doc__ or "").split("\n\n", 1)[0].strip()

RUN_QUERY_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "run_query",
        "description": _DESCRIPTION,
        "parameters": RunQueryArgs.model_json_schema(),
    },
}
