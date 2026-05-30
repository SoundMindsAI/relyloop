# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``open_pr`` tool — enqueue the GitHub PR worker for an approved proposal.

This is a MUTATING tool (per spec FR-5 + §19 Decision log) — the orchestrator's
confirmation guard requires an affirmative user message before dispatch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.services import agent_proposals_dispatch


class OpenPrArgs(BaseModel):
    """Arguments for the ``open_pr`` tool."""

    proposal_id: UUID = Field(description="The proposal whose PR to open.")


async def open_pr_impl(args: OpenPrArgs, ctx: ToolContext) -> dict[str, Any]:
    """Enqueue the GitHub PR worker for an operator-approved proposal.

    The same preflight runs as ``POST /api/v1/proposals/{id}/open_pr`` (proposal
    exists + pending + cluster has config_repo + PAT readable + Arq pool
    available). Errors flow through the spec envelope:
    ``PROPOSAL_NOT_FOUND`` (404), ``INVALID_STATE_TRANSITION`` (409),
    ``CLUSTER_HAS_NO_CONFIG_REPO`` (422), ``GITHUB_NOT_CONFIGURED`` (503),
    ``QUEUE_UNAVAILABLE`` (503). Mutating — confirmation required.
    """
    result = await agent_proposals_dispatch.open_pr(
        db=ctx.db,
        arq_pool=ctx.arq_pool,
        proposal_id=str(args.proposal_id),
    )
    return {
        "proposal_id": result.proposal_id,
        "status": result.status,
        "message": result.message,
    }


_DESCRIPTION = (open_pr_impl.__doc__ or "").split("\n\n", 1)[0].strip()

OPEN_PR_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "open_pr",
        "description": _DESCRIPTION,
        "parameters": OpenPrArgs.model_json_schema(),
    },
}
