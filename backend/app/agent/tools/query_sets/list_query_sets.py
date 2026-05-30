# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``list_query_sets`` tool."""

from __future__ import annotations

from typing import Any

from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel

from backend.app.agent.context import ToolContext
from backend.app.db.repo import query_set as query_set_repo


class ListQuerySetsArgs(BaseModel):
    """Arguments for the ``list_query_sets`` tool."""


async def list_query_sets_impl(args: ListQuerySetsArgs, ctx: ToolContext) -> dict[str, Any]:
    """List every query set (id, name, cluster_id), newest first.

    Returns a small per-row summary; use ``get_query_set`` (not part of the MVP1
    tool inventory) or the relevant judgment-list / study tools to drill in.
    """
    rows = await query_set_repo.list_query_sets(ctx.db, limit=200)
    return {
        "query_sets": [
            {
                "id": r.id,
                "name": r.name,
                "cluster_id": r.cluster_id,
            }
            for r in rows
        ],
    }


_DESCRIPTION = (list_query_sets_impl.__doc__ or "").split("\n\n", 1)[0].strip()

LIST_QUERY_SETS_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "list_query_sets",
        "description": _DESCRIPTION,
        "parameters": ListQuerySetsArgs.model_json_schema(),
    },
}
