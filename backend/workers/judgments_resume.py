"""Periodic in-worker resume sweep for stuck judgment lists (feat_judgments_periodic_resume_sweep).

Story 1.2 — the complete worker module:

* :func:`resume_counter_key` / :func:`increment_and_check_cap` —
  Redis daily-counter helpers keyed ``judgments:resume:YYYY-MM-DD:<jid>``.
  Mirror the existing budget-gate precedent at
  :mod:`backend.app.llm.budget_gate` (per-UTC-day key, 26h TTL, refreshed
  on every INCR).
* :func:`_resume_sweep_cron_kwargs` — translates
  ``Settings.relyloop_judgments_resume_sweep_minutes`` into
  ``arq.cron(minute=..., hour=...)`` kwargs using the same sub-hour /
  multi-hour routing as :func:`backend.workers.pr_reconcile._poll_cron_kwargs`.
  Unsupported values (validator bypassed by direct attribute mutation in
  tests) emit a WARN and fall back to ``FALLBACK_POLL_MINUTES = 15``.
* :func:`resume_stuck_judgment_lists` — the Arq cron handler. Each tick:

  1. ``SELECT id FROM judgment_lists WHERE status='generating'`` via
     :func:`backend.app.db.repo.list_generating_judgment_list_ids` (re-uses
     the helper the boot-time sweep already calls — no new repo helper).
  2. Build a fresh per-tick Redis client (never reads or closes a
     worker-shared client from ``ctx`` per spec §FR-5 step 2).
  3. For each id: atomically ``INCR`` the per-(id, UTC-day) counter and
     refresh the 26h TTL. If the post-INCR count exceeds the cap, log
     ``judgment_resume_capped`` (WARN) and skip the enqueue.
  4. Otherwise enqueue ``generate_judgments_llm`` with deterministic
     ``_job_id=f"generate_judgments_llm:{jid}"`` — Arq's ``_job_id`` dedup
     makes an in-flight or recently-completed job a no-op by construction.
     Same convention as the boot-time sweep at
     ``backend/workers/all.py:152-156`` so observability dedupes the two
     paths via the shared ``event_type="judgment_resume_enqueued"``.
  5. Per-id failures (Redis transient, Arq transient) are caught + logged
     as ``judgment_resume_errored`` and the loop continues. Top-level
     failures (Redis client construction raises, DB SELECT raises)
     propagate so Arq logs the tick failure; the next scheduled tick
     fires per cron schedule.

The handler returns a summary dict ``{candidates, enqueued, capped, errored}``
plus emits ``judgments_resume_tick_complete`` at INFO every tick (mirrors
:func:`backend.workers.pr_reconcile.reconcile_pr_state`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.workers.pr_reconcile import (
    FALLBACK_POLL_MINUTES,
    SUPPORTED_POLL_MINUTES,
)

logger = structlog.get_logger(__name__)


# 26h matches backend.app.llm.budget_gate:30 — slightly longer than 24h so a
# clock skew or misfired UTC rollover doesn't reset the counter mid-day.
_TTL_SECONDS = 26 * 60 * 60


def resume_counter_key(now: datetime, judgment_list_id: str) -> str:
    """Return the Redis key ``judgments:resume:YYYY-MM-DD:<jid>`` keyed on UTC date.

    Defensively normalises ``now`` to UTC before formatting so callers that
    hand us a non-UTC aware datetime (or a naive datetime they intend as
    UTC) still get the right key. Mirrors
    :func:`backend.app.llm.budget_gate.daily_key` but adds the tz
    normalisation step.
    """
    if now.tzinfo is None:
        utc_now = now.replace(tzinfo=UTC)
    else:
        utc_now = now.astimezone(UTC)
    return f"judgments:resume:{utc_now.strftime('%Y-%m-%d')}:{judgment_list_id}"


async def increment_and_check_cap(
    redis: Redis,
    judgment_list_id: str,
    cap: int,
    *,
    now: datetime | None = None,
) -> tuple[int, bool]:
    """Atomically ``INCR`` the per-(id, day) counter and refresh the 26h TTL.

    Returns ``(count, capped)`` where ``capped`` is ``True`` when
    ``count > cap``. TTL is refreshed on every INCR matching the existing
    ``budget_gate.record_cost`` cadence at
    :mod:`backend.app.llm.budget_gate` lines 86-87.
    """
    now = now or datetime.now(UTC)
    key = resume_counter_key(now, judgment_list_id)
    count = int(await redis.incr(key))
    await redis.expire(key, _TTL_SECONDS)
    return count, count > cap


def _resume_sweep_cron_kwargs() -> dict[str, Any]:
    """Translate ``Settings.relyloop_judgments_resume_sweep_minutes`` into ``arq.cron`` kwargs.

    Mirrors :func:`backend.workers.pr_reconcile._poll_cron_kwargs` exactly:

    * ``n ≤ 60`` (divisor of 60): ``{"minute": set(range(0, 60, n))}``.
    * ``n > 60`` (multiple of 60 dividing 1440):
      ``{"hour": set(range(0, 24, n // 60)), "minute": {0}}``.

    Unsupported values (validator bypassed by direct ``settings.__dict__``
    mutation in tests) log a WARN and fall back to
    ``FALLBACK_POLL_MINUTES``. Defense-in-depth — the field_validator at
    ``backend/app/core/settings.py`` rejects unsupported values at boot.
    """
    n = get_settings().relyloop_judgments_resume_sweep_minutes
    if n not in SUPPORTED_POLL_MINUTES:
        logger.warning(
            "judgments_resume_sweep_minutes_unsupported",
            configured=n,
            falling_back_to=FALLBACK_POLL_MINUTES,
            supported=sorted(SUPPORTED_POLL_MINUTES),
        )
        n = FALLBACK_POLL_MINUTES
    if n <= 60:
        return {"minute": set(range(0, 60, n))}
    return {"hour": set(range(0, 24, n // 60)), "minute": {0}}


async def _select_stuck_ids() -> list[str]:
    """Open a DB session, SELECT stuck ids, close the session.

    Factored out so the handler can build its Redis client after the DB
    session is closed (per spec FR-5 step 1 — sequencing matters for
    resource lifecycle).
    """
    factory = get_session_factory()
    async with factory() as db:
        return await repo.list_generating_judgment_list_ids(db)


async def resume_stuck_judgment_lists(ctx: dict[str, Any]) -> dict[str, int]:
    """Periodic cron sweep — re-enqueue every ``status='generating'`` row.

    FR-5: re-enqueue every stuck row this tick. Arq's ``_job_id`` dedup
    makes an in-flight or recently-completed job a no-op by construction;
    the Redis daily counter (FR-4) caps runaway loops on structurally-
    broken rows.

    Returns ``{candidates, enqueued, capped, errored}`` so the operator
    can grep one summary line per tick.
    """
    settings = get_settings()
    cadence_min = settings.relyloop_judgments_resume_sweep_minutes
    cap = settings.relyloop_judgments_resume_max_per_day
    summary = {"candidates": 0, "enqueued": 0, "capped": 0, "errored": 0}

    candidate_ids = await _select_stuck_ids()
    summary["candidates"] = len(candidate_ids)

    if candidate_ids:
        logger.info(
            "judgment_stuck_detected",
            count=len(candidate_ids),
            cadence_min=cadence_min,
            ids=list(candidate_ids[:10]),
        )

    if not candidate_ids:
        logger.info("judgments_resume_tick_complete", cadence_min=cadence_min, **summary)
        return summary

    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    arq_pool = ctx["arq_pool"]
    try:
        for jid in candidate_ids:
            try:
                count, capped = await increment_and_check_cap(redis_client, jid, cap)
                if capped:
                    logger.warning(
                        "judgment_resume_capped",
                        judgment_list_id=jid,
                        count=count,
                        cap=cap,
                    )
                    summary["capped"] += 1
                    continue
                await arq_pool.enqueue_job(
                    "generate_judgments_llm",
                    jid,
                    _job_id=f"generate_judgments_llm:{jid}",
                )
                # event_type kwarg matches the boot-time sweep at
                # backend/workers/all.py:159 so observability dedupes the
                # two re-enqueue paths under one grep target.
                logger.info(
                    "judgment_resume_enqueued",
                    event_type="judgment_resume_enqueued",
                    judgment_list_id=jid,
                )
                summary["enqueued"] += 1
            except Exception as exc:  # noqa: BLE001 — per-id isolation per FR-5
                logger.warning(
                    "judgment_resume_errored",
                    judgment_list_id=jid,
                    error_type=type(exc).__name__,
                    error_msg=str(exc)[:200],
                )
                summary["errored"] += 1
    finally:
        await redis_client.aclose()

    logger.info("judgments_resume_tick_complete", cadence_min=cadence_min, **summary)
    return summary
