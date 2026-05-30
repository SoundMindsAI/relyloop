# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``get_schema`` tool — introspect an index/collection's field schema."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    TargetNotFoundError,
)
from backend.app.agent.context import ToolContext
from backend.app.db.repo import cluster as cluster_repo
from backend.app.services import cluster as cluster_svc


class GetSchemaArgs(BaseModel):
    """Arguments for the ``get_schema`` tool."""

    cluster_id: UUID = Field(
        description="The cluster's UUIDv7.",
    )
    target: str = Field(
        min_length=1,
        max_length=256,
        description="Index or collection name on the cluster (e.g. 'products').",
    )


async def get_schema_impl(args: GetSchemaArgs, ctx: ToolContext) -> dict[str, Any]:
    """Return the field schema (name + type per field) for a target on a cluster.

    Raises ``CLUSTER_NOT_FOUND`` (404) if the cluster id is unknown,
    ``TARGET_NOT_FOUND`` (404) if the target index/collection does not exist on
    the cluster, or ``CLUSTER_UNREACHABLE`` (503) if the cluster cannot be
    reached. The result mirrors the ``GET /api/v1/clusters/{id}/schema``
    endpoint shape — ``{name, fields: [{name, type, analyzer, doc_count}, ...]}``.
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
            schema = await adapter.get_schema(args.target)
    except TargetNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "TARGET_NOT_FOUND",
                "message": f"target {exc.target!r} not found",
                "retryable": False,
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
    return schema.model_dump()


_DESCRIPTION = (get_schema_impl.__doc__ or "").split("\n\n", 1)[0].strip()

GET_SCHEMA_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "get_schema",
        "description": _DESCRIPTION,
        "parameters": GetSchemaArgs.model_json_schema(),
    },
}
