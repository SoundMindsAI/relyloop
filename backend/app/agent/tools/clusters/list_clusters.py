# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``list_clusters`` tool — return every active cluster (id, name, engine, env)."""

from __future__ import annotations

from typing import Any

from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel

from backend.app.agent.context import ToolContext
from backend.app.db.repo import cluster as cluster_repo


class ListClustersArgs(BaseModel):
    """No arguments — empty object satisfies OpenAI's JSON-Schema requirement."""


async def list_clusters_impl(args: ListClustersArgs, ctx: ToolContext) -> dict[str, Any]:
    """List every active cluster registered in the system.

    Returns a small summary per cluster (id, name, engine_type, environment) so
    the agent can pick one to drill into via ``get_cluster`` or ``get_schema``.
    Soft-deleted clusters are excluded.
    """
    rows = await cluster_repo.list_clusters(ctx.db, limit=200)
    return {
        "clusters": [
            {
                "id": c.id,
                "name": c.name,
                "engine_type": c.engine_type,
                "environment": c.environment,
            }
            for c in rows
        ],
    }


_DESCRIPTION = (list_clusters_impl.__doc__ or "").split("\n\n", 1)[0].strip()

LIST_CLUSTERS_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "list_clusters",
        "description": _DESCRIPTION,
        "parameters": ListClustersArgs.model_json_schema(),
    },
}
