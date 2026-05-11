"""Study orchestrator Arq jobs (feat_study_lifecycle Phase 2, Story 2.1 + 2.3).

``start_study`` is the long-running per-study Arq job that:

1. Transitions the study ``queued → running`` via the service layer.
2. Initializes / loads the Optuna study via the boot-cached ``RDBStorage``.
3. Polls every ``_REPLENISH_TICK_S`` to:

   - Read fresh study status (cancel detection).
   - Aggregate trials (stop-condition + consecutive-failure detection).
   - Replenish open Optuna trial slots up to ``parallelism`` — each
     replenishment ``ask()`` + ``apply_search_space()`` is done from this
     side (per ``infra_optuna_eval`` spec §11 worker contract), then
     ``run_trial(study_id, optuna_trial_number)`` is enqueued.

4. On stop-condition fire calls ``services.study_state.complete_study`` AND
   atomically inserts a ``proposals`` row with ``status='pending'`` in the
   same transaction (C3-F1 cycle-3 fix — the proposal IS the durable
   digest handoff; the Arq enqueue is a fast-path accelerator).

The polling loop opens a fresh ``AsyncSession`` per tick (C3-F2 cycle-3
fix — avoids holding a checked-out connection across ``asyncio.sleep``).
The replenishment block is protected by ``pg_try_advisory_xact_lock``
keyed on ``study_id`` so two concurrent orchestrators don't both ``ask()``
for the same study.

``resume_study`` is a thin wrapper that calls ``start_study`` — the resume
path is built-in via the idempotent ``services.study_state.start_study``
on a ``running`` study (Phase 2 Story 1.3 / FR-5).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import optuna
import structlog
import uuid_utils
from arq.connections import ArqRedis, RedisSettings, create_pool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.models import Trial
from backend.app.db.repo.trial import TrialsSummary, aggregate_trials_summary
from backend.app.db.session import get_session_factory
from backend.app.domain.study.search_space import SearchSpace, apply_search_space
from backend.app.eval.optuna_runtime import build_pruner, build_sampler, get_or_create_study
from backend.app.services import study_state

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_REPLENISH_TICK_S = 1.0
"""Spec §19 decision log: orchestrator polls every 1s."""

_DRAIN_TIMEOUT_S = 30.0
"""Spec FR-4 cancel path: wait up to 30s for in-flight trials to terminate."""

_CONSECUTIVE_FAILURE_THRESHOLD = 5
"""Spec AC-5: study transitions to ``failed`` after 5 consecutive trial
failures. Counted as: the most recent 5 terminal trials (ordered by
``optuna_trial_number DESC``) are all ``status='failed'``. Any non-failed
trial in that window resets the count."""


# ---------------------------------------------------------------------------
# start_study — the Arq job
# ---------------------------------------------------------------------------


async def start_study(ctx: dict[str, Any], study_id: str) -> None:
    """Orchestrator job — see module docstring.

    Idempotent + restart-safe (FR-5): if called on an already-running study
    (resume path), skips the queued→running transition and replenishes
    from the current in-flight count instead.

    Failure surface:

    * Trial-level failures (per ``infra_optuna_eval``'s ``run_trial``) are
      absorbed — failed ``trials`` rows accumulate; the study continues.
    * After 5 consecutive failed trials, the orchestrator calls
      ``fail_study`` with
      ``failed_reason="5 consecutive trial failures"``.
    * Orchestrator-internal ``OperationalError`` re-raises for Arq retry;
      a fresh ``start_study`` invocation resumes via the running-study
      path.
    """
    session_factory = get_session_factory()
    arq_pool: ArqRedis = ctx.get("arq_pool") or await create_pool(
        RedisSettings.from_dsn(get_settings().redis_url)
    )

    # A. Entry transition — short session.
    #
    # Observable entry states:
    #   queued        → transition to running
    #   running       → idempotent (resume path, FR-5)
    #   cancelled     → user cancelled between POST /studies and dispatch
    #   completed/failed → possible after Arq retry; same exit
    async with session_factory() as db:
        try:
            study = await study_state.start_study(db, study_id)
            await db.commit()
        except study_state.InvalidStateTransition:
            await db.rollback()
            current = await repo.get_study(db, study_id)
            logger.info(
                "orchestrator entry transition lost — study no longer queued",
                event_type="orchestrator_exit",
                study_id=study_id,
                final_status=current.status if current else "deleted",
            )
            return
        except study_state.StudyNotFound:
            logger.warning(
                "study deleted before start_study job ran",
                event_type="orchestrator_exit",
                study_id=study_id,
                final_status="deleted",
            )
            return

    # B. Initialize / load the Optuna study via boot-cached storage.
    storage = ctx["optuna_storage"]
    sampler = build_sampler(study.config, seed=study.config.get("seed"))
    pruner = build_pruner(study.config)
    optuna_study = await asyncio.to_thread(
        get_or_create_study,
        storage=storage,
        optuna_study_name=study.optuna_study_name,
        direction=study.objective["direction"],
        sampler=sampler,
        pruner=pruner,
    )

    # C. Parse search_space once (Pydantic validator catches malformed JSON;
    # API create-time validation should have already caught this — the
    # exception path here re-raises for Arq retry, which is a no-op since
    # the JSON won't change on retry).
    space = SearchSpace.model_validate(study.search_space)

    # D. Polling loop — fresh session per tick (C3-F2 cycle-3 fix).
    settings = get_settings()
    parallelism: int = study.config.get("parallelism", settings.studies_default_parallelism)
    max_trials: int | None = study.config.get("max_trials")
    time_budget_min: float | None = study.config.get("time_budget_min")
    # Per-trial timeout fallback (Story 1.5): used by ``run_trial``'s
    # adapter call to bound the engine query. Arq's `enqueue_job` doesn't
    # accept a per-job timeout (the only supported control is the
    # function-level `arq.func(timeout=...)` registered in WorkerSettings);
    # so we don't pass it here. Wiring this into the adapter `search_batch`
    # timeout is tracked at infra_per_trial_timeout/idea.md.
    _trial_timeout_s: int = study.config.get("trial_timeout_s", settings.studies_default_timeout_s)
    del _trial_timeout_s  # consumed by infra_per_trial_timeout follow-up
    started_at_floor = study.started_at or datetime.now(UTC)

    while True:
        async with session_factory() as db:
            # 1. Fresh status read (cancel detection).
            current = await repo.get_study(db, study_id)
            if current is None or current.status != "running":
                if current is not None and current.status == "cancelled":
                    await _drain_in_flight(optuna_study)
                logger.info(
                    "orchestrator exit",
                    event_type="orchestrator_exit",
                    study_id=study_id,
                    final_status=current.status if current else "deleted",
                )
                return

            # 2. Trials summary (one query).
            summary = await aggregate_trials_summary(db, study_id)
            terminal = summary.complete + summary.failed + summary.pruned

            # 3. Consecutive-failure detection (AC-5) FIRST. If the most
            # recent N trials all failed, the study is `failed` — even
            # if max_trials would also fire on this tick (e.g.,
            # max_trials=5 with all 5 failed: ``failed`` is the correct
            # terminal, not ``completed`` with best_metric=None). C3-F1
            # GPT-5.5 cycle-3 fix.
            if await _last_n_all_failed(db, study_id, n=_CONSECUTIVE_FAILURE_THRESHOLD):
                try:
                    await study_state.fail_study(
                        db,
                        study_id,
                        failed_reason="5 consecutive trial failures",
                    )
                    await db.commit()
                    logger.warning(
                        "study failed",
                        event_type="stop_condition_fired",
                        study_id=study_id,
                        reason="consecutive_failures",
                    )
                except study_state.InvalidStateTransition:
                    # Spec §11 cancel-race tolerance.
                    await db.rollback()
                    logger.info(
                        "consecutive-failure transition lost race; exiting",
                        event_type="orchestrator_race_lost",
                        study_id=study_id,
                    )
                return

            # 4. Stop conditions — each evaluated only when its key is set.
            if max_trials is not None and terminal >= max_trials:
                await _stop(db, arq_pool, study_id, summary, reason="max_trials_reached")
                return
            if time_budget_min is not None:
                elapsed = datetime.now(UTC) - started_at_floor
                if elapsed >= timedelta(minutes=time_budget_min):
                    await _stop(db, arq_pool, study_id, summary, reason="time_budget_exceeded")
                    return

        # 5. Replenishment — short session, xact-scoped advisory lock.
        async with session_factory() as db:
            async with _try_replenish_xact_lock(db, study_id) as got_lock:
                if got_lock:
                    in_flight_count = await _count_in_flight(optuna_study)
                    total_allocated = await asyncio.to_thread(lambda: len(optuna_study.trials))
                    slots_open = parallelism - in_flight_count
                    if max_trials is not None:
                        slots_open = min(slots_open, max_trials - total_allocated)
                    for _ in range(max(0, slots_open)):
                        trial = await asyncio.to_thread(optuna_study.ask)
                        await asyncio.to_thread(apply_search_space, trial, space)
                        await arq_pool.enqueue_job("run_trial", study_id, trial.number)
                        logger.info(
                            "trial replenished",
                            event_type="trial_replenished",
                            study_id=study_id,
                            optuna_trial_number=trial.number,
                        )
                    # Commit so the xact-lock releases promptly.
                    await db.commit()
                else:
                    logger.debug(
                        "replenish lock held by another orchestrator; skipping tick",
                        event_type="replenish_lock_contention",
                        study_id=study_id,
                    )

        await asyncio.sleep(_REPLENISH_TICK_S)


async def resume_study(ctx: dict[str, Any], study_id: str) -> None:
    """Resume an orchestrator loop after worker restart (Story 2.3 / FR-5).

    Thin wrapper — ``start_study`` already handles the resume path
    (``services.study_state.start_study`` is idempotent on a running
    study, per Phase 2 Story 1.3).
    """
    await start_study(ctx, study_id)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _last_n_all_failed(db: AsyncSession, study_id: str, *, n: int) -> bool:
    """Return True iff the N most recent terminal trials are ALL failed.

    Ordered by ``optuna_trial_number DESC``. If fewer than ``n`` terminal
    trials exist, returns False (insufficient signal). A single non-failed
    trial in the window resets the streak.
    """
    stmt = (
        select(Trial.status)
        .where(Trial.study_id == study_id)
        .order_by(Trial.optuna_trial_number.desc())
        .limit(n)
    )
    statuses = list((await db.execute(stmt)).scalars().all())
    if len(statuses) < n:
        return False
    return all(s == "failed" for s in statuses)


async def _count_in_flight(optuna_study: optuna.Study) -> int:
    """In-flight = Optuna trials currently RUNNING or WAITING.

    Optuna's ``study.trials`` (synced from RDB) is the authoritative list
    of allocated trials with state. App ``trials`` rows are written only
    at terminal state, so counting from app rows would miss
    ask()-but-not-yet-tell() trials and over-enqueue on the next tick.
    """

    def _sync_count() -> int:
        running = sum(1 for t in optuna_study.trials if t.state == optuna.trial.TrialState.RUNNING)
        waiting = sum(1 for t in optuna_study.trials if t.state == optuna.trial.TrialState.WAITING)
        return running + waiting

    return await asyncio.to_thread(_sync_count)


async def _stop(
    db: AsyncSession,
    arq_pool: ArqRedis,
    study_id: str,
    summary: TrialsSummary,
    *,
    reason: str,
) -> None:
    """Atomic stop-condition fire — atomic completion + pending proposal.

    Completes the study AND inserts the durable pending-proposal row in
    the SAME transaction (C3-F1 fix).

    Cancel-race tolerance: if the user cancelled between the polling-loop
    status read and now, ``complete_study`` raises
    ``InvalidStateTransition`` and we silently exit per spec §11.

    The Arq enqueue of ``generate_digest`` is a fast-path accelerator
    only; the pending proposal row IS the durable handoff and will be
    picked up by ``feat_digest_proposal``'s boot-time scan when that
    feature ships.
    """
    try:
        await study_state.complete_study(
            db,
            study_id,
            best_metric=summary.best_primary_metric,
            best_trial_id=summary.best_trial_id,
            stop_reason=reason,
        )
        # Re-read the study row for cluster_id + template_id (FK targets
        # on the proposal). complete_study returns the row, but we already
        # have the post-mutation state via that return value — call
        # repo.get_study to re-attach a fresh read so the FK lookups
        # don't fight the ORM's identity map.
        study = await repo.get_study(db, study_id)
        if study is not None:
            await repo.create_proposal(
                db,
                id=str(uuid_utils.uuid7()),
                study_id=study_id,
                study_trial_id=summary.best_trial_id,
                cluster_id=study.cluster_id,
                template_id=study.template_id,
                config_diff={},
                metric_delta=None,
                status="pending",
            )
        await db.commit()
    except study_state.InvalidStateTransition:
        await db.rollback()
        logger.info(
            "stop-condition transition lost race; exiting orchestrator loop",
            event_type="orchestrator_race_lost",
            study_id=study_id,
            attempted_reason=reason,
        )
        return

    # Best-effort fast-path digest enqueue.
    try:
        await arq_pool.enqueue_job("generate_digest", study_id)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "digest job enqueue failed; pending proposal row is the durable handoff",
            event_type="digest_enqueue_failed",
            study_id=study_id,
            error=str(exc),
        )
    logger.info(
        "stop condition fired",
        event_type="stop_condition_fired",
        study_id=study_id,
        reason=reason,
        best_metric=summary.best_primary_metric,
    )


@asynccontextmanager
async def _try_replenish_xact_lock(db: AsyncSession, study_id: str) -> AsyncIterator[bool]:
    """Try to acquire a Postgres xact-scoped advisory lock keyed by study_id.

    Two concurrent orchestrators on the same study must not both observe
    the same in-flight count and both ``ask()``. ``pg_try_advisory_xact_lock``
    serializes the count + ask block per study; losers skip this tick.

    Transaction-scoped: commit/rollback releases automatically — no
    explicit ``pg_advisory_unlock``.

    Lock key: first 8 bytes of ``blake2b(study_id)`` as a signed 64-bit
    int (Postgres advisory locks take a bigint).
    """
    lock_key = int.from_bytes(
        hashlib.blake2b(study_id.encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    acquired = (
        await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key})
    ).scalar_one()
    yield bool(acquired)


async def _drain_in_flight(optuna_study: optuna.Study) -> None:
    """Wait for in-flight Optuna trials to terminate (FR-4 cancel drain).

    Bound by ``_DRAIN_TIMEOUT_S``.

    Snapshot the currently-RUNNING/WAITING Optuna trial numbers, then
    poll every 1s. Return when all snapshotted numbers are terminal
    (COMPLETE/FAIL/PRUNED), OR when the 30s budget expires.

    The orchestrator does NOT actively cancel in-flight workers —
    ``run_trial`` is brief (~200ms-2s) and completes naturally. The drain
    just waits so the cancel state isn't observed mid-trial-write.
    """
    snapshot_numbers = await asyncio.to_thread(
        lambda: {
            t.number
            for t in optuna_study.trials
            if t.state in (optuna.trial.TrialState.RUNNING, optuna.trial.TrialState.WAITING)
        }
    )
    if not snapshot_numbers:
        return
    deadline = asyncio.get_event_loop().time() + _DRAIN_TIMEOUT_S

    while True:
        terminal_now = await asyncio.to_thread(
            lambda: {
                t.number
                for t in optuna_study.trials
                if t.number in snapshot_numbers and t.state.is_finished()
            }
        )
        if terminal_now >= snapshot_numbers:
            return
        if asyncio.get_event_loop().time() >= deadline:
            logger.warning(
                "drain timed out — some in-flight trials still RUNNING",
                event_type="drain_timeout",
                still_pending=sorted(snapshot_numbers - terminal_now),
            )
            return
        await asyncio.sleep(1.0)


__all__ = [
    "resume_study",
    "start_study",
]
