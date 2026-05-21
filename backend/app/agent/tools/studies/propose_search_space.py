"""``propose_search_space`` tool — build a deterministic starter search space.

Read-only agent tool (NOT in :data:`backend.app.agent.confirmation.MUTATING_TOOL_NAMES`).
The orchestrator's system prompt directs the LLM to call this BEFORE
``create_study``; the returned ``search_space`` is passed verbatim into
``create_study.search_space`` so the bounds are grounded in the same
TS+Python parity-locked heuristic as the create-study wizard's auto-fill
(see :mod:`backend.app.domain.study.search_space_defaults`).

When the optional ``prior_study_id`` arg resolves to a study with a
``best_trial_id`` AND the templates match, the helper narrows each numeric
param's bounds ±50% (linear) or √2-bracket (log-uniform) around the prior
winner. Mismatched templates, missing trial rows, and out-of-bounds winners
degrade gracefully to the heuristic-only output with WARN logs (spec FR-3).

Telemetry (spec FR-6): emits ``agent.search_space_proposed`` tagged with
``ctx.conversation_id`` on every successful invocation; the sibling
``create_study`` impl emits ``agent.create_study.invoked``. Offline
correlation by ``conversation_id`` measures propose→create chain adherence.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel, ConfigDict, Field

from backend.app.agent.context import ToolContext
from backend.app.db import repo
from backend.app.domain.study.search_space import (
    InvalidSearchSpaceError,
    SearchSpace,
    estimate_cardinality,
)
from backend.app.domain.study.search_space_defaults import (
    build_starter_search_space,
    narrow_bounds_around_winner,
)

logger = logging.getLogger(__name__)


class ProposeSearchSpaceArgs(BaseModel):
    """Arguments for the ``propose_search_space`` tool.

    Strict — extra fields are rejected so a hallucinated LLM arg surfaces as a
    Pydantic ``ValidationError`` at the orchestrator's arg-validation step
    rather than being silently dropped.
    """

    model_config = ConfigDict(extra="forbid")

    template_id: UUID = Field(description="The template's UUIDv7 — the param universe.")
    cluster_id: UUID = Field(description="The cluster's UUIDv7 — validated to exist.")
    judgment_list_id: UUID | None = Field(
        default=None,
        description="Optional judgment list — v1 validates existence only (signature-only).",
    )
    prior_study_id: UUID | None = Field(
        default=None,
        description=(
            "Optional prior study — when its template matches, narrows bounds ±50% around its "
            "winning trial."
        ),
    )


async def propose_search_space_impl(  # noqa: PLR0915
    args: ProposeSearchSpaceArgs, ctx: ToolContext
) -> dict[str, Any]:
    """Build a deterministic, code-generated search_space for create_study.

    Returns a dict shaped ``{"search_space": {...}, "grounding": {...}}`` —
    pass ``result["search_space"]`` verbatim into ``create_study.search_space``.
    Read-only — no DB writes, no commit, no enqueue.

    Errors (per spec §7.5): ``TEMPLATE_NOT_FOUND`` 404, ``CLUSTER_NOT_FOUND`` 404,
    ``JUDGMENT_LIST_NOT_FOUND`` 404, ``STUDY_NOT_FOUND`` 404, ``INVALID_SEARCH_SPACE``
    400 (empty declared_params OR cap-aware overflow exhausted).
    """
    # 1. FK resolution.
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
    if args.judgment_list_id is not None:
        jlist = await repo.get_judgment_list(ctx.db, str(args.judgment_list_id))
        if jlist is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "JUDGMENT_LIST_NOT_FOUND",
                    "message": f"judgment list {args.judgment_list_id} not found",
                    "retryable": False,
                },
            )

    # 2. Build heuristic-only starter (spec FR-1).
    declared_params = template.declared_params or {}
    try:
        starter = build_starter_search_space(declared_params)
    except InvalidSearchSpaceError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_SEARCH_SPACE",
                "message": str(exc),
                "retryable": False,
            },
        ) from exc

    space: SearchSpace = starter.space
    cap_fallback_names: list[str] = list(starter.cap_aware_fallback_param_names)
    narrowed_names: list[str] = []
    prior_study_template_mismatch = False
    used_prior_study_id: str | None = None

    # 3. Optional prior-study narrowing (spec FR-3 with graceful degrade).
    if args.prior_study_id is not None:
        prior = await repo.get_study(ctx.db, str(args.prior_study_id))
        if prior is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "STUDY_NOT_FOUND",
                    "message": f"study {args.prior_study_id} not found",
                    "retryable": False,
                },
            )
        used_prior_study_id = str(prior.id)
        # Normalize both sides to str: Study.template_id is String(36) but Pydantic
        # UUID args round-trip through str() so the comparison is type-safe either way.
        if str(prior.template_id) != str(args.template_id):
            prior_study_template_mismatch = True
            logger.warning(
                "agent.propose_search_space.prior_template_mismatch "
                "conversation_id=%s prior_study_id=%s prior_template_id=%s "
                "requested_template_id=%s",
                ctx.conversation_id,
                used_prior_study_id,
                prior.template_id,
                args.template_id,
            )
        elif prior.best_trial_id is not None:
            trial = await repo.get_trial(ctx.db, prior.best_trial_id)
            if trial is None:
                logger.warning(
                    "agent.propose_search_space.missing_winner_trial "
                    "conversation_id=%s prior_study_id=%s best_trial_id=%s",
                    ctx.conversation_id,
                    used_prior_study_id,
                    prior.best_trial_id,
                )
            else:
                space, narrowed_names = narrow_bounds_around_winner(
                    space, trial.params, bracket=0.5
                )

    # 4. Telemetry (spec FR-6) — INFO event, swallowed on logger failure.
    try:
        logger.info(
            "agent.search_space_proposed "
            "conversation_id=%s template_id=%s cluster_id=%s judgment_list_id=%s "
            "prior_study_id=%s param_names=%s cardinality=%d narrowed_param_names=%s",
            ctx.conversation_id,
            str(args.template_id),
            str(args.cluster_id),
            str(args.judgment_list_id) if args.judgment_list_id is not None else None,
            used_prior_study_id,
            sorted(space.params.keys()),
            estimate_cardinality(space),
            narrowed_names,
        )
    except Exception:  # noqa: BLE001, S110 — telemetry must not block dispatch (spec FR-6)
        pass

    # 5. Return result. Read-only — no ctx.db.commit().
    return {
        "search_space": space.model_dump(),
        "grounding": {
            "template_id": str(template.id),
            "template_name": template.name,
            "cluster_id": str(cluster.id),
            "used_prior_study_id": used_prior_study_id,
            "narrowed_param_names": narrowed_names,
            "cap_aware_fallback_param_names": cap_fallback_names,
            "prior_study_template_mismatch": prior_study_template_mismatch,
        },
    }


_DESCRIPTION = (propose_search_space_impl.__doc__ or "").split("\n\n", 1)[0].strip()

PROPOSE_SEARCH_SPACE_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "propose_search_space",
        "description": _DESCRIPTION,
        "parameters": ProposeSearchSpaceArgs.model_json_schema(),
    },
}
