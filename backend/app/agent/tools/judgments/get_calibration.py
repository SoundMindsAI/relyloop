"""``get_calibration`` tool — return the LLM-vs-human calibration for a list."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.db.repo import judgment_list as judgment_list_repo


class GetCalibrationArgs(BaseModel):
    """Arguments for the ``get_calibration`` tool."""

    judgment_list_id: UUID = Field(description="The judgment list whose calibration to fetch.")


async def get_calibration_impl(args: GetCalibrationArgs, ctx: ToolContext) -> dict[str, Any]:
    """Return the calibration JSONB stored on a judgment list (Cohen's + weighted kappa).

    Returns ``{"calibration": null}`` when calibration hasn't been computed yet
    (the operator runs ``POST /judgment-lists/{id}/calibration`` to populate it
    from human samples). Raises ``JUDGMENT_LIST_NOT_FOUND`` (404) if unknown.
    """
    row = await judgment_list_repo.get_judgment_list(ctx.db, str(args.judgment_list_id))
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "JUDGMENT_LIST_NOT_FOUND",
                "message": f"judgment list {args.judgment_list_id} not found",
                "retryable": False,
            },
        )
    return {
        "judgment_list_id": row.id,
        "calibration": row.calibration,
    }


_DESCRIPTION = (get_calibration_impl.__doc__ or "").split("\n\n", 1)[0].strip()

GET_CALIBRATION_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "get_calibration",
        "description": _DESCRIPTION,
        "parameters": GetCalibrationArgs.model_json_schema(),
    },
}
