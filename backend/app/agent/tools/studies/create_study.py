"""``create_study`` tool — create + enqueue a new optimization study.

This is a MUTATING tool (per spec FR-5 + §19 Decision log) — the orchestrator's
confirmation guard requires an affirmative user message before dispatch.
"""

from __future__ import annotations

from typing import Any

import uuid_utils
from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import ValidationError

from backend.app.agent.context import ToolContext
from backend.app.api.v1.schemas import CreateStudyRequest
from backend.app.db import repo
from backend.app.domain.study.search_space import SearchSpace

# Re-export so the registry's TOOL_ARG_MODELS table can reference it.
CreateStudyArgs = CreateStudyRequest


async def create_study_impl(args: CreateStudyArgs, ctx: ToolContext) -> dict[str, Any]:
    """Create + enqueue a new optimization study and return the new study_id.

    Mirrors the preflight + INSERT + Arq enqueue of
    ``POST /api/v1/studies`` (search_space validation, FK resolution,
    judgment_list ↔ query_set consistency, UUIDv7 + INSERT + commit, best-effort
    enqueue). Same error codes (``INVALID_SEARCH_SPACE`` 400, ``CLUSTER_NOT_FOUND``,
    ``TEMPLATE_NOT_FOUND``, ``QUERY_SET_NOT_FOUND``, ``JUDGMENT_LIST_NOT_FOUND``
    404, ``VALIDATION_ERROR`` 422). Mutating — confirmation required.
    """
    # 1. SearchSpace validation.
    try:
        SearchSpace.model_validate(args.search_space)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_SEARCH_SPACE",
                "message": str(exc),
                "retryable": False,
            },
        ) from exc

    # 2. FK resolution.
    cluster = await repo.get_cluster(ctx.db, args.cluster_id)
    if cluster is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "CLUSTER_NOT_FOUND",
                "message": f"cluster {args.cluster_id} not found",
                "retryable": False,
            },
        )
    template = await repo.get_query_template(ctx.db, args.template_id)
    if template is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "TEMPLATE_NOT_FOUND",
                "message": f"template {args.template_id} not found",
                "retryable": False,
            },
        )
    query_set = await repo.get_query_set(ctx.db, args.query_set_id)
    if query_set is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "QUERY_SET_NOT_FOUND",
                "message": f"query set {args.query_set_id} not found",
                "retryable": False,
            },
        )
    judgment_list = await repo.get_judgment_list(ctx.db, args.judgment_list_id)
    if judgment_list is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "JUDGMENT_LIST_NOT_FOUND",
                "message": f"judgment list {args.judgment_list_id} not found",
                "retryable": False,
            },
        )

    # 3. judgment_list ↔ query_set consistency.
    if judgment_list.query_set_id != args.query_set_id:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VALIDATION_ERROR",
                "message": "judgment_list query_set_id does not match study query_set_id",
                "retryable": False,
            },
        )

    # 4. Serialize config (parity with router).
    config_payload = args.config.model_dump(exclude_none=True, exclude_unset=True)

    # 5. UUIDv7 + INSERT + commit.
    study_id = str(uuid_utils.uuid7())
    row = await repo.create_study(
        ctx.db,
        id=study_id,
        name=args.name,
        cluster_id=args.cluster_id,
        target=args.target,
        template_id=args.template_id,
        query_set_id=args.query_set_id,
        judgment_list_id=args.judgment_list_id,
        search_space=args.search_space,
        objective=args.objective.model_dump(),
        config=config_payload,
        status="queued",
        optuna_study_name=study_id,
    )
    await ctx.db.commit()

    # 6. Best-effort Arq enqueue.
    if ctx.arq_pool is not None:
        await ctx.arq_pool.enqueue_job("start_study", study_id)

    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "cluster_id": row.cluster_id,
        "target": row.target,
        "template_id": row.template_id,
        "query_set_id": row.query_set_id,
        "judgment_list_id": row.judgment_list_id,
    }


_DESCRIPTION = (create_study_impl.__doc__ or "").split("\n\n", 1)[0].strip()

CREATE_STUDY_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "create_study",
        "description": _DESCRIPTION,
        "parameters": CreateStudyArgs.model_json_schema(),
    },
}
