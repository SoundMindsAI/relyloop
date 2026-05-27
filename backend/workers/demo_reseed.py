"""Arq worker job for the demo-reseed flow.

Per ``bug_demo_reseed_fake_metric_regression`` — the home-button reseed
moves from a synchronous endpoint (held one HTTP connection open for the
2-6 minutes it took to run real trials) to an async enqueue + poll
pattern. The route handler enqueues this job and returns 202; the
frontend polls ``GET /api/v1/_test/demo/reseed/status`` for progress.

The job:

1. Acquires the Postgres advisory lock (same key the synchronous
   handler used). On contention, marks Redis status as ``failed`` with
   ``SEED_IN_PROGRESS`` reason and exits — Arq's own dedup-via-job-id
   should prevent this, but it's a belt-and-suspenders safeguard
   against operator-clicked-twice racing through the queue.
2. Constructs the two ``httpx.AsyncClient`` instances the orchestrator
   needs (one against the API, one against ES/OS).
3. Runs :func:`backend.app.services.demo_seeding.reseed_demo_state` with
   a Redis-writing :type:`StatusCallback` so progress flows to the
   polling endpoint after every phase.
4. Writes terminal status (``complete`` or ``failed``) to Redis before
   releasing the advisory lock.
"""

from __future__ import annotations

from typing import Any, Final

import httpx
import structlog
from redis.asyncio import Redis
from sqlalchemy import text

from backend.app.core.settings import get_settings
from backend.app.db.session import get_engine, get_session_factory
from backend.app.services.demo_seeding import (
    DEMO_RESEED_LOCK_KEY,
    DemoSeedingError,
    ReseedStatusResponse,
    _now_iso,
    reseed_demo_state,
    run_demo_reseed_cleanup,
    status_set,
)

logger = structlog.get_logger(__name__)


# 20-minute hard ceiling on the entire reseed — 4 small scenarios + the
# rich ESCI scenario (1000 docs + LLM judgments + 15-trial study). Per
# scripts/seed_meaningful_demos.py wall-clock notes: small scenarios run
# ~1 min each, the rich scenario adds ~3-5 min, plus digest waits and
# headroom. The advisory lock prevents concurrent runs from piling up;
# this timeout bounds the worst case.
DEMO_RESEED_JOB_TIMEOUT_S: Final[int] = 1200


async def run_demo_reseed(ctx: dict[str, Any]) -> None:
    """Arq job: wipe + reseed the 4 demo scenarios using real studies.

    Worker enqueue site:
    :func:`backend.app.api.v1._test.reseed_demo` POSTs to
    ``/api/v1/_test/demo/reseed`` and calls ``arq_pool.enqueue_job`` with
    a deterministic ``_job_id`` to prevent double-enqueue from a fast
    double-click.

    Status is reported via Redis (key
    :data:`backend.app.services.demo_seeding.DEMO_RESEED_STATUS_KEY`).
    The polling endpoint at
    ``GET /api/v1/_test/demo/reseed/status`` reads the same key.

    No retries — if the underlying ES/OS or DB is in a bad state, retrying
    won't help; the operator needs to investigate. Status flips to
    ``failed`` with the exception class + first 200 chars of the message.
    """
    settings = get_settings()
    factory = get_session_factory()
    redis = Redis.from_url(settings.redis_url, decode_responses=False)

    try:
        engine = get_engine()
        async with engine.connect() as lock_conn:
            acquired = bool(
                (
                    await lock_conn.execute(
                        text("SELECT pg_try_advisory_lock(:k)"),
                        {"k": DEMO_RESEED_LOCK_KEY},
                    )
                ).scalar_one()
            )
            await lock_conn.commit()
            if not acquired:
                # The POST handler already prevents double-enqueue via the
                # deterministic job id, but if somehow two workers raced
                # here, surface a clean failed-status rather than blocking.
                logger.warning("demo_reseed_worker_lock_contention")
                await status_set(
                    redis,
                    ReseedStatusResponse(
                        status="failed",
                        started_at=_now_iso(),
                        finished_at=_now_iso(),
                        failed_reason="advisory lock held by another reseed run",
                    ),
                )
                return

            try:
                async with factory() as db:
                    timeout = httpx.Timeout(settings.demo_reseed_per_call_http_timeout_s)
                    # The worker runs in its own container (relyloop-worker-1),
                    # so ``localhost`` resolves to the worker itself, not the
                    # API. Use the Compose service alias ``http://api:8000``
                    # so the self-call lands on the API container. (The old
                    # synchronous handler used ``http://localhost:8000``
                    # because it ran INSIDE the API container — same loopback.)
                    async with (
                        httpx.AsyncClient(
                            base_url="http://api:8000",
                            timeout=timeout,
                        ) as api_client,
                        httpx.AsyncClient(timeout=timeout) as engine_client,
                    ):
                        logger.info("demo_reseed_worker_started")

                        async def _redis_status_cb(status: ReseedStatusResponse) -> None:
                            await status_set(redis, status)

                        try:
                            summary = await reseed_demo_state(
                                db,
                                api_client,
                                engine_client,
                                status_callback=_redis_status_cb,
                            )
                            logger.info(
                                "demo_reseed_worker_completed",
                                duration_ms=summary.duration_ms,
                            )
                        except (DemoSeedingError, httpx.HTTPError, Exception) as exc:  # noqa: BLE001
                            logger.warning(
                                "demo_reseed_worker_failed",
                                exc_class=type(exc).__name__,
                                exc=str(exc)[:200],
                            )
                            # Best-effort cleanup so the system isn't left
                            # half-seeded. Holding the advisory lock keeps
                            # concurrent reseeds 409'd until we release.
                            await run_demo_reseed_cleanup(engine_client)
                            await status_set(
                                redis,
                                ReseedStatusResponse(
                                    status="failed",
                                    started_at=_now_iso(),
                                    finished_at=_now_iso(),
                                    failed_reason=(f"{type(exc).__name__}: {str(exc)[:200]}"),
                                ),
                            )
                            # Swallow — Arq retries would re-run the entire
                            # destructive wipe + reseed, which is the wrong
                            # behavior. The operator can re-click after
                            # investigating the underlying failure.
                            return
            finally:
                # Always release the advisory lock, even on exception.
                await lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"),
                    {"k": DEMO_RESEED_LOCK_KEY},
                )
                await lock_conn.commit()
    finally:
        await redis.aclose()
