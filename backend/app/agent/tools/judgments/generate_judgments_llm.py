# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``generate_judgments_llm`` tool — start an LLM-judgment generation job.

This is a MUTATING tool (per spec FR-5 + §19 Decision log) — the orchestrator's
confirmation guard requires an affirmative user message before dispatch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field

from backend.app.agent.context import ToolContext
from backend.app.services.agent_judgments_dispatch import (
    JudgmentGenerationRequest,
    start_judgment_generation,
)


class GenerateJudgmentsLLMArgs(BaseModel):
    """Arguments for the ``generate_judgments_llm`` tool.

    Mirrors :class:`backend.app.api.v1.schemas.CreateJudgmentListGenerateRequest`
    field-for-field — the same preflight runs in both paths via
    :func:`start_judgment_generation`.
    """

    name: str = Field(min_length=1, max_length=256, description="Operator-supplied list name.")
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: UUID = Field(description="Source queries.")
    cluster_id: UUID = Field(description="Cluster the judgments target.")
    target: str = Field(
        min_length=1, max_length=256, description="Index/collection to judge against."
    )
    current_template_id: UUID = Field(description="Query template used for retrieval.")
    rubric: str = Field(min_length=1, description="Free-form rubric text shown to the judge model.")


async def generate_judgments_llm_impl(
    args: GenerateJudgmentsLLMArgs, ctx: ToolContext
) -> dict[str, Any]:
    """Start an LLM-judgment generation job and return the new judgment_list_id.

    The full preflight (OpenAI configured, capability cache, model pricing,
    daily-budget peek, FK resolution, consistency, oversize) runs server-side
    via the shared dispatch helper — same checks the
    ``POST /api/v1/judgments/generate`` endpoint runs. Mutating — confirmation
    required.
    """
    result = await start_judgment_generation(
        db=ctx.db,
        redis=ctx.redis,
        arq_pool=ctx.arq_pool,
        settings=ctx.settings,
        req=JudgmentGenerationRequest(
            name=args.name,
            description=args.description,
            query_set_id=str(args.query_set_id),
            cluster_id=str(args.cluster_id),
            target=args.target,
            current_template_id=str(args.current_template_id),
            rubric=args.rubric,
        ),
    )
    return {
        "judgment_list_id": result.judgment_list_id,
        "status": result.status,
    }


_DESCRIPTION = (generate_judgments_llm_impl.__doc__ or "").split("\n\n", 1)[0].strip()

GENERATE_JUDGMENTS_LLM_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "generate_judgments_llm",
        "description": _DESCRIPTION,
        "parameters": GenerateJudgmentsLLMArgs.model_json_schema(),
    },
}
