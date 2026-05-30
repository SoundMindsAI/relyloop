# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``get_study`` tool — return one study's full detail (with trial summary)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db import repo


class GetStudyArgs(BaseModel):
    """Arguments for the ``get_study`` tool."""

    study_id: UUID = Field(description="The study's UUIDv7.")


async def get_study_impl(args: GetStudyArgs, ctx: ToolContext) -> dict[str, Any]:
    """Return one study's detail (status, baseline/best metrics, trial summary).

    Raises ``STUDY_NOT_FOUND`` (404) if the study id is unknown.
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
    summary = await repo.aggregate_trials_summary(ctx.db, study.id)
    return {
        "id": study.id,
        "name": study.name,
        "cluster_id": study.cluster_id,
        "target": study.target,
        "template_id": study.template_id,
        "query_set_id": study.query_set_id,
        "judgment_list_id": study.judgment_list_id,
        "status": study.status,
        "failed_reason": study.failed_reason,
        "baseline_metric": study.baseline_metric,
        "best_metric": study.best_metric,
        "best_trial_id": study.best_trial_id,
        "trials_summary": {
            "total": summary.total,
            "complete": summary.complete,
            "failed": summary.failed,
            "pruned": summary.pruned,
            "best_primary_metric": summary.best_primary_metric,
        },
    }


_DESCRIPTION = (get_study_impl.__doc__ or "").split("\n\n", 1)[0].strip()

GET_STUDY_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "get_study",
        "description": _DESCRIPTION,
        "parameters": GetStudyArgs.model_json_schema(),
    },
}
