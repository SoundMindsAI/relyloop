# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``create_proposal_manual`` tool — create a hand-crafted proposal.

This is a MUTATING tool (per spec FR-5 + §19 Decision log) — the orchestrator's
confirmation guard requires an affirmative user message before dispatch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import uuid_utils
from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db import repo


class CreateProposalManualArgs(BaseModel):
    """Arguments for the ``create_proposal_manual`` tool.

    Mirrors :class:`backend.app.api.v1.schemas.CreateProposalRequest`.
    """

    cluster_id: UUID = Field(description="Cluster the proposal targets.")
    template_id: UUID = Field(description="Template the config_diff applies to.")
    config_diff: dict[str, Any] = Field(
        description="JSON object describing the param changes to apply.",
    )
    metric_delta: dict[str, Any] | None = Field(
        default=None,
        description="Optional metric delta object (baseline/best metric, etc.).",
    )


async def create_proposal_manual_impl(
    args: CreateProposalManualArgs, ctx: ToolContext
) -> dict[str, Any]:
    """Create a hand-crafted proposal not tied to any study.

    ``study_id`` and ``study_trial_id`` are set to NULL. Validates FK targets
    (cluster + template exist) before insert. Raises ``CLUSTER_NOT_FOUND``
    (404) or ``TEMPLATE_NOT_FOUND`` (404) on FK miss. Mutating —
    confirmation required.
    """
    cluster = await repo.get_cluster(ctx.db, str(args.cluster_id))
    if cluster is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "CLUSTER_NOT_FOUND",
                "message": f"cluster {args.cluster_id} not found",
                "retryable": False,
            },
        )
    template = await repo.get_query_template(ctx.db, str(args.template_id))
    if template is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "TEMPLATE_NOT_FOUND",
                "message": f"template {args.template_id} not found",
                "retryable": False,
            },
        )
    proposal = await repo.create_proposal(
        ctx.db,
        id=str(uuid_utils.uuid7()),
        study_id=None,
        study_trial_id=None,
        cluster_id=str(args.cluster_id),
        template_id=str(args.template_id),
        config_diff=args.config_diff,
        metric_delta=args.metric_delta,
        status="pending",
    )
    await ctx.db.commit()
    return {
        "id": proposal.id,
        "cluster_id": proposal.cluster_id,
        "template_id": proposal.template_id,
        "status": proposal.status,
        "created_at": proposal.created_at.isoformat(),
    }


_DESCRIPTION = (create_proposal_manual_impl.__doc__ or "").split("\n\n", 1)[0].strip()

CREATE_PROPOSAL_MANUAL_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "create_proposal_manual",
        "description": _DESCRIPTION,
        "parameters": CreateProposalManualArgs.model_json_schema(),
    },
}
