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
from backend.app.domain.study.auto_followup_strategy import (
    SelectionOutcome,
    select_executable_followup,
)
from backend.app.domain.study.followups import (
    NarrowFollowup,
    SwapTemplateFollowup,
    WidenFollowup,
    parse_followup_list,
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

        # 7b. feat_overnight_final_solution Story 2.2 — strategy dispatch.
        # When parent.config.auto_followup_strategy == "follow_suggestions"
        # the autopilot consumes the parent's digest follow-ups instead of
        # always running the same ±50% narrow. Default / "narrow" / missing
        # keep today's exact behavior (byte-identical legacy path).
        strategy = parent.config.get("auto_followup_strategy")
        # State that may be overridden by the follow_suggestions branch.
        # Defaults mirror the legacy narrow path so a clean fallback works.
        child_template_id: str = parent.template_id
        selection_outcome: SelectionOutcome | None = None  # populated only under follow_suggestions
        swap_target_missing = False  # tracked for the post-INSERT telemetry suppression
        # Captured INSIDE the db-context block so the post-commit
        # telemetry can use them without re-querying the closed session
        # (P2 verification finding — the `async with factory() as db:`
        # block ends at the commit; later code runs against a closed
        # session).
        digest_followup_kinds: list[str] = []
        visited_template_id_count: int = 0

        if strategy == "follow_suggestions":
            # Wrap the whole follow_suggestions block in a defensive
            # try/except per spec §13 Reliability + P1-B4: any unexpected
            # error in digest read / parse / select MUST be caught and
            # fall back to today's narrow path with a WARN. Chain
            # reliability MUST NOT regress vs the legacy path.
            try:
                digest = await repo.get_digest_for_study(db, parent.id)
                # F2 (GPT-5.5 final review): a missing digest under
                # follow_suggestions is the defensive edge case spec FR-3
                # flagged — the digest worker normally enqueues this
                # worker AFTER persisting, so a None here means manual
                # digest deletion / persistence drift. WARN with the
                # distinct event_type so operators can grep this case
                # apart from the routine text-only-digest fallback.
                if digest is None:
                    logger.warning(
                        "auto_followup follow_suggestions: parent digest missing",
                        event_type="auto_followup_strategy_digest_missing",
                        parent_study_id=parent.id,
                    )
                raw_followups = digest.suggested_followups if digest else []
                followups = parse_followup_list(raw_followups, study_id=parent.id)
                # Capture diagnostics for the post-commit telemetry.
                digest_followup_kinds = [f.kind for f in followups]
                # Anchor's missing key is treated as [anchor.template_id]
                # per D-14 (single-writer rule). The worker is the sole
                # writer of this list.
                parent_visited_list: list[str] = parent.config.get(
                    "auto_followup_visited_template_ids",
                    [parent.template_id],
                )
                visited_template_id_count = len(parent_visited_list)
                visited_template_ids: set[str] = set(parent_visited_list)
                selection_outcome = select_executable_followup(followups, visited_template_ids)

                sel = selection_outcome.selected
                if isinstance(sel, (NarrowFollowup, WidenFollowup)):
                    # Consume the follow-up's search_space verbatim
                    # (already validated by parse_followup_list + the
                    # digest worker's structured-output schema). Keep
                    # parent.template_id — narrow/widen never branch
                    # the template.
                    child_space = sel.search_space
                    narrowed_names = sorted(sel.search_space.params.keys())
                    # child_template_id stays at parent.template_id
                elif isinstance(sel, SwapTemplateFollowup):
                    # Defensive: the swap target may have been hard-
                    # deleted between digest persist and now (AC-17).
                    # On miss → WARN + fall through to the narrow
                    # fallback (the swap_template event consumes the
                    # missing-target slot; the no-executable event is
                    # NOT also emitted per FR-8).
                    swap_template = await repo.get_query_template(db, sel.template_id)
                    if swap_template is None:
                        # WARN emitted BEFORE fallback so it carries
                        # parent_study_id only (no child_study_id —
                        # the worker has not yet INSERTed the
                        # fallback child).
                        logger.warning(
                            "auto_followup swap_template target template missing",
                            event_type="auto_followup_swap_target_missing",
                            parent_study_id=parent.id,
                            swap_target_template_id=sel.template_id,
                        )
                        swap_target_missing = True
                        # Fall through to narrow fallback (defaults
                        # for child_template_id / child_space are
                        # already the legacy narrow values from
                        # step 7 above).
                    else:
                        # Use the swap target's id; consume the
                        # follow-up's search_space verbatim — the
                        # digest worker called
                        # remap_search_space_for_swap_target before
                        # persisting so the bounds are already
                        # validated against the swap target's
                        # declared_params.
                        child_template_id = sel.template_id
                        child_space = sel.search_space
                        narrowed_names = sorted(sel.search_space.params.keys())
                # else: outcome.selected is None → fall through to
                # narrow fallback (child_template_id / child_space
                # already at legacy defaults). The telemetry on the
                # fallback event still carries
                # outcome.dropped_template_ids so a chain that wanted
                # to ping-pong but was guard-dropped is observable on
                # the same line.
            except Exception as exc:  # noqa: BLE001 — defensive fallback
                # Spec §13 Reliability — any unexpected failure in the
                # follow_suggestions dispatch must degrade to the
                # legacy narrow path; chain reliability MUST NOT
                # regress vs pre-feature.
                logger.warning(
                    "auto_followup follow_suggestions dispatch failed; falling back to narrow",
                    event_type="auto_followup_strategy_dispatch_error",
                    parent_study_id=parent.id,
                    error=str(exc)[:200],
                )
                selection_outcome = None  # treat as "no selection" → fallback
                # child_template_id + child_space remain at legacy
                # narrow defaults from step 7 above.

        # 8. Build the child config with the depth counter decremented.
        # FR-5 strict inheritance: every other key propagates verbatim.
        # Use .get() defensively in case parent.config was serialized with
        # exclude_none=True (Gemini Code Assist review, PR #223).
        parent_depth: int = parent.config.get("auto_followup_depth", 0)
        remaining = parent_depth - 1
        child_config: dict[str, Any] = {**parent.config, "auto_followup_depth": remaining}

        # Per FR-3 / AC-18: child must NEVER inherit the parent's
        # auto_followup_selected_kind — it's per-link state recording the
        # path THIS worker invocation took. Pop unconditionally; the
        # follow_suggestions branch below re-sets the right value.
        child_config.pop("auto_followup_selected_kind", None)

        if strategy == "follow_suggestions":
            # Persist the cycle-guard state (ordered-unique visited list)
            # and the per-link selected_kind. Per D-12, these keys are
            # ONLY persisted under "follow_suggestions" — the legacy
            # path stays clean.
            parent_visited_raw = parent.config.get(
                "auto_followup_visited_template_ids",
                [parent.template_id],
            )
            # Ordered-unique via list(dict.fromkeys(...)) per FR-5 + AC-6:
            # when child_template_id == parent.template_id (narrow/widen
            # kept the same template, OR fell back to narrow), the list
            # does not grow.
            child_config["auto_followup_visited_template_ids"] = list(
                dict.fromkeys([*parent_visited_raw, child_template_id])
            )
            sel = selection_outcome.selected if selection_outcome is not None else None
            if isinstance(sel, NarrowFollowup):
                child_config["auto_followup_selected_kind"] = "narrow"
            elif isinstance(sel, WidenFollowup):
                child_config["auto_followup_selected_kind"] = "widen"
            elif isinstance(sel, SwapTemplateFollowup) and not swap_target_missing:
                child_config["auto_followup_selected_kind"] = "swap_template"
            else:
                # No executable selected, OR swap target missing → the
                # follow_suggestions fallback-to-narrow path. Per D-12
                # this DOES persist "narrow_default" (operator picked
                # follow_suggestions but the autopilot had nothing
                # executable to run; the "refined" badge on the chain
                # panel is the audit signal).
                child_config["auto_followup_selected_kind"] = "narrow_default"

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
            template_id=child_template_id,
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

    # 12. feat_overnight_final_solution Story 2.2 — strategy telemetry.
    # Emitted AFTER child INSERT/commit so child_study_id is populated.
    # Only under "follow_suggestions"; legacy/narrow stays log-quiet.
    if strategy == "follow_suggestions" and selection_outcome is not None:
        sel = selection_outcome.selected
        if isinstance(sel, (NarrowFollowup, WidenFollowup, SwapTemplateFollowup)):
            # Suppress when swap target was missing — the swap_target_missing
            # WARN already covered that case (FR-8: distinct event shape).
            if not (isinstance(sel, SwapTemplateFollowup) and swap_target_missing):
                logger.info(
                    "auto_followup strategy selected an executable follow-up",
                    event_type="auto_followup_strategy_selected",
                    parent_study_id=parent_study_id,
                    child_study_id=child_id,
                    strategy="follow_suggestions",
                    selected_kind=child_config["auto_followup_selected_kind"],
                    source_index=selection_outcome.source_index,
                    candidate_count=selection_outcome.candidate_count,
                    dropped_template_ids=selection_outcome.dropped_template_ids,
                )
        else:
            # sel is None → no executable candidate (text-only digest OR
            # all-swaps-cycle-dropped). Fallback to narrow took the
            # `narrow_default` path. The fallback event carries the
            # dropped ids so the operator sees the ping-pong-vs-text
            # distinction on one line. Uses the diagnostic locals
            # captured inside the db-context block above.
            logger.info(
                "auto_followup no executable candidate; fell back to narrow",
                event_type="auto_followup_no_executable_candidate_fell_back_to_narrow",
                parent_study_id=parent_study_id,
                child_study_id=child_id,
                digest_followup_kinds=digest_followup_kinds,
                visited_template_id_count=visited_template_id_count,
                dropped_template_ids=selection_outcome.dropped_template_ids,
            )
    elif strategy == "follow_suggestions" and selection_outcome is None:
        # The defensive try/except caught an unexpected error in the
        # dispatch block. We already emitted the
        # auto_followup_strategy_dispatch_error WARN inside the except;
        # the child was still created on the narrow fallback path. No
        # additional INFO event — the WARN is the audit signal.
        pass
