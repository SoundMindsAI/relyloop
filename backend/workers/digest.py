# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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
from typing import Any, cast

import openai
import optuna
import optuna.importance
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
from backend.app.domain.study.followups import (
    FollowupItem,
    SwapTemplateFollowup,
    TextFollowup,
    parse_followup_list,
    serialize_followup_list,
    truncate_validation_error,
)
from backend.app.domain.study.search_space import InvalidSearchSpaceError
from backend.app.domain.study.template_defaults import compute_default_params
from backend.app.domain.study.template_swap import (
    remap_search_space_for_swap_target,
)
from backend.app.eval.optuna_runtime import build_pruner, build_sampler, get_or_create_study
from backend.app.llm.budget_gate import peek_daily_total
from backend.app.llm.capability_check import read_capability_result
from backend.app.llm.cost_model import (
    compute_call_cost,
    estimated_max_call_cost,
    known_models,
)
from backend.app.llm.digest_prompt import load_digest_prompts, render_digest_user_prompt
from backend.app.services.study_confidence import fetch_study_confidence
from backend.app.services.study_convergence import fetch_study_convergence
from backend.workers.helpers import safe_record_cost

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOP_K_TRIALS = 10
"""Top-N trials passed to the LLM in the prompt (per spec §11 token budget)."""


_PARAM_IMPORTANCE_EXPECTED_EXCEPTIONS: tuple[type[BaseException], ...] = (ValueError,)
"""Exceptions that ``optuna.importance.get_param_importances`` legitimately raises.

Audited via parametrized unit tests at
``backend/tests/unit/workers/test_digest_importance_audit.py`` against three
edge cases — zero-completed-trials, single-trial, all-pruned — all of which
raise ``ValueError`` with documented messages ("Cannot evaluate parameter
importances without completed trials" / "...with only a single trial").
Exceptions NOT in this tuple (e.g., ``ImportError`` from a missing optional
dep like scikit-learn — the canonical PR #92 regression — or ``RuntimeError``
from a misconfigured Optuna RDB) take the louder ERROR-level fallback path in
:func:`_compute_param_importance` so the regression doesn't silently ship
``{}`` again. See ``chore_digest_worker_narrow_except`` idea for the full
audit + fork decisions.
"""


def _compute_param_importance(optuna_study: optuna.Study, *, study_id: str) -> dict[str, float]:
    """Compute parameter importance with two-tier fallback.

    * Allowlisted exceptions (per ``_PARAM_IMPORTANCE_EXPECTED_EXCEPTIONS``) →
      log ``digest_importance_failed`` at WARN, return ``{}``. These are the
      benign small-study cases the digest can gracefully degrade through.
    * Anything else → log ``digest_importance_failed_unexpected`` at ERROR,
      return ``{}``. The digest still ships (soft-fail), but the ERROR-level
      event_type makes the regression visible to ``make logs`` / MVP2+ Langfuse
      alerting instead of silently degrading.

    Both paths return ``{}`` to preserve the existing caller contract; only the
    signal-loudness differs.

    Extracted from the inline try/except at the Step 10 call site to make the
    routing logic unit-testable without the surrounding ``generate_digest`` DB
    + OpenAI fixture chain (per ``chore_digest_worker_narrow_except`` idea
    Story 1 + Story 2).
    """
    try:
        # optuna's stub returns Any; the documented contract is dict[str, float]
        # (param name → normalized importance score). Cast at the boundary.
        result = optuna.importance.get_param_importances(optuna_study)
        return cast(dict[str, float], result)
    except _PARAM_IMPORTANCE_EXPECTED_EXCEPTIONS as exc:
        logger.warning(
            "digest worker: get_param_importances raised; using empty map",
            event_type="digest_importance_failed",
            study_id=study_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {}
    except Exception as exc:  # noqa: BLE001 — unexpected; surfaces as ERROR
        # exc_info=True captures the traceback into structlog so operators
        # can root-cause unexpected regressions like the PR #92 ImportError.
        # Only on the unexpected path — allowlisted exceptions are benign
        # and don't need traceback noise.
        logger.error(
            "digest worker: get_param_importances raised UNEXPECTEDLY; using empty map",
            event_type="digest_importance_failed_unexpected",
            study_id=study_id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return {}


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
#
# feat_digest_executable_followups Story 2.1 — suggested_followups is now an
# array of {kind, rationale, search_space_json} objects. The discriminator
# is ``kind`` ∈ {narrow, widen, text}. To stay within OpenAI's strict-mode
# JSON schema constraints (which forbid open-ended object subschemas like
# the inner ``SearchSpace.params`` map with arbitrary param-name keys), we
# ship ``search_space`` to the LLM as ``search_space_json`` — a string
# carrying the JSON-encoded SearchSpace body for narrow/widen items, and
# an empty string for text items. The worker parses + validates
# ``search_space_json`` through ``parse_followup_list``; invalid JSON or
# invalid SearchSpace contents downgrade the item to ``text`` per the
# defensive parser contract. Capability-degraded path persists ``[]``
# per D-27.
DIGEST_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "suggested_followups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["narrow", "widen", "text", "swap_template"],
                    },
                    "rationale": {"type": "string"},
                    "search_space_json": {
                        "type": "string",
                        "description": (
                            "JSON-encoded SearchSpace body for "
                            "narrow/widen/swap_template items; empty "
                            "string for text items. Worker parses + "
                            "validates via "
                            "backend.app.domain.study.followups.parse_followup_list."
                        ),
                    },
                    "template_id": {
                        "type": "string",
                        "description": (
                            "36-char query_templates.id for swap_template "
                            "items; empty string for other kinds (worker "
                            "drops the field before Pydantic dispatch per "
                            "feat_digest_executable_followups_swap_template "
                            "spec D-29/D-20)."
                        ),
                    },
                },
                "required": [
                    "kind",
                    "rationale",
                    "search_space_json",
                    "template_id",
                ],
                "additionalProperties": False,
            },
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


# Rationale-prefix mapping for swap_template downgrades (Story 2.3, FR-8).
# Keys mirror the four ``reason`` codes emitted on
# ``digest_followup_validation_downgraded`` WARN events; the prefix lands on
# the resulting :class:`TextFollowup.rationale` so the operator-facing card
# explains why the suggestion was demoted to text.
_SWAP_DOWNGRADE_PREFIXES: dict[str, str] = {
    "not_found": "swap_template target template not found",
    "same_as_parent": "swap_template target is the same as the parent template",
    "engine_type_mismatch": "swap_template target engine_type differs from parent cluster",
    "remap_invalid_search_space": "swap_template remap produced an invalid search_space",
}


def _downgrade_swap_template_to_text(
    item: SwapTemplateFollowup,
    reason: str,
    *,
    validation_error: str = "",
) -> TextFollowup:
    """Build the downgrade :class:`TextFollowup` for a failed swap_template item.

    Per spec FR-8 the prefix references the reason code so runbooks can grep
    by reason. The validation_error tail (truncated via
    :func:`truncate_validation_error`) preserves the original LLM rationale
    + any underlying Pydantic message.
    """
    prefix_core = _SWAP_DOWNGRADE_PREFIXES.get(reason, f"swap_template downgrade: {reason}")
    body = f"[validation failed: {prefix_core}: {item.template_id}]"
    if validation_error:
        body = f"{body} ({truncate_validation_error(validation_error)})"
    return TextFollowup(
        kind="text",
        rationale=f"{body} {item.rationale}",
        search_space=None,
    )


async def _apply_swap_template_remap(
    parsed_followups: list[FollowupItem],
    *,
    db: AsyncSession,
    parent_template_id: str,
    parent_declared_params: dict[str, str],
    parent_engine_type: str,
    study_id: str,
    proposal_id: str,
) -> list[FollowupItem]:
    """Resolve + remap each ``swap_template`` followup in-place.

    Runs AFTER the ``[:5]`` truncation (per AC-15) so we never spend a DB
    lookup on an item that wouldn't have been persisted anyway. Per-target
    template lookups are cached for the lifetime of the call (a single
    digest may emit multiple swap_template items pointing at the same
    target — rare but legal).

    Downgrade-reason cascade (FR-8):

    1. ``not_found``         — :func:`repo.get_query_template` returned None.
    2. ``same_as_parent``    — target id matches the parent study's template.
    3. ``engine_type_mismatch`` — target engine differs from parent cluster.
    4. ``remap_invalid_search_space`` — :func:`remap_search_space_for_swap_target`
       raised :class:`InvalidSearchSpaceError`.

    On success, the item's ``search_space`` is replaced with the merged
    :class:`SearchSpace` and an INFO ``digest_followup_swap_template_remapped``
    event is emitted with the 4 sorted name lists.
    """
    target_template_cache: dict[str, Any] = {}
    final_followups: list[FollowupItem] = []
    for idx, item in enumerate(parsed_followups):
        if not isinstance(item, SwapTemplateFollowup):
            final_followups.append(item)
            continue

        # Lazily resolve the target template (cached per call).
        sentinel = object()
        target = target_template_cache.get(item.template_id, sentinel)
        if target is sentinel:
            target = await repo.get_query_template(db, item.template_id)
            target_template_cache[item.template_id] = target

        reason: str | None = None
        validation_error_tail = ""

        if target is None:
            reason = "not_found"
        elif target.id == parent_template_id:
            reason = "same_as_parent"
        elif target.engine_type != parent_engine_type:
            reason = "engine_type_mismatch"

        if reason is not None:
            downgraded = _downgrade_swap_template_to_text(item, reason)
            logger.warning(
                "digest worker: swap_template followup downgraded",
                event_type="digest_followup_validation_downgraded",
                study_id=study_id,
                proposal_id=proposal_id,
                followup_index=idx,
                original_kind="swap_template",
                reason=reason,
                validation_error=truncate_validation_error(downgraded.rationale),
            )
            final_followups.append(downgraded)
            continue

        # Happy path — call the remap helper, downgrade on InvalidSearchSpaceError.
        try:
            result = remap_search_space_for_swap_target(
                parent_declared_params=parent_declared_params,
                swap_target_declared_params=target.declared_params or {},
                llm_search_space=item.search_space,
            )
        except InvalidSearchSpaceError as exc:
            validation_error_tail = str(exc)
            downgraded = _downgrade_swap_template_to_text(
                item,
                "remap_invalid_search_space",
                validation_error=validation_error_tail,
            )
            logger.warning(
                "digest worker: swap_template remap failed",
                event_type="digest_followup_validation_downgraded",
                study_id=study_id,
                proposal_id=proposal_id,
                followup_index=idx,
                original_kind="swap_template",
                reason="remap_invalid_search_space",
                validation_error=truncate_validation_error(validation_error_tail),
            )
            final_followups.append(downgraded)
            continue

        # Replace search_space with merged result; emit INFO.
        merged: SwapTemplateFollowup = item.model_copy(update={"search_space": result.search_space})
        logger.info(
            "digest worker: swap_template remap success",
            event_type="digest_followup_swap_template_remapped",
            study_id=study_id,
            proposal_id=proposal_id,
            followup_index=idx,
            target_template_id=target.id,
            trusted_intersection_param_names=result.trusted_intersection_param_names,
            disjoint_fill_param_names=result.disjoint_fill_param_names,
            dropped_parent_param_names=result.dropped_parent_param_names,
            ignored_llm_param_names=result.ignored_llm_param_names,
        )
        final_followups.append(merged)

    return final_followups


async def _safe_record_cost(redis: Redis, cost_usd: float) -> float | None:
    """Record cost, swallowing transient Redis failures (digest worker voice)."""
    return await safe_record_cost(
        redis,
        cost_usd,
        logger=logger,
        log_message="digest worker: record_cost failed (budget telemetry only)",
        event_type="digest_record_cost_failed",
    )


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
        # feat_digest_executable_followups Story 2.1: per-item shape is
        # enforced upstream by the JSON-schema (response_format) and
        # downstream by parse_followup_list — the worker only verifies
        # the top-level types here.
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
                parameter_importance = await _asyncio.to_thread(
                    _compute_param_importance, optuna_study, study_id=study_id
                )

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
                # FR-11: exclude baseline from the top-10 list — the digest
                # surfaces Optuna's exploration; baseline is reported
                # separately via study.baseline_metric.
                top_stmt = (
                    select(Trial)
                    .where(Trial.study_id == study_id)
                    .where(Trial.is_baseline.is_(False))
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
                # Fetch the human-readable names + query_count + rubric so
                # the operator-facing narrative renders names instead of
                # raw UUIDs (final-review F2 from GPT-5.5).
                cluster_row = await repo.get_cluster(db, study.cluster_id)
                query_set_row = await repo.get_query_set(db, study.query_set_id)
                jl_row = await repo.get_judgment_list(db, study.judgment_list_id)
                # feat_digest_executable_followups_swap_template Story 2.3
                # (FR-6 / FR-7): fetch the catalogue of alternative templates
                # registered against the parent cluster's engine_type, minus
                # the parent template itself. Empty / single-template installs
                # yield ``catalogue_payload = None`` so the
                # ``<available_templates>`` jinja block is omitted (AC-13).
                catalogue_payload: list[dict[str, Any]] | None = None
                if cluster_row is not None:
                    catalogue_rows = await repo.list_query_templates(
                        db,
                        engine_type=cluster_row.engine_type,
                        limit=200,
                    )
                    catalogue_payload = [
                        {
                            "id": row.id,
                            "name": row.name,
                            "version": row.version,
                            "declared_params": row.declared_params or {},
                        }
                        for row in catalogue_rows
                        if row.id != study.template_id
                    ]
                    if not catalogue_payload:
                        catalogue_payload = None
                qs_count = (
                    await repo.count_queries_in_set(db, study.query_set_id)
                    if query_set_row is not None
                    else 0
                )
                cluster_name = cluster_row.name if cluster_row else study.cluster_id
                query_set_name = query_set_row.name if query_set_row else study.query_set_id
                judgment_list_name = jl_row.name if jl_row else study.judgment_list_id
                rubric_text = (jl_row.rubric or "") if jl_row else ""
                # Truncate rubric for the prompt (operators may set a
                # long rubric; we want a summary line, not the whole body).
                rubric_summary = rubric_text[:280] + ("..." if len(rubric_text) > 280 else "")
                if not rubric_summary:
                    rubric_summary = "(see judgment list rubric)"
                # feat_pr_metric_confidence Story 1.6 (FR-6): assemble the
                # per-study ConfidenceShape and serialize for the jinja
                # ``<confidence>`` + ``<per_query_outcomes>`` blocks. Returns
                # ``None`` on degraded paths (FR-7) so the blocks skip cleanly.
                confidence_shape = await fetch_study_confidence(db, study)
                confidence_payload = (
                    confidence_shape.model_dump() if confidence_shape is not None else None
                )
                # feat_study_convergence_indicator Story 5.1 (FR-6): assemble
                # the per-study StudyConvergenceShape and serialize for the
                # jinja ``<convergence>`` block. Returns ``None`` whole-object
                # on in-flight studies, sub-MIN trial counts, or any graceful-
                # degrade path from FR-3; the block skips cleanly via
                # ``{% if convergence %}`` in the template.
                convergence_shape = await fetch_study_convergence(db, study)
                convergence_payload = (
                    convergence_shape.model_dump() if convergence_shape is not None else None
                )
                user_prompt = render_digest_user_prompt(
                    study_name=study.name,
                    cluster_name=cluster_name,
                    target=study.target,
                    query_set_name=query_set_name,
                    query_count=qs_count,
                    judgment_list_name=judgment_list_name,
                    rubric_summary=rubric_summary,
                    baseline_metric=study.baseline_metric,
                    achieved_metric=study.best_metric,
                    top_trials=_compute_top_trials(top_trials),
                    parameter_importance=parameter_importance,
                    recommended_config=recommended_config,
                    dropped_template_params=dropped,
                    include_recommendation=structured_output_enabled and not all_dropped,
                    confidence=confidence_payload,
                    convergence=convergence_payload,
                    # feat_digest_executable_followups Story 2.2 — the LLM
                    # needs the parent search-space to author narrow / widen
                    # follow-ups (FR-8).
                    parent_search_space=study.search_space,
                    # feat_digest_executable_followups_swap_template Story
                    # 2.3 (FR-6 / FR-7): pass the parent template's
                    # declared_params + the catalogue so the LLM can author
                    # ``swap_template`` follow-ups grounded in real
                    # template IDs.
                    parent_template_declared_params=(template_row.declared_params or {}),
                    available_templates=catalogue_payload,
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
                # feat_digest_executable_followups Story 2.1: followups are
                # now structured dicts (FollowupItem shape). The capability-
                # fallback (degraded) path persists no follow-ups per spec
                # AC-11 / D-27 — the LLM didn't generate any, and the
                # deterministic drift-followup is moot because we're also
                # dropping the recommended_config in that path. The drift
                # item is built as a text-kind followup and prepended to the
                # LLM list; the merged list is validated through
                # parse_followup_list which downgrades any invalid LLM
                # narrow/widen items to text (or drops them outright).
                followup_dicts: list[dict[str, Any]] = []
                if structured_output_enabled:
                    if all_dropped:
                        sample = ", ".join(dropped[:5])
                        ellipsis = "..." if len(dropped) > 5 else ""
                        followup_dicts.append(
                            {
                                "kind": "text",
                                "rationale": (
                                    f"Best trial used {len(dropped)} params no longer declared "
                                    f"on the template ({sample}{ellipsis}). The recommendation is "
                                    "empty. Re-add the dropped params to the template or treat "
                                    "this study as stale."
                                ),
                                "search_space": None,
                            }
                        )
                    elif dropped:
                        followup_dicts.append(
                            {
                                "kind": "text",
                                "rationale": (
                                    f"Best trial used params no longer declared on the "
                                    f"template: {dropped}. Re-establish them or accept the "
                                    "filtered config."
                                ),
                                "search_space": None,
                            }
                        )
                    # feat_digest_executable_followups Story 2.1 — the LLM
                    # ships search_space as a JSON string (search_space_json)
                    # to satisfy OpenAI strict-mode JSON-schema constraints.
                    # Translate to the {kind, rationale, search_space} shape
                    # parse_followup_list expects: decode the JSON string for
                    # narrow/widen/swap_template, drop the field for text.
                    # Bad JSON => search_space stays missing => Pydantic
                    # rejects => parse_followup_list downgrades to text (or
                    # drops). For swap_template, the worker also surfaces
                    # template_id (a uniform string field added in the
                    # DIGEST_RESPONSE_SCHEMA per spec D-20 because OpenAI
                    # strict mode rejects oneOf/if/then on item schemas);
                    # the worker pre-cleans the empty-string sentinel per
                    # spec D-29 before Pydantic dispatch so non-swap kinds
                    # don't trip extra="forbid".
                    for raw_item in parsed.get("suggested_followups", []) or []:
                        if not isinstance(raw_item, dict):
                            followup_dicts.append(raw_item)
                            continue
                        kind = raw_item.get("kind")
                        rationale = raw_item.get("rationale")
                        ss_json = raw_item.get("search_space_json", "")
                        template_id_raw = raw_item.get("template_id", "")
                        if kind in ("narrow", "widen", "swap_template"):
                            try:
                                ss_decoded = json.loads(ss_json) if ss_json else None
                            except (json.JSONDecodeError, TypeError):
                                ss_decoded = None
                            item_dict: dict[str, Any] = {
                                "kind": kind,
                                "rationale": rationale,
                                "search_space": ss_decoded,
                            }
                            if kind == "swap_template":
                                # Surface template_id on the discriminated
                                # variant; parse_followup_list dispatches to
                                # SwapTemplateFollowup which validates it.
                                item_dict["template_id"] = template_id_raw
                            elif template_id_raw != "":
                                # Non-empty template_id on narrow/widen is a
                                # protocol violation: keep the field so
                                # extra="forbid" rejects and the parser
                                # downgrade-decision-table fires (spec D-29).
                                item_dict["template_id"] = template_id_raw
                            followup_dicts.append(item_dict)
                        else:  # text
                            item_dict_text: dict[str, Any] = {
                                "kind": kind,
                                "rationale": rationale,
                                "search_space": None,
                            }
                            if template_id_raw != "":
                                # Non-empty template_id on text = protocol
                                # violation; surface so extra="forbid" + the
                                # downgrade-decision-table catch it.
                                item_dict_text["template_id"] = template_id_raw
                            followup_dicts.append(item_dict_text)

                # Validate + downgrade-or-drop through the defensive parser.
                # proposal.id is in-scope at this point (resolved in Step 7).
                parsed_followups = parse_followup_list(
                    followup_dicts,
                    study_id=study_id,
                    proposal_id=proposal.id,
                )
                parsed_followups = parsed_followups[:5]
                # feat_digest_executable_followups_swap_template Story 2.3
                # (FR-7 / AC-15): truncate-to-5 happens FIRST so a 6th
                # malformed swap_template item never triggers a DB lookup.
                # The remap step runs ONLY on the retained list and
                # downgrades each swap_template item that fails the FR-8
                # cascade (not_found / same_as_parent / engine_type_mismatch
                # / remap_invalid_search_space).
                if cluster_row is not None:
                    parsed_followups = await _apply_swap_template_remap(
                        parsed_followups,
                        db=db,
                        parent_template_id=study.template_id,
                        parent_declared_params=(template_row.declared_params or {}),
                        parent_engine_type=cluster_row.engine_type,
                        study_id=study_id,
                        proposal_id=proposal.id,
                    )
                followups_json = serialize_followup_list(parsed_followups)
                # Per-kind counts for the digest_complete observability log
                # (so operators can spot LLM mode drift without grepping
                # individual WARN events).
                followups_narrow_count = sum(1 for f in parsed_followups if f.kind == "narrow")
                followups_widen_count = sum(1 for f in parsed_followups if f.kind == "widen")
                followups_text_count = sum(1 for f in parsed_followups if f.kind == "text")
                followups_swap_template_count = sum(
                    1 for f in parsed_followups if f.kind == "swap_template"
                )

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
                        # feat_digest_executable_followups Story 2.1: pass
                        # the JSONB-safe list[dict] shape after the
                        # parse-and-downgrade round-trip + serialize_followup_list.
                        suggested_followups=followups_json,
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

                if not structured_output_enabled:
                    # Capability-fallback (degraded) path per spec AC-11:
                    # pending proposal stays untouched. This branch wins
                    # over the all_dropped DELETE — capability failure is
                    # a SYSTEM concern (LLM endpoint), not a TEMPLATE
                    # concern, so the proposal should still be available
                    # to retry once the operator fixes the upstream
                    # capability (final-review F1 from GPT-5.5).
                    pass
                elif all_dropped:
                    # All-dropped: DELETE the pending proposal — non-actionable.
                    await db.execute(delete(Proposal).where(Proposal.id == proposal.id))
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
                    # feat_digest_executable_followups Story 2.1: per-kind
                    # counts so operators can spot LLM mode drift.
                    # feat_digest_executable_followups_swap_template Story
                    # 2.3 adds the fourth count.
                    followups_narrow_count=followups_narrow_count,
                    followups_widen_count=followups_widen_count,
                    followups_text_count=followups_text_count,
                    followups_swap_template_count=followups_swap_template_count,
                )

                # feat_auto_followup_studies Story 2.2 — auto-chain trigger.
                # Fires AFTER:
                #   (a) pending-proposal commit (line 850 above),
                #   (b) _safe_record_cost (line 853 above — parent's budget
                #       delta is now visible to the followup worker's
                #       budget peek), and
                #   (c) the digest_complete success log.
                #
                # The followup worker re-peeks the budget (FR-6) — and we
                # only fire here on the success path, so failure / short-
                # circuit branches of generate_digest don't enqueue a child.
                # Study.status == 'completed' is guaranteed by the gate at
                # line 453 (early-return on anything else).
                #
                # Per FR-1 + D-12: trigger on `is not None` (NOT > 0) so
                # the depth-0 worker-set terminal leaf emits its own
                # auto_followup_depth_exhausted event.
                #
                # Per spec §9 layer-1 idempotency: deterministic _job_id
                # makes Arq drop duplicate deliveries at the queue level.
                # The worker has a layer-2 list_children_of_study backstop.
                #
                # Per cycle-1 finding C1-5: failure-warning events use
                # `digest_followup_*` event_type prefixes (NOT `auto_followup_*`)
                # so the FR-9 8-event catalog stays exact.
                auto_depth = study.config.get("auto_followup_depth")
                if auto_depth is not None:
                    arq_pool = ctx.get("arq_pool")
                    if arq_pool is None:
                        logger.warning(
                            "digest worker: arq_pool missing in ctx; cannot enqueue auto-followup",
                            event_type="digest_followup_enqueue_pool_missing",
                            study_id=study_id,
                        )
                    else:
                        try:
                            await arq_pool.enqueue_job(
                                "enqueue_followup_study",
                                study_id,
                                _job_id=f"enqueue_followup_study:{study_id}",
                            )
                        except Exception as exc:  # noqa: BLE001 — best-effort
                            # Mirrors orchestrator.py:452-460 digest_enqueue_failed
                            # pattern. Chain ends here; the parent's proposal
                            # is still created. Operator can re-trigger via
                            # shell if needed.
                            logger.warning(
                                "digest worker: auto-followup enqueue failed; chain ends here",
                                event_type="digest_followup_enqueue_failed",
                                study_id=study_id,
                                error=str(exc),
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
