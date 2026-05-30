# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""HTTP middleware (infra_foundation Story 3.1).

Per ``docs/01_architecture/api-conventions.md`` §"Trace / request correlation":

- Every request gets a ``request_id`` (UUIDv7) — generated on entry by this
  middleware, attached to every structured-log record for that request via
  ``structlog.contextvars``, and echoed in the ``X-Request-ID`` response header.
- If the client supplies ``X-Request-ID`` on the request, the server adopts
  it (idempotent retry support); otherwise the server mints one.
- MVP1 does NOT propagate W3C ``traceparent`` through DB / Redis / OpenAI /
  ES / GitHub — that lands at MVP2 with the OpenTelemetry wiring.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
import uuid_utils
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a stable request_id to every request/response.

    Order of resolution:
        1. Client-supplied ``X-Request-ID`` header → adopted as-is (treat as opaque)
        2. None supplied → mint a UUIDv7 (sortable, time-ordered)

    The chosen request_id is:
        - Bound to ``structlog.contextvars`` so all log lines emitted during
          the request include it
        - Echoed back in the ``X-Request-ID`` response header
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process a single request through the X-Request-ID handshake."""
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid_utils.uuid7())

        # Bind to structlog context for the duration of this request.
        # clear_contextvars() at the start prevents leakage across concurrent
        # requests (each request runs in its own asyncio task with its own context).
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        try:
            response = await call_next(request)
        finally:
            # Clear so the contextvars don't leak to the next request handled
            # by this same task (shouldn't happen with starlette's per-request
            # task model, but defensive).
            structlog.contextvars.clear_contextvars()

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
