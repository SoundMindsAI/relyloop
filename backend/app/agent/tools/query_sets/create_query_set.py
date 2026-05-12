"""``create_query_set`` tool — create an empty query set under a cluster."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import uuid_utils
from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from backend.app.agent.context import ToolContext
from backend.app.db.repo import cluster as cluster_repo
from backend.app.db.repo import query_set as query_set_repo


class CreateQuerySetArgs(BaseModel):
    """Arguments for the ``create_query_set`` tool."""

    name: str = Field(min_length=1, max_length=256, description="Operator-supplied name.")
    description: str | None = Field(default=None, max_length=2000)
    cluster_id: UUID = Field(description="Cluster the new query set belongs to.")


async def create_query_set_impl(args: CreateQuerySetArgs, ctx: ToolContext) -> dict[str, Any]:
    """Create an empty query set under a cluster.

    The result row contains an ``id`` the operator can hand to
    ``import_queries_from_csv`` (or the UI's bulk-add) to populate the set.
    Empty query sets are intentionally cheap to create — this tool is NOT on
    the spec FR-5 confirmation list. Raises ``CLUSTER_NOT_FOUND`` (404) if the
    cluster id is unknown, ``QUERY_SET_NAME_TAKEN`` (409) on name collision.
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
        row = await query_set_repo.create_query_set(
            ctx.db,
            id=str(uuid_utils.uuid7()),
            name=args.name,
            description=args.description,
            cluster_id=str(args.cluster_id),
        )
        await ctx.db.commit()
    except IntegrityError as exc:
        await ctx.db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "QUERY_SET_NAME_TAKEN",
                "message": f"query set name {args.name!r} already exists",
                "retryable": False,
            },
        ) from exc
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "cluster_id": row.cluster_id,
    }


_DESCRIPTION = (create_query_set_impl.__doc__ or "").split("\n\n", 1)[0].strip()

CREATE_QUERY_SET_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "create_query_set",
        "description": _DESCRIPTION,
        "parameters": CreateQuerySetArgs.model_json_schema(),
    },
}
