# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``get_cluster`` tool — return one cluster's full detail by id."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db.repo import cluster as cluster_repo


class GetClusterArgs(BaseModel):
    """Arguments for the ``get_cluster`` tool."""

    cluster_id: UUID = Field(
        description="The cluster's UUIDv7 (string form like '01987b...').",
    )


async def get_cluster_impl(args: GetClusterArgs, ctx: ToolContext) -> dict[str, Any]:
    """Return one cluster's full detail (name, engine_type, environment, base_url).

    Raises ``CLUSTER_NOT_FOUND`` (404) if ``cluster_id`` does not correspond to
    an active cluster (soft-deleted rows are treated as missing).
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
    return {
        "id": cluster.id,
        "name": cluster.name,
        "engine_type": cluster.engine_type,
        "environment": cluster.environment,
        "base_url": cluster.base_url,
    }


_DESCRIPTION = (get_cluster_impl.__doc__ or "").split("\n\n", 1)[0].strip()

GET_CLUSTER_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "get_cluster",
        "description": _DESCRIPTION,
        "parameters": GetClusterArgs.model_json_schema(),
    },
}
