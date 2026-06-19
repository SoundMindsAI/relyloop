# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``generate_judgments_llm`` Arq job (feat_llm_judgments Story 2.1 / FR-2).

Single-list LLM-as-judge pipeline:

1. Load the ``judgment_lists`` row + its generation context (cluster,
   template, query_set, rubric). Bail early if the row vanished or is no
   longer ``status='generating'`` (idempotent re-entry).
2. For each query in the query_set:

   a. **Resume-skip check** — if ``count_judgments_for_list_and_query``
      already ``>= TOP_K``, the query was completed by a prior pass; skip
      it so a resumed worker doesn't re-spend OpenAI dollars on
      already-judged rows (per GPT-5.5 cycle 2 F5).
   b. **Pre-call budget peek** — if ``current + estimated_max > budget``
      and the budget is enabled, abort the loop with ``BudgetExceededError``
      (per spec FR-2 + GPT-5.5 cycle 1 F8).
   c. Render the query template + run ``adapter.search_batch``.
   d. Render the user prompt; call ``rate_query_batch`` with the doc-id
      allowlist (the hits' ``doc_id`` set).
   e. **Post-call record** — ``record_cost`` with the actual measured cost.
   f. ``bulk_create_judgments`` with ``source='llm'``,
      ``rater_ref='openai:{model}'``. Idempotent against re-runs by way of
      the UNIQUE ``(judgment_list_id, query_id, doc_id)`` ON CONFLICT
      DO NOTHING semantics.

3. Terminal status: ``status='complete'`` on a clean loop;
   ``status='failed'`` + a structured ``failed_reason`` on
   ``BudgetExceededError`` / ``UnknownModelPricingError`` /
   unexpected exception.

Per-query failures (e.g., OpenAI rate-limit exhaustion for one query,
cluster unreachable for one query) are isolated: they log WARN and the
loop moves on to the next query.
"""

from __future__ import annotations

import time
from typing import Any, cast

import structlog
from openai import AsyncOpenAI
from redis.asyncio import Redis

from backend.app.adapters.protocol import QueryTemplate
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.llm.budget_gate import BudgetExceededError
from backend.app.llm.cost_model import UnknownModelPricingError, estimated_max_call_cost
from backend.app.llm.prompt_loader import load_judgment_prompts
from backend.app.services.cluster import build_adapter
from backend.app.services.judgment_generation import (
    fail_judgment_list,
    fail_on_budget_or_pricing_error,
    process_judgment_query,
)
from backend.workers.helpers import close_quietly

logger = structlog.get_logger(__name__)


async def generate_judgments_llm(ctx: dict[str, Any], judgment_list_id: str) -> None:
    """Arq entry point — run the LLM judge pipeline for one judgment list.

    Contract (per FR-2 + the cycle-1 + cycle-2 review):

    1. Load row → bail if missing or already-terminal.
    2. Build engine adapter + OpenAI client (lazy — operator may enable
       OPENAI_API_KEY after the API service booted).
    3. Loop queries; per-query budget / search / LLM / persist.
    4. Terminal-status flip on the parent row.
    """
    settings = get_settings()
    started_at = time.monotonic()
    factory = get_session_factory()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    openai_client: AsyncOpenAI | None = None

    try:
        async with factory() as db:
            judgment_list = await repo.get_judgment_list(db, judgment_list_id)
            if judgment_list is None:
                logger.info(
                    "judgment worker: list vanished, returning",
                    event_type="judgment_list_missing",
                    judgment_list_id=judgment_list_id,
                )
                return
            if judgment_list.status != "generating":
                logger.info(
                    "judgment worker: list already terminal, returning",
                    event_type="judgment_list_already_terminal",
                    judgment_list_id=judgment_list_id,
                    status=judgment_list.status,
                )
                return

            cluster = await repo.get_cluster(db, judgment_list.cluster_id)
            if cluster is None:
                await fail_judgment_list(
                    db,
                    judgment_list_id,
                    "CLUSTER_NOT_FOUND",
                )
                return

            template_row = None
            if judgment_list.current_template_id is not None:
                template_row = await repo.get_query_template(db, judgment_list.current_template_id)
            if template_row is None:
                await fail_judgment_list(db, judgment_list_id, "TEMPLATE_NOT_FOUND")
                return

            queries = await repo.list_queries_for_set(db, judgment_list.query_set_id)
            if not queries:
                # No queries → nothing to judge → mark complete (degenerate but valid).
                await repo.update_judgment_list_status(db, judgment_list_id, status="complete")
                await db.commit()
                return

        # Resolve OpenAI config + build the AsyncOpenAI client.
        api_key = settings.openai_api_key
        if not api_key:
            async with factory() as db:
                await fail_judgment_list(db, judgment_list_id, "OPENAI_NOT_CONFIGURED")
            return
        model = settings.openai_model
        # Pricing must be known so the budget gate can fire honestly.
        try:
            estimated_max_call_cost(model)
        except UnknownModelPricingError:
            async with factory() as db:
                await fail_judgment_list(db, judgment_list_id, "UNKNOWN_MODEL_PRICING")
            return

        openai_client = AsyncOpenAI(api_key=api_key, base_url=settings.openai_base_url)
        bundle = load_judgment_prompts()
        adapter = build_adapter(cluster)

        # Re-use a long-lived session for the per-query loop so each commit
        # only flushes that query's bulk insert. Mirrors the trials.py
        # short-lived-session pattern but pivoted around the query loop.
        template = QueryTemplate(
            name=template_row.name,
            engine_type=cast(Any, template_row.engine_type),
            body=template_row.body,
            declared_params=cast(dict[str, str], template_row.declared_params),
        )

        skipped_query_ids: list[str] = []
        for query in queries:
            async with factory() as db:
                try:
                    ok = await process_judgment_query(
                        db=db,
                        redis=redis_client,
                        openai_client=openai_client,
                        judgment_list_id=judgment_list_id,
                        judgment_list=judgment_list,
                        template=template,
                        template_row=template_row,
                        query=query,
                        adapter=adapter,
                        bundle_system=bundle.system_prompt,
                        rubric_text=judgment_list.rubric,
                        model=model,
                        budget_usd=settings.openai_daily_budget_usd,
                    )
                    if not ok:
                        skipped_query_ids.append(str(query.id))
                except (BudgetExceededError, UnknownModelPricingError) as exc:
                    await fail_on_budget_or_pricing_error(
                        factory, judgment_list_id, exc, logger=logger, event_prefix="judgment"
                    )
                    return

        # All queries processed. If any query was skipped (search failed,
        # LLM call failed after retries, LLM returned a partial response,
        # cost-recording flap), surface that as a terminal ``failed``
        # state rather than silently completing with missing qrels. The
        # resume sweep only re-enqueues ``generating`` lists, so a
        # ``complete`` list with gaps would be permanently stuck. Per
        # GPT-5.5 cycle-8 C8-F1.
        async with factory() as db:
            if skipped_query_ids:
                reason = f"PARTIAL_LLM_FAILURE: {len(skipped_query_ids)} queries unrated"
                await repo.update_judgment_list_status(
                    db,
                    judgment_list_id,
                    status="failed",
                    failed_reason=reason,
                )
                await db.commit()
                logger.warning(
                    "judgment worker: list complete with skipped queries — marking failed",
                    event_type="judgment_list_partial_failure",
                    judgment_list_id=judgment_list_id,
                    skipped_count=len(skipped_query_ids),
                    skipped_sample=skipped_query_ids[:5],
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
            else:
                await repo.update_judgment_list_status(db, judgment_list_id, status="complete")
                await db.commit()
                logger.info(
                    "judgment worker: list complete",
                    event_type="judgment_list_complete",
                    judgment_list_id=judgment_list_id,
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
    except Exception as exc:  # noqa: BLE001 — any unexpected failure → mark failed
        logger.warning(
            "judgment worker: unhandled exception — marking list failed",
            event_type="judgment_unhandled_failure",
            judgment_list_id=judgment_list_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        try:
            async with factory() as db:
                await fail_judgment_list(db, judgment_list_id, f"UNEXPECTED:{type(exc).__name__}")
        except Exception:  # noqa: BLE001 — defensive; nothing left to do
            logger.exception(
                "judgment worker: failed to record terminal status",
                judgment_list_id=judgment_list_id,
            )
    finally:
        await close_quietly(openai_client, logger=logger, label="openai client")
        await close_quietly(redis_client, logger=logger, label="redis")
