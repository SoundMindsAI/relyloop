# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``generate_judgments_from_ubi`` tool (feat_ubi_judgments Story 3.4 / FR-6).

Mirrors ``generate_judgments_llm`` for the UBI path. Routes through the
shared :func:`backend.app.services.agent_judgments_dispatch.start_ubi_judgment_generation`
dispatcher — same preflight runs as the
``POST /api/v1/judgments/generate-from-ubi`` endpoint.

MUTATING tool — the orchestrator's confirmation guard requires
affirmative user message before dispatch (per ``feat_chat_agent`` §19
Decision log; UBI lists are equivalent to LLM lists in terms of
operator commitment + side-effects on the operator's data).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, Field, model_validator

from backend.app.agent.context import ToolContext
from backend.app.api.v1.schemas import (
    UbiConverterKind,
    UbiMappingStrategyWire,
)
from backend.app.services.agent_judgments_dispatch import (
    UbiJudgmentGenerationRequest,
    start_ubi_judgment_generation,
)


class GenerateJudgmentsFromUbiArgs(BaseModel):
    """Arguments for the ``generate_judgments_from_ubi`` tool.

    Mirrors :class:`backend.app.api.v1.schemas.CreateJudgmentListFromUbiRequest`
    field-for-field; the same conditional validator + the same
    dispatcher run both paths.
    """

    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: UUID
    cluster_id: UUID
    target: str = Field(min_length=1, max_length=256)
    since: datetime
    until: datetime | None = None
    converter: UbiConverterKind
    converter_config: dict[str, Any] | None = None
    llm_fill_threshold: int | None = Field(default=20, ge=1)
    min_impressions_threshold: int | None = Field(default=100, ge=1)
    mapping_strategy: UbiMappingStrategyWire = "reject"
    current_template_id: UUID | None = None
    rubric: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_hybrid_conditional(self) -> GenerateJudgmentsFromUbiArgs:
        is_hybrid = self.converter == "hybrid_ubi_llm"
        has_template = self.current_template_id is not None
        has_rubric = self.rubric is not None
        if is_hybrid and not (has_template and has_rubric):
            raise ValueError(
                "current_template_id and rubric are REQUIRED when converter == 'hybrid_ubi_llm'"
            )
        if not is_hybrid and (has_template or has_rubric):
            raise ValueError(
                "current_template_id and rubric MUST be null for non-hybrid converters"
            )
        return self


async def generate_judgments_from_ubi_impl(
    args: GenerateJudgmentsFromUbiArgs, ctx: ToolContext
) -> dict[str, Any]:
    """Start a UBI-derived judgment generation job; return the new judgment_list_id.

    The full preflight (FK resolve, consistency, UBI_NOT_ENABLED probe,
    window validity + 90-day cap, sync UBI_INSUFFICIENT_DATA gate,
    hybrid-only LLM preflight, oversize) runs server-side via the
    shared dispatch helper — same checks the
    ``POST /api/v1/judgments/generate-from-ubi`` endpoint runs.
    MUTATING — confirmation required.
    """
    result = await start_ubi_judgment_generation(
        db=ctx.db,
        redis=ctx.redis,
        arq_pool=ctx.arq_pool,
        settings=ctx.settings,
        req=UbiJudgmentGenerationRequest(
            name=args.name,
            description=args.description,
            query_set_id=str(args.query_set_id),
            cluster_id=str(args.cluster_id),
            target=args.target,
            since=args.since,
            until=args.until,
            converter=args.converter,
            converter_config=args.converter_config,
            llm_fill_threshold=args.llm_fill_threshold,
            min_impressions_threshold=args.min_impressions_threshold,
            mapping_strategy=args.mapping_strategy,
            current_template_id=(
                str(args.current_template_id) if args.current_template_id is not None else None
            ),
            rubric=args.rubric,
        ),
    )
    return {
        "judgment_list_id": result.judgment_list_id,
        "status": result.status,
    }


_DESCRIPTION = (generate_judgments_from_ubi_impl.__doc__ or "").split("\n\n", 1)[0].strip()

GENERATE_JUDGMENTS_FROM_UBI_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "generate_judgments_from_ubi",
        "description": _DESCRIPTION,
        "parameters": GenerateJudgmentsFromUbiArgs.model_json_schema(),
    },
}
