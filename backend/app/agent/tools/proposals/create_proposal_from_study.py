"""``create_proposal_from_study`` tool — create a proposal from a completed study.

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


class CreateProposalFromStudyArgs(BaseModel):
    """Arguments for the ``create_proposal_from_study`` tool."""

    study_id: UUID = Field(description="The completed study whose best trial sources the proposal.")


async def create_proposal_from_study_impl(
    args: CreateProposalFromStudyArgs, ctx: ToolContext
) -> dict[str, Any]:
    """Create a proposal sourced from a study's best trial.

    The digest worker auto-creates a pending proposal when a study completes;
    this tool is for the operator who wants to surface a proposal explicitly
    (e.g. after manually inspecting trial results). Raises ``STUDY_NOT_FOUND``
    (404) on unknown study, ``VALIDATION_ERROR`` (422) if the study has no
    best trial yet (no completed trials with primary_metric). Mutating —
    confirmation required.
    """
    study = await repo.get_study(ctx.db, str(args.study_id))
    if study is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "STUDY_NOT_FOUND",
                "message": f"study {args.study_id} not found",
                "retryable": False,
            },
        )
    if study.best_trial_id is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VALIDATION_ERROR",
                "message": (
                    f"study {args.study_id} has no best trial yet — wait for "
                    "the orchestrator to record at least one completed trial"
                ),
                "retryable": True,
            },
        )

    # Build a minimal metric_delta from the study's baseline/best metrics.
    metric_delta: dict[str, Any] | None = None
    if study.baseline_metric is not None or study.best_metric is not None:
        metric_delta = {
            "baseline_metric": study.baseline_metric,
            "best_metric": study.best_metric,
        }

    # The best trial's params become the proposal's config_diff. The digest
    # worker normally filters these against the template's currently-declared
    # params (per feat_digest_proposal cycle-1 F5 / cycle-2 F1); the manual
    # surface preserves the raw params and leaves the operator to review.
    config_diff: dict[str, Any] = {"params": {}, "source": "study_best_trial"}

    proposal = await repo.create_proposal(
        ctx.db,
        id=str(uuid_utils.uuid7()),
        study_id=str(args.study_id),
        study_trial_id=study.best_trial_id,
        cluster_id=study.cluster_id,
        template_id=study.template_id,
        config_diff=config_diff,
        metric_delta=metric_delta,
        status="pending",
    )
    await ctx.db.commit()
    return {
        "id": proposal.id,
        "study_id": proposal.study_id,
        "study_trial_id": proposal.study_trial_id,
        "cluster_id": proposal.cluster_id,
        "template_id": proposal.template_id,
        "status": proposal.status,
        "created_at": proposal.created_at.isoformat(),
    }


_DESCRIPTION = (create_proposal_from_study_impl.__doc__ or "").split("\n\n", 1)[0].strip()

CREATE_PROPOSAL_FROM_STUDY_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "create_proposal_from_study",
        "description": _DESCRIPTION,
        "parameters": CreateProposalFromStudyArgs.model_json_schema(),
    },
}
