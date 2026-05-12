"""Service-layer dispatch for LLM-judgment generation (feat_chat_agent Story 2.2).

The preflight (OpenAI configured / capability cache / model pricing / budget
peek / FK resolution / consistency / oversize) + INSERT + Arq enqueue lift out
of ``backend/app/api/v1/judgments.py`` so both the router AND the chat-agent
``generate_judgments_llm`` tool reuse the same checks without duplication.

Raises ``HTTPException`` with the spec §7.5 error envelope so the router's
existing handler passes the structured detail through unchanged and the agent
dispatcher can map ``HTTPException.detail['error_code']`` into a
``tool_result.error`` payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from arq.connections import ArqRedis
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import get_logger
from backend.app.core.settings import Settings
from backend.app.db import repo
from backend.app.llm.budget_gate import peek_daily_total
from backend.app.llm.capability_check import read_capability_result
from backend.app.llm.cost_model import known_models

logger = get_logger(__name__)


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


@dataclass(frozen=True, slots=True)
class JudgmentGenerationRequest:
    """Inputs to ``start_judgment_generation``.

    Mirrors the shape of ``CreateJudgmentListGenerateRequest`` (the router's
    request body) so callers can pass either the request model fields directly
    or build this dataclass from tool args.
    """

    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    current_template_id: str
    rubric: str


@dataclass(frozen=True, slots=True)
class JudgmentGenerationResult:
    """Return value from ``start_judgment_generation``."""

    judgment_list_id: str
    status: Literal["generating"]


async def start_judgment_generation(
    *,
    db: AsyncSession,
    redis: Redis,
    arq_pool: ArqRedis | None,
    settings: Settings,
    req: JudgmentGenerationRequest,
) -> JudgmentGenerationResult:
    """Run the full preflight + create the judgment_list row + enqueue the worker.

    Preflight order (matches spec FR-3 + GPT-5.5 cycles 1/2 from feat_llm_judgments):

    A. ``OPENAI_NOT_CONFIGURED`` — key missing.
    B. ``LLM_PROVIDER_INCAPABLE`` — capability cache miss OR
       ``structured_output != ok`` OR cached model differs from configured.
    B.1. ``UNKNOWN_MODEL_PRICING`` — ``Settings.openai_model`` has no cost_model entry.
    C. ``OPENAI_BUDGET_EXCEEDED`` — pre-call peek already >= budget.
    D. FK resolution (cluster / template / query_set).
    D.1. Consistency (query_set ↔ cluster, template engine ↔ cluster engine).
    E. Oversized query set (>10K) → 422 VALIDATION_ERROR.
    F. INSERT (UNIQUE collision → 409 JUDGMENT_LIST_NAME_TAKEN); commit; best-effort enqueue.
    """
    # Preflight A — OpenAI key configured.
    api_key = settings.openai_api_key
    if not api_key:
        raise _err(
            503,
            "OPENAI_NOT_CONFIGURED",
            "OPENAI_API_KEY_FILE is empty; cannot dispatch judgment generation",
            False,
        )

    # Preflight B — capability cache (model-aware per cycle-8 C8-F2 in feat_llm_judgments).
    cap = await read_capability_result(redis, settings.openai_base_url)
    if cap is None or cap.structured_output != "ok" or cap.model != settings.openai_model:
        if cap is None:
            cause = "cache miss"
        elif cap.model != settings.openai_model:
            cause = (
                f"cached probe model {cap.model!r} != configured "
                f"OPENAI_MODEL {settings.openai_model!r}"
            )
        else:
            cause = f"structured_output={cap.structured_output!r}"
        raise _err(
            503,
            "LLM_PROVIDER_INCAPABLE",
            f"OpenAI capability check ({cause}); structured-output required",
            False,
        )

    # Preflight B.1 — model pricing must be known.
    if settings.openai_model not in known_models():
        raise _err(
            503,
            "UNKNOWN_MODEL_PRICING",
            f"OPENAI_MODEL={settings.openai_model!r} has no entry in cost_model; "
            "cannot enforce daily budget gate",
            False,
        )

    # Preflight C — daily budget peek.
    if settings.openai_daily_budget_usd > 0:
        current = await peek_daily_total(redis)
        if current >= settings.openai_daily_budget_usd:
            raise _err(
                503,
                "OPENAI_BUDGET_EXCEEDED",
                f"daily total ${current:.2f} >= budget ${settings.openai_daily_budget_usd:.2f}",
                True,
            )

    # Preflight D — FK resolution.
    cluster = await repo.get_cluster(db, req.cluster_id)
    if cluster is None:
        raise _err(404, "CLUSTER_NOT_FOUND", f"cluster {req.cluster_id} not found", False)
    template = await repo.get_query_template(db, req.current_template_id)
    if template is None:
        raise _err(
            404,
            "TEMPLATE_NOT_FOUND",
            f"template {req.current_template_id} not found",
            False,
        )
    query_set = await repo.get_query_set(db, req.query_set_id)
    if query_set is None:
        raise _err(404, "QUERY_SET_NOT_FOUND", f"query set {req.query_set_id} not found", False)

    # Preflight D.1 — consistency.
    if query_set.cluster_id != req.cluster_id:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"query_set {req.query_set_id} belongs to cluster "
            f"{query_set.cluster_id!r}, not {req.cluster_id!r}",
            False,
        )
    if template.engine_type != cluster.engine_type:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"template engine_type {template.engine_type!r} does not match "
            f"cluster engine_type {cluster.engine_type!r}",
            False,
        )

    # Preflight E — oversized query set.
    count = await repo.count_queries_in_set(db, req.query_set_id)
    if count > 10_000:
        raise _err(
            422,
            "VALIDATION_ERROR",
            f"query set has {count} queries; max 10000 allowed for LLM generation",
            False,
        )

    # F. INSERT — catch UNIQUE name collision.
    judgment_list_id = str(uuid.uuid4())
    try:
        await repo.create_judgment_list(
            db,
            id=judgment_list_id,
            name=req.name,
            description=req.description,
            query_set_id=req.query_set_id,
            cluster_id=req.cluster_id,
            target=req.target,
            current_template_id=req.current_template_id,
            rubric=req.rubric,
            status="generating",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise _err(
            409,
            "JUDGMENT_LIST_NAME_TAKEN",
            f"judgment list name {req.name!r} already exists",
            False,
        ) from exc

    # Best-effort Arq enqueue. Pool absent → boot-time resume sweep recovers.
    if arq_pool is not None:
        try:
            await arq_pool.enqueue_job(
                "generate_judgments_llm",
                judgment_list_id,
                _job_id=f"generate_judgments_llm:{judgment_list_id}",
            )
        except Exception as exc:  # noqa: BLE001 — durable row + sweep covers this
            logger.warning(
                "start_judgment_generation: arq enqueue raised — relying on worker boot sweep",
                judgment_list_id=judgment_list_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    return JudgmentGenerationResult(judgment_list_id=judgment_list_id, status="generating")
