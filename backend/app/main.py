# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from backend.app.api import health
from backend.app.api.errors import install_exception_handlers
from backend.app.api.middleware import RequestIDMiddleware
from backend.app.api.v1 import _test as test_router
from backend.app.api.v1 import clusters as clusters_router
from backend.app.api.v1 import config_repos as config_repos_router
from backend.app.api.v1 import conversations as conversations_router
from backend.app.api.v1 import judgments as judgments_router
from backend.app.api.v1 import proposals as proposals_router
from backend.app.api.v1 import query_sets as query_sets_router
from backend.app.api.v1 import query_templates as query_templates_router
from backend.app.api.v1 import studies as studies_router
from backend.app.api.webhooks import github as webhook_github_router
from backend.app.core.logging import configure_logging, get_logger
from backend.app.core.settings import get_settings
from backend.app.db.session import get_session_factory
from backend.app.llm.capability_check import run_capability_check_background
from backend.app.services.cluster_health_warmup import (
    run_cluster_health_warmup_background,
)

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

    # Deprecation WARN: GITHUB_TOKEN_FILE was retired when
    # feat_github_pr_worker shipped per-repo `auth_ref`. Carrying it over
    # from a pre-retirement install is silently no-op; warn the operator
    # so the stale env var gets dropped on the next deploy.
    if os.environ.get("GITHUB_TOKEN_FILE"):
        logger.warning(
            "GITHUB_TOKEN_FILE is no longer read; "
            "register each config_repo via POST /api/v1/config-repos with an "
            "explicit auth_ref and drop the corresponding PAT at ./secrets/{auth_ref}",
            event_type="github_token_file_deprecated",
        )

    # Hardened-posture guards (security audit 2026-07-11 findings #4/#5).
    # ENVIRONMENT defaults to "development", which UN-gates the destructive,
    # unauthenticated /api/v1/_test/* endpoints (hard-DELETE + demo reseed).
    # That is correct for a laptop/CI host but a footgun if such an instance is
    # ever exposed to an untrusted network before the auth surface lands, so we
    # emit a one-line boot reminder.
    if settings.environment == "development":
        logger.warning(
            "ENVIRONMENT=development: destructive, unauthenticated /api/v1/_test/* "
            "endpoints (hard-delete + demo reseed) are ENABLED. Only run this "
            "instance on a trusted local/CI host — never expose it to an untrusted "
            "network. Set ENVIRONMENT=staging|production to disable them.",
            event_type="dev_test_endpoints_enabled",
        )

    # The cluster base_url SSRF guard is a no-op while RELYLOOP_ALLOW_PRIVATE_
    # CLUSTERS is True (the laptop-friendly default). On a non-development
    # deployment that default means ZERO SSRF protection (internal hosts + cloud
    # metadata IPs are registerable), so warn loudly to flip it.
    if settings.relyloop_allow_private_clusters and settings.environment != "development":
        logger.warning(
            "RELYLOOP_ALLOW_PRIVATE_CLUSTERS=True on a non-development deployment "
            "(ENVIRONMENT=%s): the cluster base_url SSRF guard is disabled, so "
            "internal/metadata endpoints can be registered and probed. Set "
            "RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False to enable the guard.",
            settings.environment,
            event_type="ssrf_guard_disabled_non_dev",
        )

    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    cap_task = asyncio.create_task(
        run_capability_check_background(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            redis_client=redis_client,
        )
    )

    # bug_demo_clusters_unreachable_in_healthz Story 1.3: warm the
    # cluster:health:* Redis cache so /healthz reports truthful counts
    # within ~5s of boot. Fire-and-forget, same shutdown semantics as
    # cap_task above (cancel/await/swallow at the end of lifespan).
    #
    # Gated by RELYLOOP_DISABLE_STARTUP_WARMUP env var (defaults to
    # spawn). The gate exists so integration tests can opt out — under
    # interleaved event-loop scheduling, the warmup task perturbs the
    # timing of `test_ac7_concurrent_merges_serialize_via_row_lock` and
    # exposes a latent webhook merge-handler row-lock race captured at
    # docs/00_overview/planned_features/02_mvp2/
    # bug_webhook_concurrent_merge_race_timing_sensitive/idea.md.
    # Production deployments should leave this UNSET so the warmup runs.
    warmup_task: asyncio.Task[None] | None = None
    if not os.environ.get("RELYLOOP_DISABLE_STARTUP_WARMUP"):
        db_factory = get_session_factory()
        warmup_task = asyncio.create_task(
            run_cluster_health_warmup_background(db_factory, redis_client)
        )

    # Build the Arq pool used by Phase 2's POST /api/v1/studies to
    # enqueue the start_study orchestrator job. The pool is best-effort:
    # if Redis isn't reachable we log + skip (the study row still lands
    # in the DB and the worker's on_startup resume sweep will pick it up
    # if it's running).
    from arq.connections import RedisSettings, create_pool

    arq_pool = None
    try:
        arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        _app.state.arq_pool = arq_pool
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "failed to build Arq pool at startup; POST /studies will not enqueue",
            error=str(exc),
        )

    try:
        yield
    finally:
        if arq_pool is not None:
            try:
                await arq_pool.aclose()
            except Exception as exc:  # noqa: BLE001 — shutdown swallow
                logger.warning("arq pool close raised during shutdown", error=str(exc))
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
        # Cancel the cluster-health warmup task (Story 1.3 / FR-4).
        # Mirrors the capability-check shutdown above. The warmup function's
        # short-lived `async with db_factory() as db:` blocks release the
        # DB session on CancelledError propagation per spec §19 D-10.
        # Skipped entirely if RELYLOOP_DISABLE_STARTUP_WARMUP is set
        # (warmup_task is None in that case).
        if warmup_task is not None and not warmup_task.done():
            warmup_task.cancel()
            try:
                await warmup_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001 — shutdown swallow
                logger.warning(
                    "Cluster health warmup task raised during shutdown",
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

# CORS: required for the browser UI on a separate dev origin (Next on :3000
# calling the API on :8000). Origins are configurable via Settings.cors_allow_origins
# (comma-separated). Empty string disables. MVP1 default covers the local Next
# dev server; operators add production origins at MVP3.
_cors_origins = [o.strip() for o in get_settings().cors_allow_origins.split(",") if o.strip()]
# Security audit 2026-07-11 finding #10: a wildcard origin combined with
# allow_credentials=True is unsafe — Starlette reflects the request Origin
# (rather than sending a literal "*"), which lets ANY site make credentialed
# cross-origin requests. Disable credentials whenever a wildcard is configured;
# MVP1 has no cookies/auth so nothing depends on credentialed CORS today.
_cors_has_wildcard = "*" in _cors_origins
_cors_allow_credentials = not _cors_has_wildcard
if _cors_has_wildcard:
    logger.warning(
        "CORS_ALLOW_ORIGINS contains '*'; disabling allow_credentials to avoid "
        "reflecting arbitrary origins with credentials. Configure explicit "
        "origins if you need credentialed CORS.",
        event_type="cors_wildcard_credentials_disabled",
    )
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=_cors_allow_credentials,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        # Browsers ALWAYS strip custom headers from the request preflight unless
        # they're explicitly allowed. The UI's api-client.ts injects X-Request-ID
        # on every request — must be allow-listed here or the preflight fails.
        allow_headers=["Content-Type", "Accept", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Total-Count"],
    )

install_exception_handlers(app)
app.include_router(health.router)  # /healthz unprefixed; operator endpoint per Rule #6
app.include_router(clusters_router.router, prefix="/api/v1")  # Story 3.2 — cluster CRUD
app.include_router(query_templates_router.router, prefix="/api/v1")  # Phase 2 Story 3.1
app.include_router(query_sets_router.router, prefix="/api/v1")  # Phase 2 Story 3.2
app.include_router(studies_router.router, prefix="/api/v1")  # Phase 2 Stories 3.3 + 3.4
app.include_router(judgments_router.router, prefix="/api/v1")  # feat_llm_judgments Epic 3
app.include_router(proposals_router.router, prefix="/api/v1")  # feat_digest_proposal Epic 3
app.include_router(config_repos_router.router, prefix="/api/v1")  # feat_github_pr_worker Epic 3
app.include_router(conversations_router.router, prefix="/api/v1")  # feat_chat_agent Epic 3
app.include_router(
    test_router.router, prefix="/api/v1"
)  # infra_e2e_seed_completed_study — dev-only; 404 outside
app.include_router(webhook_github_router.router)  # feat_github_webhook /webhooks/github
