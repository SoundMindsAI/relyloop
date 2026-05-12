"""``cancel_study`` tool — request cancellation of a queued/running study.

This is a MUTATING tool (per spec FR-5 + §19 Decision log) — the orchestrator's
confirmation guard requires an affirmative user message before dispatch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.services import study_state


class CancelStudyArgs(BaseModel):
    """Arguments for the ``cancel_study`` tool."""

    study_id: UUID = Field(description="The study's UUIDv7.")


async def cancel_study_impl(args: CancelStudyArgs, ctx: ToolContext) -> dict[str, Any]:
    """Cancel a queued or running study; the orchestrator drains in-flight trials.

    Raises ``STUDY_NOT_FOUND`` (404) if the study id is unknown,
    ``INVALID_STATE_TRANSITION`` (409) if the study has already terminated.
    Mutating — confirmation required.
    """
    try:
        row = await study_state.cancel_study(ctx.db, str(args.study_id))
        await ctx.db.commit()
    except study_state.StudyNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "STUDY_NOT_FOUND",
                "message": f"study {args.study_id} not found",
                "retryable": False,
            },
        ) from exc
    except study_state.InvalidStateTransition as exc:
        await ctx.db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "INVALID_STATE_TRANSITION",
                "message": str(exc),
                "retryable": False,
            },
        ) from exc
    return {
        "id": row.id,
        "status": row.status,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


_DESCRIPTION = (cancel_study_impl.__doc__ or "").split("\n\n", 1)[0].strip()

CANCEL_STUDY_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "cancel_study",
        "description": _DESCRIPTION,
        "parameters": CancelStudyArgs.model_json_schema(),
    },
}
