# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``get_template`` tool — return one query template's full detail by id."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db.repo import query_template as query_template_repo


class GetTemplateArgs(BaseModel):
    """Arguments for the ``get_template`` tool."""

    template_id: UUID = Field(
        description="The query template's UUIDv7.",
    )


async def get_template_impl(args: GetTemplateArgs, ctx: ToolContext) -> dict[str, Any]:
    """Return a query template's full detail (name, engine_type, body, declared_params).

    Raises ``TEMPLATE_NOT_FOUND`` (404) if the template id is unknown.
    """
    template = await query_template_repo.get_query_template(ctx.db, str(args.template_id))
    if template is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "TEMPLATE_NOT_FOUND",
                "message": f"template {args.template_id} not found",
                "retryable": False,
            },
        )
    return {
        "id": template.id,
        "name": template.name,
        "engine_type": template.engine_type,
        "version": template.version,
        "body": template.body,
        "declared_params": template.declared_params,
        "parent_id": template.parent_id,
    }


_DESCRIPTION = (get_template_impl.__doc__ or "").split("\n\n", 1)[0].strip()

GET_TEMPLATE_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "get_template",
        "description": _DESCRIPTION,
        "parameters": GetTemplateArgs.model_json_schema(),
    },
}
