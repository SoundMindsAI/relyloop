"""``generate_digest`` Arq job (feat_digest_proposal Story 2.1 / FR-2).

Replaces the stub at :mod:`backend.workers.digest_stub` under the same Arq
job name (``generate_digest``) so the orchestrator's enqueue at
``backend/workers/orchestrator.py:370`` and the boot-scan enqueue at
``backend/workers/all.py`` keep firing without orchestrator-side changes.

Worker contract (the cycle-2 / cycle-3 GPT-5.5 plan-review revisions are
authoritative — see implementation_plan.md Story 2.1):

  1. Load study + bail if missing or status != 'completed'.
  2. **Pre-LLM idempotency guard (cycle-1 F6)** — if a digest already
     exists for ``study_id``, log + return.
  3. **Atomic per-study advisory lock (cycle-2 F6)** — acquire
     ``pg_try_advisory_xact_lock`` keyed on a hash of
     ``f"digest:{study_id}"`` (different prefix from the orchestrator's
     replenish lock). Held across the LLM call + persist tx.
  4. Locate the pending proposal; defensive INSERT if missing.
  5. **Zero-trials short-circuit (cycle-2 F5; AC-2)** — if
     ``study.best_metric IS NULL``, persist a placeholder digest +
     DELETE pending proposal + return. **No OpenAI call.**
  6. OpenAI key check → log + return on missing key (AC-10).
  7. Capability check → set ``structured_output_enabled`` flag (cycle-3
     F2 — DO NOT short-circuit; the narrative-only fallback still costs
     money so pricing + budget below MUST still apply).
  8. Model-pricing check.
  9. Daily-budget peek.
 10. Load top trials + Optuna study; compute parameter_importance.
 11. **Compute deterministic recommended_config (cycle-1 F5/F9 + cycle-2
     F7)** — filter best-trial params to currently-declared template
     params. All-dropped sub-case → persist digest + DELETE proposal.
 12. Render user prompt with ``include_recommendation``; call OpenAI.
 13. Merge follow-ups (drift-followup prepended; capped at 5).
 14. Compute metric_delta + config_diff.
 15. **Persist FIRST then record cost (cycle-2 C2-F3 ordering from
     feat_llm_judgments)** — INSERT digest + UPDATE pending proposal
     conditionally (cycle-3 F4 — UPDATE WHERE status='pending'; benign
     no-op when operator rejected mid-LLM).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import openai
import optuna
import structlog
import uuid_utils
from openai import AsyncOpenAI
from redis.asyncio import Redis
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.models import Proposal
from backend.app.db.session import get_session_factory
from backend.app.domain.study.template_defaults import compute_default_params
from backend.app.eval.optuna_runtime import build_pruner, build_sampler, get_or_create_study
from backend.app.llm.budget_gate import peek_daily_total, record_cost
from backend.app.llm.capability_check import read_capability_result
from backend.app.llm.cost_model import (
    compute_call_cost,
    estimated_max_call_cost,
    known_models,
)
from backend.app.llm.digest_prompt import load_digest_prompts, render_digest_user_prompt

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOP_K_TRIALS = 10
"""Top-N trials passed to the LLM in the prompt (per spec §11 token budget)."""

_MAX_COMPLETION_TOKENS = 2_000
"""Honest budget gate: matches cost_model._OUTPUT_TOKEN_CEILING. Cycle-1 F4."""

_FAILURE_NARRATIVE = "No successful trials in this study. Diagnose using the worker logs."
"""AC-2 placeholder narrative for the zero-trials path."""


# ---------------------------------------------------------------------------
# Structured-output schema (cycle-1 F4 + cycle-1 F5)
# ---------------------------------------------------------------------------

# The LLM provides ONLY narrative + suggested_followups. recommended_config
# is computed deterministically from best-trial params filtered to
# currently-declared template params (per spec FR-5 + cycle-1 F5 / cycle-2 F1).
# Module-level so the contract test can import + assert shape.
DIGEST_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "suggested_followups": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,  # cycle-1 F4: wired into the schema, not just prose
        },
    },
    "required": ["narrative", "suggested_followups"],
    "additionalProperties": False,
}

DIGEST_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "digest_narrative",
        "schema": DIGEST_RESPONSE_SCHEMA,
        "strict": True,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _safe_record_cost(redis: Redis, cost_usd: float) -> float | None:
    """Record cost, catching transient Redis failures.

    Mirrors :func:`backend.workers.judgments._safe_record_cost` (cycle-2
    C2-F3 from feat_llm_judgments). Persisting the digest precedes this
    call; under-counting daily spend during a Redis outage is recoverable
    on rollover, losing a paid-for digest is not.
    """
    try:
        return await record_cost(redis, cost_usd)
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "digest worker: record_cost failed (budget telemetry only)",
            event_type="digest_record_cost_failed",
            cost_usd=cost_usd,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None


@asynccontextmanager
async def _acquire_digest_lock(db: AsyncSession, study_id: str) -> AsyncIterator[bool]:
    """Try to acquire a Postgres xact-scoped advisory lock keyed by study_id.

    Lock key: first 8 bytes of ``blake2b(f"digest:{study_id}", digest_size=8)``
    interpreted as a signed 64-bit integer. The ``digest:`` prefix keeps
    this lock space DISJOINT from the orchestrator's replenish lock
    (which uses the bare ``study_id`` as input) — same study can have
    both an orchestrator replenish lock AND a digest generation lock
    held simultaneously without colliding.

    Transaction-scoped: commit/rollback releases automatically — no
    explicit ``pg_advisory_unlock``.

    Mirrors :func:`backend.workers.orchestrator._try_replenish_xact_lock`
    (cycle-2 F6).
    """
    lock_key = int.from_bytes(
        hashlib.blake2b(f"digest:{study_id}".encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    acquired = (
        await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key})
    ).scalar_one()
    yield bool(acquired)


async def _ensure_pending_proposal(db: AsyncSession, study: Any) -> Proposal:
    """Locate the pending proposal for the study; defensive INSERT if missing.

    The orchestrator inserts the pending proposal in the same transaction
    as ``complete_study`` (Phase 2 C3-F1 atomicity fix), so the row
    almost always exists by the time the digest worker runs. The
    defensive INSERT covers the operationally-unlikely case where the
    proposal row was hand-deleted between commit and the worker's tick.
    """
    stmt = (
        select(Proposal)
        .where(Proposal.study_id == study.id)
        .where(Proposal.status == "pending")
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    logger.warning(
        "digest worker: pending proposal missing — inserting defensively",
        event_type="digest_proposal_inserted_defensively",
        study_id=study.id,
    )
    inserted = await repo.create_proposal(
        db,
        id=str(uuid_utils.uuid7()),
        study_id=study.id,
        study_trial_id=study.best_trial_id,
        cluster_id=study.cluster_id,
        template_id=study.template_id,
        config_diff={},
        metric_delta=None,
        status="pending",
    )
    return inserted


def _objective_metric_key(objective: dict[str, Any]) -> str:
    """Build the wire-name metric key from ``study.objective``.

    Mirrors :func:`backend.app.eval.scoring.objective_metric_key` shape
    (e.g. ``ndcg`` + ``k=10`` → ``ndcg@10``; ``mrr`` → ``mrr``).
    """
    metric = str(objective.get("metric", "primary"))
    k = objective.get("k")
    if isinstance(k, int) and k > 0:
        return f"{metric}@{k}"
    return metric


def _compute_metric_delta(study: Any) -> dict[str, Any]:
    """Build the wire-shape ``metric_delta`` dict for the proposal.

    ``{primary_metric_key: {baseline, achieved, delta_pct}}``. ``delta_pct``
    is ``None`` when there's no baseline (no division denominator).
    """
    key = _objective_metric_key(study.objective)
    baseline = study.baseline_metric
    achieved = study.best_metric
    delta_pct: float | None = None
    if baseline is not None and baseline != 0:
        delta_pct = round((achieved - baseline) / baseline * 100, 1)
    return {key: {"baseline": baseline, "achieved": achieved, "delta_pct": delta_pct}}


def _compute_top_trials(trials: list[Any]) -> list[dict[str, Any]]:
    """Produce the prompt-shape ``[{number, params, primary_metric}, ...]`` list."""
    return [
        {
            "number": t.optuna_trial_number,
            "params": t.params,
            "primary_metric": t.primary_metric,
        }
        for t in trials
    ]


# ---------------------------------------------------------------------------
# Specialized exit paths (kept tiny and isolated for readability)
# ---------------------------------------------------------------------------


async def _persist_zero_trials_digest(db: AsyncSession, study: Any) -> None:
    """AC-2 + cycle-2 F5: failure-narrative digest + DELETE pending proposal.

    Runs BEFORE OpenAI key/capability/pricing/budget preflights — the
    failure digest must be persisted regardless of OpenAI configuration.
    """
    proposal = await _ensure_pending_proposal(db, study)
    digest_id = str(uuid_utils.uuid7())
    try:
        await repo.create_digest(
            db,
            id=digest_id,
            study_id=study.id,
            narrative=_FAILURE_NARRATIVE,
            parameter_importance={},
            recommended_config={},
            suggested_followups=[],
            generated_by="local:zero_trials",
        )
    except IntegrityError:
        # Defensive: race against a concurrent boot-scan re-enqueue OR a
        # manual re-run after we already wrote the digest. The advisory
        # lock guards against the in-flight race; this catches the
        # post-commit re-entry. Roll back + return so the caller's outer
        # commit is a no-op.
        await db.rollback()
        logger.info(
            "digest worker: digest already exists (race) — skipping zero-trials write",
            event_type="digest_already_persisted",
            study_id=study.id,
        )
        return
    # DELETE the pending proposal — it points at a non-existent best trial.
    await db.execute(delete(Proposal).where(Proposal.id == proposal.id))
    await db.commit()
    logger.warning(
        "digest worker: zero-successful-trials placeholder persisted; pending proposal deleted",
        event_type="digest_zero_trials",
        study_id=study.id,
        digest_id=digest_id,
    )


# ---------------------------------------------------------------------------
# OpenAI invocation (split out so the structured + degraded paths share the
# call site; the response parsing branches on `structured_output_enabled`).
# ---------------------------------------------------------------------------


async def _call_openai_for_digest(
    *,
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    structured_output_enabled: bool,
) -> tuple[dict[str, Any], int, int]:
    """Single OpenAI chat-completions call.

    Returns ``(parsed, input_tokens, output_tokens)``. ``parsed`` is:
      - ``{"narrative": str, "suggested_followups": list[str]}`` when
        ``structured_output_enabled=True``.
      - ``{"narrative": str, "suggested_followups": []}`` when False — the
        plain-text response is wrapped into the same shape so the caller
        doesn't branch.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_completion_tokens": _MAX_COMPLETION_TOKENS,
    }
    if structured_output_enabled:
        kwargs["response_format"] = DIGEST_RESPONSE_FORMAT
    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    usage = response.usage
    input_tokens = int(usage.prompt_tokens) if usage else 0
    output_tokens = int(usage.completion_tokens) if usage else 0

    if structured_output_enabled:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("digest LLM response is not a JSON object")
        narrative = parsed.get("narrative")
        followups = parsed.get("suggested_followups", [])
        if not isinstance(narrative, str) or not isinstance(followups, list):
            raise ValueError("digest LLM response missing required fields")
        return (
            {"narrative": narrative, "suggested_followups": followups},
            input_tokens,
            output_tokens,
        )

    # Degraded path — content is plain prose. Wrap into the same shape.
    return ({"narrative": content.strip(), "suggested_followups": []}, input_tokens, output_tokens)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


async def generate_digest(ctx: dict[str, Any], study_id: str) -> None:
    """Arq entry point — see module docstring for the 15-step contract."""
    settings = get_settings()
    started_at = time.monotonic()
    factory = get_session_factory()
    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    openai_client: AsyncOpenAI | None = None

    try:
        # Step 1 — Load study; bail on missing / non-completed.
        async with factory() as db:
            study = await repo.get_study(db, study_id)
            if study is None:
                logger.info(
                    "digest worker: study vanished",
                    event_type="digest_study_missing",
                    study_id=study_id,
                )
                return
            if study.status != "completed":
                logger.warning(
                    "digest worker: study not completed; refusing to generate",
                    event_type="digest_invalid_state",
                    error_code="INVALID_STUDY_STATE",
                    study_id=study_id,
                    status=study.status,
                )
                return

            # Step 2 — Pre-LLM idempotency guard (cycle-1 F6).
            existing_digest = await repo.get_digest_for_study(db, study_id)
            if existing_digest is not None:
                logger.info(
                    "digest worker: digest already exists; short-circuiting",
                    event_type="digest_already_persisted",
                    study_id=study_id,
                    digest_id=existing_digest.id,
                )
                return

        # Step 3 — Acquire the advisory lock (cycle-2 F6).
        # Open a NEW session so the lock is xact-scoped to the work-doing
        # transaction. The lock is released automatically on commit/rollback
        # at the end of the `async with factory() as db` block below.
        async with factory() as db:
            async with _acquire_digest_lock(db, study_id) as got_lock:
                if not got_lock:
                    logger.info(
                        "digest worker: another worker holds the digest lock; skipping",
                        event_type="digest_lock_contention",
                        study_id=study_id,
                    )
                    return

                # Re-read inside the lock — avoids a TOCTOU window where the
                # idempotency guard at Step 2 raced against another worker
                # that completed between our Step 2 SELECT and our lock.
                existing = await repo.get_digest_for_study(db, study_id)
                if existing is not None:
                    logger.info(
                        "digest worker: digest landed during lock acquisition; exiting",
                        event_type="digest_already_persisted",
                        study_id=study_id,
                        digest_id=existing.id,
                    )
                    return

                # Step 4 + 5 — Pending proposal + zero-trials short-circuit.
                if study.best_metric is None:
                    await _persist_zero_trials_digest(db, study)
                    return

                # Step 6 — OpenAI key.
                api_key = settings.openai_api_key
                if not api_key:
                    logger.warning(
                        "digest worker: OPENAI_API_KEY not configured; deferring",
                        event_type="digest_openai_not_configured",
                        error_code="OPENAI_NOT_CONFIGURED",
                        study_id=study_id,
                    )
                    return

                # Step 7 — Capability check (mode flag, NOT short-circuit per cycle-3 F2).
                cap = await read_capability_result(redis_client, settings.openai_base_url)
                structured_output_enabled = (
                    cap is not None
                    and cap.structured_output == "ok"
                    and cap.model == settings.openai_model
                )
                if not structured_output_enabled:
                    if cap is None:
                        cause = "cache miss"
                    elif cap.model != settings.openai_model:
                        cause = (
                            f"cached probe model {cap.model!r} != configured "
                            f"OPENAI_MODEL {settings.openai_model!r}"
                        )
                    else:
                        cause = f"structured_output={cap.structured_output!r}"
                    logger.warning(
                        "digest worker: capability degraded; falling back to narrative-only",
                        event_type="digest_capability_fail",
                        error_code="LLM_PROVIDER_INCAPABLE",
                        study_id=study_id,
                        cause=cause,
                    )

                # Step 8 — Model pricing (applies to both paths — cycle-3 F2).
                model = settings.openai_model
                if model not in known_models():
                    logger.warning(
                        "digest worker: model has no pricing entry; aborting",
                        event_type="digest_unknown_pricing",
                        error_code="UNKNOWN_MODEL_PRICING",
                        study_id=study_id,
                        model=model,
                    )
                    return

                # Step 9 — Daily-budget peek (also applies to both paths).
                budget = settings.openai_daily_budget_usd
                if budget > 0:
                    try:
                        current = await peek_daily_total(redis_client)
                    except Exception as exc:  # noqa: BLE001 — defensive
                        logger.warning(
                            "digest worker: budget peek failed; aborting",
                            event_type="digest_budget_peek_failed",
                            study_id=study_id,
                            error=str(exc),
                        )
                        return
                    est_max = estimated_max_call_cost(model)
                    if current + est_max > budget:
                        logger.warning(
                            "digest worker: budget would be breached; aborting",
                            event_type="digest_budget_exceeded",
                            error_code="OPENAI_BUDGET_EXCEEDED",
                            study_id=study_id,
                            current_total_usd=current,
                            estimated_max_usd=est_max,
                            budget_usd=budget,
                        )
                        return

                # Step 10 — Optuna study + parameter_importance.
                # The Optuna study is loaded once via the boot-cached storage
                # in ctx["optuna_storage"] (set up by WorkerSettings.on_startup).
                # Falls back to building one inline if ctx is not populated
                # (e.g. unit/integration tests that exercise generate_digest
                # directly without the WorkerSettings lifecycle).
                storage = ctx.get("optuna_storage")
                if storage is None:
                    from backend.app.eval.optuna_runtime import build_storage

                    storage = build_storage(settings.database_url)
                sampler = build_sampler(study.config, seed=study.config.get("seed"))
                pruner = build_pruner(study.config)
                import asyncio as _asyncio

                optuna_study = await _asyncio.to_thread(
                    get_or_create_study,
                    storage=storage,
                    optuna_study_name=study.optuna_study_name,
                    direction=study.objective.get("direction", "maximize"),
                    sampler=sampler,
                    pruner=pruner,
                )
                try:
                    parameter_importance = await _asyncio.to_thread(
                        optuna.importance.get_param_importances, optuna_study
                    )
                except Exception as exc:  # noqa: BLE001 — small-study edge case
                    logger.warning(
                        "digest worker: get_param_importances raised; using empty map",
                        event_type="digest_importance_failed",
                        study_id=study_id,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    parameter_importance = {}

                # Load the best trial + top-K trials from the app DB.
                from backend.app.db.models import Trial

                best_trial_stmt = (
                    select(Trial)
                    .where(Trial.study_id == study_id)
                    .where(Trial.id == study.best_trial_id)
                )
                best_trial = (await db.execute(best_trial_stmt)).scalar_one_or_none()
                if best_trial is None:
                    # Defensive: study.best_trial_id pointed at a deleted/missing row.
                    # Treat the same as zero-trials: persist the failure narrative.
                    logger.warning(
                        "digest worker: study.best_trial_id resolves to no row; "
                        "treating as zero-trials",
                        event_type="digest_best_trial_missing",
                        study_id=study_id,
                        best_trial_id=study.best_trial_id,
                    )
                    await _persist_zero_trials_digest(db, study)
                    return
                top_stmt = (
                    select(Trial)
                    .where(Trial.study_id == study_id)
                    .where(Trial.status == "complete")
                    .order_by(Trial.primary_metric.desc())
                    .limit(TOP_K_TRIALS)
                )
                top_trials = list((await db.execute(top_stmt)).scalars().all())

                # Step 4 — Locate pending proposal (we need it now, before the
                # LLM call, so the all-dropped sub-case can DELETE it cleanly).
                proposal = await _ensure_pending_proposal(db, study)

                # Step 11 — Deterministic recommended_config + drift handling
                # (cycle-1 F5/F9 + cycle-2 F7).
                template_row = await repo.get_query_template(db, study.template_id)
                if template_row is None:
                    logger.warning(
                        "digest worker: template vanished; aborting",
                        event_type="digest_template_missing",
                        study_id=study_id,
                        template_id=study.template_id,
                    )
                    return
                declared = set((template_row.declared_params or {}).keys())
                best_params: dict[str, Any] = best_trial.params or {}
                recommended_config = {p: v for p, v in best_params.items() if p in declared}
                dropped = sorted(set(best_params.keys()) - declared)

                # All-dropped sub-case (cycle-2 F7) — the recommendation is
                # empty + non-actionable; persist digest + DELETE proposal.
                all_dropped = bool(best_params) and not recommended_config
                if all_dropped:
                    logger.warning(
                        "digest worker: every best-trial param drifted out of the template; "
                        "persisting empty-recommendation digest + deleting pending proposal",
                        event_type="digest_template_drift_all_dropped",
                        study_id=study_id,
                        dropped_count=len(dropped),
                    )

                # Step 12 — Render + LLM call.
                user_prompt = render_digest_user_prompt(
                    study_name=study.name,
                    cluster_name=str(study.cluster_id),  # name lookup deferred to follow-up
                    target=study.target,
                    query_set_name=str(study.query_set_id),
                    query_count=0,  # not load-bearing; populated by future enrichment
                    judgment_list_name=str(study.judgment_list_id),
                    rubric_summary="(see judgment list rubric)",
                    baseline_metric=study.baseline_metric,
                    achieved_metric=study.best_metric,
                    top_trials=_compute_top_trials(top_trials),
                    parameter_importance=parameter_importance,
                    recommended_config=recommended_config,
                    dropped_template_params=dropped,
                    include_recommendation=structured_output_enabled and not all_dropped,
                )
                bundle = load_digest_prompts()
                openai_client = AsyncOpenAI(api_key=api_key, base_url=settings.openai_base_url)
                try:
                    parsed, input_tokens, output_tokens = await _call_openai_for_digest(
                        client=openai_client,
                        model=model,
                        system_prompt=bundle.system_prompt,
                        user_prompt=user_prompt,
                        structured_output_enabled=structured_output_enabled and not all_dropped,
                    )
                except (
                    openai.AuthenticationError,
                    openai.PermissionDeniedError,
                    openai.BadRequestError,
                    openai.NotFoundError,
                ) as exc:
                    logger.warning(
                        "digest worker: persistent OpenAI error; aborting",
                        event_type="digest_openai_error",
                        study_id=study_id,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    return
                except Exception as exc:  # noqa: BLE001 — operational failure
                    logger.warning(
                        "digest worker: LLM call failed; aborting",
                        event_type="digest_llm_failed",
                        study_id=study_id,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    return

                cost_usd = compute_call_cost(model, input_tokens, output_tokens)

                # Step 13 — Merge follow-ups.
                # The capability-fallback (degraded) path persists no
                # follow-ups per spec AC-11 — the LLM didn't generate
                # any, and the deterministic drift-followup is moot
                # because we're also dropping the recommended_config in
                # that path (see Step 14/15).
                followups: list[str] = []
                if structured_output_enabled:
                    if all_dropped:
                        sample = ", ".join(dropped[:5])
                        ellipsis = "..." if len(dropped) > 5 else ""
                        followups.append(
                            f"Best trial used {len(dropped)} params no longer declared "
                            f"on the template ({sample}{ellipsis}). The recommendation is "
                            "empty. Re-add the dropped params to the template or treat "
                            "this study as stale."
                        )
                    elif dropped:
                        followups.append(
                            f"Best trial used params no longer declared on the "
                            f"template: {dropped}. Re-establish them or accept the "
                            "filtered config."
                        )
                    followups.extend(parsed.get("suggested_followups", []) or [])
                    followups = followups[:5]

                # Step 14 — Persisted recommended_config + config_diff.
                # Per spec AC-11, the capability-fallback path persists
                # recommended_config={} (and consequently config_diff={})
                # AND leaves the pending proposal untouched. The
                # all-dropped sub-case (cycle-2 F7) likewise persists
                # recommended_config={} but DELETEs the proposal.
                metric_delta = _compute_metric_delta(study)
                template_defaults = compute_default_params(template_row)
                if structured_output_enabled and not all_dropped:
                    persisted_recommended_config = recommended_config
                    config_diff = {
                        p: {"from": template_defaults.get(p), "to": v}
                        for p, v in recommended_config.items()
                    }
                else:
                    persisted_recommended_config = {}
                    config_diff = {}

                # Step 15 — persist FIRST (cycle-2 C2-F3), then record cost.
                digest_id = str(uuid_utils.uuid7())
                try:
                    await repo.create_digest(
                        db,
                        id=digest_id,
                        study_id=study_id,
                        narrative=parsed["narrative"],
                        parameter_importance=parameter_importance,
                        recommended_config=persisted_recommended_config,
                        suggested_followups=followups,
                        generated_by=f"openai:{model}",
                    )
                except IntegrityError:
                    # Race against another worker that finished between our
                    # lock acquisition and now (extremely rare — we hold
                    # the advisory lock — but defensive). Roll back + log.
                    await db.rollback()
                    logger.info(
                        "digest worker: UNIQUE on digests.study_id fired; another worker won",
                        event_type="digest_already_persisted",
                        study_id=study_id,
                    )
                    return

                if all_dropped:
                    # All-dropped: DELETE the pending proposal — non-actionable.
                    await db.execute(delete(Proposal).where(Proposal.id == proposal.id))
                elif not structured_output_enabled:
                    # Capability-fallback (degraded) path per spec AC-11:
                    # pending proposal stays untouched. Skip the UPDATE.
                    pass
                else:
                    # Standard / partial-drift: conditional UPDATE on the
                    # pending proposal (cycle-3 F4 — benign no-op when the
                    # operator rejected the proposal mid-LLM-call).
                    updated = await repo.update_proposal_for_digest(
                        db,
                        proposal.id,
                        config_diff=config_diff,
                        metric_delta=metric_delta,
                    )
                    if updated is None:
                        logger.info(
                            "digest worker: pending proposal no longer pending; "
                            "digest persisted but proposal not updated",
                            event_type="digest_proposal_no_longer_pending",
                            study_id=study_id,
                            proposal_id=proposal.id,
                        )
                await db.commit()

                # Post-commit: record cost (Redis flap is recoverable).
                new_total = await _safe_record_cost(redis_client, cost_usd)
                logger.info(
                    "digest worker: complete",
                    event_type="digest_complete",
                    study_id=study_id,
                    digest_id=digest_id,
                    proposal_id=proposal.id,
                    model=model,
                    structured_output_enabled=structured_output_enabled and not all_dropped,
                    template_drift_dropped=len(dropped),
                    all_dropped=all_dropped,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    running_total_usd=new_total,
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
    finally:
        if openai_client is not None:
            try:
                await openai_client.close()
            except Exception:  # noqa: BLE001 — defensive
                logger.debug("openai client close raised", exc_info=True)
        try:
            await redis_client.aclose()
        except Exception:  # noqa: BLE001 — defensive
            logger.debug("redis close raised", exc_info=True)


__all__ = [
    "DIGEST_RESPONSE_FORMAT",
    "DIGEST_RESPONSE_SCHEMA",
    "TOP_K_TRIALS",
    "generate_digest",
]
