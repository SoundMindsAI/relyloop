"""Arq worker entry point (Phase 2 / infra_optuna_eval / infra_foundation).

Adds feat_study_lifecycle Phase 2 Stories 2.1 / 2.3 on top of the
infra_foundation Story 4.3 + infra_optuna_eval Story 2.3 baseline.

The Compose ``worker`` service starts via ``arq backend.workers.all.WorkerSettings``.

Registered jobs:

* ``run_trial`` — infra_optuna_eval Story 2.3; executes one Optuna trial
  (render → search → score → tell → persist trials row).
* ``start_study`` — feat_study_lifecycle Phase 2 Story 2.1; long-running
  per-study orchestrator that runs the ask/tell + replenish + stop-condition
  loop.
* ``resume_study`` — feat_study_lifecycle Phase 2 Story 2.3; thin wrapper
  around ``start_study`` enqueued by the on_startup sweep below (FR-5).
* ``generate_digest`` — feat_study_lifecycle Phase 2 Story 2.1; idempotent
  digest-handoff stub replaced by ``feat_digest_proposal`` later.

The ``on_startup`` hook:

1. Constructs Optuna's ``RDBStorage`` once per worker boot and caches it
   in ``ctx["optuna_storage"]`` (spec FR-1).
2. Constructs a shared Arq pool and caches it in ``ctx["arq_pool"]`` so
   the orchestrator job can enqueue ``run_trial`` / ``generate_digest``
   without re-opening a Redis connection per study.
3. Sweeps ``SELECT id FROM studies WHERE status = 'running'`` and
   enqueues ``resume_study(study_id)`` for each — restart safety per
   FR-5 / AC-4.

Long-running orchestrator jobs are given ``job_timeout=86400`` (24h) on
WorkerSettings so a long ``time_budget_min`` doesn't trigger Arq's
default 5-minute timeout. ``run_trial`` keeps the default (per-trial scope).
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from arq import func
from arq.connections import ArqRedis, RedisSettings, create_pool

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.eval.optuna_runtime import build_storage
from backend.workers.digest_stub import generate_digest
from backend.workers.judgments import generate_judgments_llm
from backend.workers.orchestrator import resume_study, start_study
from backend.workers.trials import run_trial

logger = structlog.get_logger(__name__)

# Spec FR-4: studies can run for up to ``time_budget_min`` (no explicit
# upper bound in MVP1 beyond reasonableness). 24h covers the worst-case
# operator-set budget.
_ORCHESTRATOR_JOB_TIMEOUT_S = 86_400

# Spec FR-2: judgment generation runs one LLM call per query. ~50 queries
# × ~6s per call + retry headroom = comfortable 15-minute ceiling. The Arq
# default (5 min) sits right at the boundary; this gives the worker room
# to finish without an arbitrary kill.
_JUDGMENTS_JOB_TIMEOUT_S = 900


def _build_redis_settings() -> RedisSettings:
    """Parse ``Settings.redis_url`` into Arq's RedisSettings dataclass."""
    return RedisSettings.from_dsn(get_settings().redis_url)


async def on_startup(ctx: dict[str, Any]) -> None:
    """Initialize per-worker resources and resume in-flight studies.

    Three boot-time steps:

    1. Build Optuna RDBStorage (spec FR-1; offloaded to a worker thread
       because construction can open a sync DB connection).
    2. Build a shared ArqRedis pool so the orchestrator job can enqueue
       child jobs without re-opening the pool per study.
    3. Enqueue ``resume_study`` for every currently-running study
       (FR-5 / AC-4). Idempotent against duplicate resume jobs because
       ``start_study`` is a no-op on already-running studies (Story 1.3
       state machine).
    """
    settings = get_settings()
    ctx["optuna_storage"] = await asyncio.to_thread(build_storage, settings.database_url)
    arq_pool: ArqRedis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    ctx["arq_pool"] = arq_pool

    factory = get_session_factory()
    async with factory() as db:
        running_ids = await repo.list_running_study_ids(db)
        # Also pick up studies whose POST /studies committed the row but
        # failed to enqueue (e.g., Arq pool unreachable at API request
        # time). Without this sweep, a queued study would sit forever.
        queued_ids = await repo.list_queued_study_ids(db)
        # feat_llm_judgments Story 2.1: equivalent sweep for judgment
        # generation. Per GPT-5.5 cycle 1 F14 / cycle 2 F1 — covers the
        # case where POST /judgments/generate committed the
        # judgment_lists row but enqueue_job raised (Redis transient).
        generating_judgment_ids = await repo.list_generating_judgment_list_ids(db)
    for sid in running_ids:
        await arq_pool.enqueue_job("resume_study", sid)
        logger.info(
            "study queued for resume",
            event_type="resume_enqueued",
            study_id=sid,
        )
    for sid in queued_ids:
        await arq_pool.enqueue_job("start_study", sid)
        logger.info(
            "queued study dispatched at worker boot",
            event_type="queued_dispatch_at_boot",
            study_id=sid,
        )
    for jid in generating_judgment_ids:
        # Deterministic ``_job_id`` so the boot sweep doesn't enqueue a
        # duplicate when a job from the API is already in-flight (per
        # GPT-5.5 cycle-4 C4-F1).
        await arq_pool.enqueue_job(
            "generate_judgments_llm",
            jid,
            _job_id=f"generate_judgments_llm:{jid}",
        )
        logger.info(
            "judgment generation dispatched at worker boot",
            event_type="judgment_resume_enqueued",
            judgment_list_id=jid,
        )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Dispose Optuna's SQLAlchemy engine + close the Arq pool."""
    storage = ctx.get("optuna_storage")
    if storage is not None:
        engine = getattr(storage, "_engine", None) or getattr(storage, "engine", None)
        if engine is not None:
            try:
                await asyncio.to_thread(engine.dispose)
            except AttributeError:  # pragma: no cover  — defensive
                pass

    arq_pool: ArqRedis | None = ctx.get("arq_pool")
    if arq_pool is not None:
        await arq_pool.close()


class WorkerSettings:
    """Arq worker configuration.

    Per-function timeouts: ``start_study`` / ``resume_study`` wrap an
    indefinite polling loop and get a 24h timeout (worst-case
    ``time_budget_min``). ``run_trial`` keeps Arq's default per-job
    timeout (~5 min — fits ~200ms–2s per trial with margin).
    ``generate_digest`` keeps default; the stub returns instantly.
    """

    functions: list[Any] = [
        run_trial,
        func(start_study, timeout=_ORCHESTRATOR_JOB_TIMEOUT_S),
        func(resume_study, timeout=_ORCHESTRATOR_JOB_TIMEOUT_S),
        generate_digest,
        func(generate_judgments_llm, timeout=_JUDGMENTS_JOB_TIMEOUT_S),
    ]
    redis_settings = _build_redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
