# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Auto-followup chain worker (feat_auto_followup_studies Story 2.1).

`enqueue_followup_study` is dispatched by the digest worker after a study
completes. It evaluates the chain gate + budget gate; if both pass, it
creates the next chain member and enqueues `start_study` for it.

Telemetry events (FR-9 catalog — 7 of 8 emitted here; the 8th
`auto_followup_cancelled_with_parent` lives in the cascade service):

* ``auto_followup_enqueued`` — child created + start_study enqueued
* ``auto_followup_skipped_no_lift`` — gate returned SKIP_NO_LIFT
* ``auto_followup_skipped_parent_failed`` — defensive; digest doesn't run
  on failed studies in normal flow
* ``auto_followup_skipped_parent_missing`` — defensive; hard-delete race
* ``auto_followup_skipped_budget`` — daily LLM budget would exceed 80%
* ``auto_followup_depth_exhausted`` — fires on depth-0 leaf's own
  invocation (per FR-1 + D-12)
* ``auto_followup_enqueued_duplicate_dropped`` — layer-2 idempotency
  backstop (Arq `_job_id` dedup is the primary mechanism per D-11)

Plus one auxiliary event (outside FR-9 catalog):

* ``digest_followup_start_study_enqueue_failed`` — best-effort log per
  the digest-worker `digest_enqueue_failed` precedent at
  backend/workers/orchestrator.py:455. The child row stays as
  `queued`; the existing `on_startup` boot-sweep at
  backend/workers/all.py:138-151 picks it up on next worker boot.

Imports (per Story 1.2 discovery + cycle-1 finding C1-10): the actual
domain function is `narrow_bounds_around_winner`, NOT `narrow_around_winner`,
and it takes a SearchSpace not a template_id. The worker composes
`build_starter_search_space` + `narrow_bounds_around_winner` itself.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.domain.study.auto_followup import (
    ChainGateDecision,
    evaluate_chain_gate,
)
from backend.app.domain.study.search_space_defaults import (
    build_starter_search_space,
    narrow_bounds_around_winner,
)
from backend.app.llm.budget_gate import peek_daily_total
from backend.app.llm.cost_model import estimated_max_call_cost, known_models

logger = structlog.get_logger(__name__)

# Spec FR-6 + D-5: enqueue is blocked at >= 80% of the configured daily budget.
_BUDGET_THRESHOLD_PCT = 0.80


async def enqueue_followup_study(ctx: dict[str, Any], parent_study_id: str) -> None:
    """Build the next chain member if all gates pass.

    Dispatched by the digest worker via Arq with deterministic
    ``_job_id=f"enqueue_followup_study:{parent_study_id}"`` for layer-1
    queue-level idempotency. The worker re-checks
    ``list_children_of_study`` as a layer-2 backstop in case the
    ``_job_id`` key expired between deliveries.
    """
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as db:
        # 1. Load parent. Defensive: missing parent → defensive skip log.
        parent = await repo.get_study(db, parent_study_id)
        if parent is None:
            logger.info(
                "auto_followup parent study missing (race with hard delete)",
                event_type="auto_followup_skipped_parent_missing",
                parent_study_id=parent_study_id,
            )
            return

        # 2. LAYER-2 IDEMPOTENCY BACKSTOP (D-11). Re-check children to
        # cover the case where the Arq _job_id key expired between deliveries.
        existing_children = await repo.list_children_of_study(db, parent_study_id)
        if existing_children:
            logger.info(
                "auto_followup child already exists; dropping duplicate enqueue",
                event_type="auto_followup_enqueued_duplicate_dropped",
                parent_study_id=parent_study_id,
                existing_child_ids=[c.id for c in existing_children],
            )
            return

        # 3. Load complete trials. repo.list_trials_for_study returns ALL
        # trials (any status); filter in-Python to status='complete' per
        # spec FR-3 + cycle-1 finding C1-7.
        all_trials = await repo.list_trials_for_study(db, parent_study_id)
        complete_trials = [t for t in all_trials if t.status == "complete"]

        # 4. Evaluate the chain gate. Dispatch on the returned decision.
        outcome = evaluate_chain_gate(parent, complete_trials)
        if outcome.decision is ChainGateDecision.SKIP_NO_LIFT:
            logger.info(
                "auto_followup chain skipped: no lift",
                event_type="auto_followup_skipped_no_lift",
                parent_study_id=parent_study_id,
                best_metric=parent.best_metric,
                first_decile_max=outcome.first_decile_max,
                epsilon=outcome.epsilon,
            )
            return
        if outcome.decision is ChainGateDecision.SKIP_PARENT_FAILED:
            logger.info(
                "auto_followup chain skipped: parent terminated abnormally",
                event_type="auto_followup_skipped_parent_failed",
                parent_study_id=parent_study_id,
                parent_status=parent.status,
                parent_failed_reason=parent.failed_reason,
            )
            return
        if outcome.decision is ChainGateDecision.SKIP_DEPTH_EXHAUSTED:
            logger.info(
                "auto_followup chain ended: depth exhausted",
                event_type="auto_followup_depth_exhausted",
                parent_study_id=parent_study_id,
                auto_followup_depth=parent.config.get("auto_followup_depth"),
            )
            return
        # Falls through only for ChainGateDecision.ENQUEUE.

        # 5. Budget peek (FR-6 + D-5). Skip if peek + max-call estimate
        # would exceed 80% of the daily budget.
        budget = settings.openai_daily_budget_usd
        model = settings.openai_model
        # Per phase-gate review F5: unknown model pricing is a defensive
        # SKIP, not a "treat as zero cost" pass. Mirrors digest.py:543
        # "digest worker: model has no pricing entry; aborting" — better
        # to over-skip than under-skip the budget gate.
        if budget > 0 and model not in known_models():
            logger.warning(
                "auto_followup chain skipped: unknown model pricing",
                event_type="auto_followup_skipped_budget",
                parent_study_id=parent_study_id,
                model=model,
                reason="unknown_model_pricing",
            )
            return
        # Per digest.py:439 precedent — create our own Redis client inline
        # rather than relying on ctx['redis_client'] (which isn't set up
        # in WorkerSettings.on_startup per cycle-1 finding C1-11).
        redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
        try:
            if budget > 0:
                peek_total = await peek_daily_total(redis_client)
                max_call_cost = estimated_max_call_cost(model)
                if peek_total + max_call_cost > _BUDGET_THRESHOLD_PCT * budget:
                    logger.info(
                        "auto_followup chain skipped: daily LLM budget near limit",
                        event_type="auto_followup_skipped_budget",
                        parent_study_id=parent_study_id,
                        peek_total=peek_total,
                        budget=budget,
                        threshold_pct=int(_BUDGET_THRESHOLD_PCT * 100),
                    )
                    return
        finally:
            await redis_client.aclose()

        # 6. Load the parent's best trial for the narrowing primitive.
        if parent.best_trial_id is None:
            # Shouldn't happen — evaluate_chain_gate already requires
            # parent.best_metric is not None and would have skipped.
            # Defensive only.
            logger.info(
                "auto_followup parent has no best_trial_id; cannot narrow",
                event_type="auto_followup_skipped_no_lift",
                parent_study_id=parent_study_id,
            )
            return
        best_trial = await repo.get_trial(db, parent.best_trial_id)
        if best_trial is None:
            logger.warning(
                "auto_followup parent.best_trial_id points at missing trial",
                event_type="auto_followup_skipped_no_lift",
                parent_study_id=parent_study_id,
                best_trial_id=parent.best_trial_id,
            )
            return

        # 7. Load template + build starter space + narrow around winner.
        # Per Story 1.2 discovery: narrow_bounds_around_winner takes a
        # SearchSpace, not a template_id; we compose two domain funcs.
        template = await repo.get_query_template(db, parent.template_id)
        if template is None:
            logger.warning(
                "auto_followup parent.template_id points at missing template",
                event_type="auto_followup_skipped_no_lift",
                parent_study_id=parent_study_id,
                template_id=parent.template_id,
            )
            return
        declared_params = template.declared_params or {}
        starter = build_starter_search_space(declared_params)
        child_space, narrowed_names = narrow_bounds_around_winner(
            starter.space,
            best_trial.params,
            bracket=0.5,
        )

        # 8. Build the child config with the depth counter decremented.
        # FR-5 strict inheritance: every other key propagates verbatim.
        # Use .get() defensively in case parent.config was serialized with
        # exclude_none=True (Gemini Code Assist review, PR #223).
        parent_depth: int = parent.config.get("auto_followup_depth", 0)
        remaining = parent_depth - 1
        child_config = {**parent.config, "auto_followup_depth": remaining}

        # 9. Build child name + persist via repo. The repo.create_study
        # call sets status='queued' (default for new studies); the
        # SQLAlchemy event-listener guard at services/study_state.py:296
        # permits queued-row creation (the guard only fires on UPDATE,
        # not INSERT).
        child_id = str(uuid.uuid4())
        child_name = f"{parent.name} (chain depth {remaining})"
        await repo.create_study(
            db,
            id=child_id,
            name=child_name,
            cluster_id=parent.cluster_id,
            target=parent.target,
            template_id=parent.template_id,
            query_set_id=parent.query_set_id,
            judgment_list_id=parent.judgment_list_id,
            search_space=child_space.model_dump(),
            objective=parent.objective,
            config=child_config,
            status="queued",
            optuna_study_name=child_id,
            parent_study_id=parent.id,
        )
        await db.commit()

    # 10. Enqueue start_study (best-effort — recovery via boot-sweep).
    arq_pool = ctx.get("arq_pool")
    if arq_pool is None:
        logger.warning(
            "auto_followup: arq_pool missing in ctx; child queued without start enqueue",
            event_type="digest_followup_start_study_enqueue_failed",
            parent_study_id=parent_study_id,
            child_study_id=child_id,
            error="arq_pool missing in ctx",
        )
    else:
        try:
            await arq_pool.enqueue_job("start_study", child_id)
        except Exception as exc:  # noqa: BLE001 — best-effort, mirrors digest.py
            logger.warning(
                "auto_followup: start_study enqueue failed; queued-row sweep will recover",
                event_type="digest_followup_start_study_enqueue_failed",
                parent_study_id=parent_study_id,
                child_study_id=child_id,
                error=str(exc),
            )

    # 11. Success telemetry (FR-9 event #1).
    logger.info(
        "auto_followup child enqueued",
        event_type="auto_followup_enqueued",
        parent_study_id=parent_study_id,
        child_study_id=child_id,
        remaining_depth=remaining,
        lift=outcome.lift,
        first_decile_max=outcome.first_decile_max,
        epsilon=outcome.epsilon,
        narrowed_param_names=narrowed_names,
    )
