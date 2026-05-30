# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``list_proposals`` tool — list proposals with optional status filter."""

from __future__ import annotations

from typing import Any, Literal

from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db import repo

# Values must match backend/app/db/repo/proposal.py ProposalStatusFilter
# (which mirrors the proposals.status CHECK constraint).
ProposalStatusFilterValue = Literal["pending", "pr_opened", "pr_merged", "rejected"]


class ListProposalsArgs(BaseModel):
    """Arguments for the ``list_proposals`` tool."""

    status: ProposalStatusFilterValue | None = Field(
        default=None,
        description="Restrict to proposals with this status. Omit to list across statuses.",
    )
    cluster_id: str | None = Field(
        default=None,
        max_length=36,
        description="Optional cluster id filter.",
    )


async def list_proposals_impl(args: ListProposalsArgs, ctx: ToolContext) -> dict[str, Any]:
    """List proposals (id, status, cluster_id, template_id), newest first.

    Returns a small per-row summary; use ``get_proposal`` for full detail.
    """
    rows = await repo.list_proposals_paginated(
        ctx.db,
        limit=200,
        status=args.status,
        cluster_id=args.cluster_id,
    )
    return {
        "proposals": [
            {
                "id": p.id,
                "study_id": p.study_id,
                "cluster_id": p.cluster_id,
                "template_id": p.template_id,
                "status": p.status,
                "pr_url": p.pr_url,
                "pr_state": p.pr_state,
                "created_at": p.created_at.isoformat(),
            }
            for p in rows
        ],
    }


_DESCRIPTION = (list_proposals_impl.__doc__ or "").split("\n\n", 1)[0].strip()

LIST_PROPOSALS_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "list_proposals",
        "description": _DESCRIPTION,
        "parameters": ListProposalsArgs.model_json_schema(),
    },
}
