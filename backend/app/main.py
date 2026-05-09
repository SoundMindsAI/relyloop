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

from fastapi import FastAPI

from backend.app.api import health
from backend.app.api.errors import install_exception_handlers
from backend.app.api.middleware import RequestIDMiddleware
from backend.app.core.logging import configure_logging

# Configure logging eagerly at module load so anything that runs during app
# construction (e.g. settings validation in lifespan, future startup hooks)
# emits JSON.
configure_logging()

app = FastAPI(
    title="RelyLoop",
    # Version is the package version; `Settings.relyloop_git_sha` (the build
    # SHA) surfaces in /healthz.version once Story 3.2 wires the endpoint.
    version="0.1.0",
    description="Open-source automated relevance tuning for enterprise search platforms",
)

app.add_middleware(RequestIDMiddleware)
install_exception_handlers(app)
app.include_router(health.router)  # /healthz unprefixed; operator endpoint per Rule #6
