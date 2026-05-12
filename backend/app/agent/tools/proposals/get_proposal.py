"""``get_proposal`` tool — return one proposal's full detail."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db import repo


class GetProposalArgs(BaseModel):
    """Arguments for the ``get_proposal`` tool."""

    proposal_id: UUID = Field(description="The proposal's UUIDv7.")


async def get_proposal_impl(args: GetProposalArgs, ctx: ToolContext) -> dict[str, Any]:
    """Return one proposal's full detail (config_diff, metric_delta, PR state).

    Raises ``PROPOSAL_NOT_FOUND`` (404) if the proposal id is unknown.
    """
    proposal = await repo.get_proposal(ctx.db, str(args.proposal_id))
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "PROPOSAL_NOT_FOUND",
                "message": f"proposal {args.proposal_id} not found",
                "retryable": False,
            },
        )
    return {
        "id": proposal.id,
        "study_id": proposal.study_id,
        "study_trial_id": proposal.study_trial_id,
        "cluster_id": proposal.cluster_id,
        "template_id": proposal.template_id,
        "config_diff": proposal.config_diff,
        "metric_delta": proposal.metric_delta,
        "status": proposal.status,
        "pr_url": proposal.pr_url,
        "pr_state": proposal.pr_state,
        "pr_open_error": proposal.pr_open_error,
        "created_at": proposal.created_at.isoformat(),
    }


_DESCRIPTION = (get_proposal_impl.__doc__ or "").split("\n\n", 1)[0].strip()

GET_PROPOSAL_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "get_proposal",
        "description": _DESCRIPTION,
        "parameters": GetProposalArgs.model_json_schema(),
    },
}
