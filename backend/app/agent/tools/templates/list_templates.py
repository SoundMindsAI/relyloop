# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``list_templates`` tool — list query templates, optionally filtered by engine."""

from __future__ import annotations

from typing import Any, Literal

from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db.repo import query_template as query_template_repo


class ListTemplatesArgs(BaseModel):
    """Arguments for the ``list_templates`` tool."""

    engine_type: Literal["elasticsearch", "opensearch"] | None = Field(
        default=None,
        description=(
            "Restrict results to templates targeting this engine. Omit to list "
            "templates across both engines."
        ),
    )


async def list_templates_impl(args: ListTemplatesArgs, ctx: ToolContext) -> dict[str, Any]:
    """List query templates (id, name, engine_type, version), newest first.

    The ``engine_type`` argument optionally filters by engine. The result mirrors
    the ``GET /api/v1/templates`` summary shape — only the headline fields, not
    the full Jinja body. Use ``get_template`` to retrieve a single template's
    body + declared params.
    """
    # The repo paginates at 200 per page; MVP1 expects a small total template
    # count so a single page is sufficient. Engine-type filter is applied here
    # rather than in the repo: the existing repo signature is shared with the
    # ``GET /api/v1/templates`` endpoint, which has no engine filter today.
    rows = await query_template_repo.list_query_templates(ctx.db, limit=200)
    if args.engine_type is not None:
        rows = [t for t in rows if t.engine_type == args.engine_type]
    return {
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "engine_type": t.engine_type,
                "version": t.version,
            }
            for t in rows
        ],
    }


_DESCRIPTION = (list_templates_impl.__doc__ or "").split("\n\n", 1)[0].strip()

LIST_TEMPLATES_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "list_templates",
        "description": _DESCRIPTION,
        "parameters": ListTemplatesArgs.model_json_schema(),
    },
}
