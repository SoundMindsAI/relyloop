"""RelyLoop API entry point.

Wires together the bootstrap pieces:

1. ``configure_logging()`` — structured JSON logging via structlog (Story 3.1)
2. ``RequestIDMiddleware`` — per-request UUIDv7 in X-Request-ID header (Story 3.1)
3. Exception handlers — structured error envelope per api-conventions (Story 3.1)
4. ``/healthz`` router — subsystem probes (Story 3.2)
5. OpenAI capability check at startup — cached in Redis (Story 3.3)

Subsequent feature stories register their own routers via
``app.include_router()`` (e.g. infra_adapter_elastic adds /api/v1/clusters).

**Settings are NOT read at module load.** The ``Settings`` class requires
``DATABASE_URL_FILE`` and ``POSTGRES_PASSWORD_FILE`` to be configured (per
FR-3) and would crash unit tests that just import ``app`` without the
runtime stack. The version surfaces ``Settings.relyloop_git_sha`` lazily via
the FastAPI ``lifespan`` hook (added in Story 3.2 when the /healthz route
needs it); for now the OpenAPI version field reports ``Settings`` only when
``get_settings()`` is called from within a route handler or lifespan.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from backend.app.api import health
from backend.app.api.errors import install_exception_handlers
from backend.app.api.middleware import RequestIDMiddleware
from backend.app.core.logging import configure_logging, get_logger
from backend.app.core.settings import get_settings
from backend.app.llm.capability_check import run_capability_check_background

# Configure logging eagerly at module load so anything that runs during app
# construction (e.g. settings validation in lifespan, future startup hooks)
# emits JSON.
configure_logging()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: schedule the OpenAI capability check (Story 3.3 / FR-7).

    The check runs as a background task via ``asyncio.create_task`` so a
    slow / unreachable LLM endpoint does not delay startup. ``/healthz``
    reads the cached result from Redis; until the task completes,
    ``subsystems.openai`` reports ``configured`` (key present, cache miss
    treated as non-blocking per ``probe_openai_state`` in
    ``backend/app/api/probes.py``).
    """
    settings = get_settings()
    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    cap_task = asyncio.create_task(
        run_capability_check_background(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            redis_client=redis_client,
        )
    )
    try:
        yield
    finally:
        # Cancel the capability check if it's still running on shutdown
        # (e.g. a slow endpoint pushed it past process lifetime).
        if not cap_task.done():
            cap_task.cancel()
            try:
                await cap_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 — shutdown swallow
                logger.warning(
                    "Capability check task raised during shutdown",
                    error=str(exc),
                )
        await redis_client.aclose()


app = FastAPI(
    title="RelyLoop",
    # Version is the package version; `Settings.relyloop_git_sha` (the build
    # SHA) surfaces in /healthz.version once Story 3.2 wires the endpoint.
    version="0.1.0",
    description="Open-source automated relevance tuning for enterprise search platforms",
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
install_exception_handlers(app)
app.include_router(health.router)  # /healthz unprefixed; operator endpoint per Rule #6
