"""Structured error envelope + exception handlers (infra_foundation Story 3.1).

Per ``docs/01_architecture/api-conventions.md`` §"Error envelope":

.. code-block:: json

    {
      "detail": {
        "error_code": "<MACHINE_READABLE>",
        "message": "<human>",
        "retryable": <bool>
      }
    }

Standard codes (defined in api-conventions §"Standard error codes"):

- ``VALIDATION_ERROR`` (422) — Pydantic validation failed
- ``RESOURCE_NOT_FOUND`` (404) — generic not-found (specific resources define
  their own codes, e.g. ``CLUSTER_NOT_FOUND`` once ``infra_adapter_elastic`` lands)
- ``RATE_LIMITED`` (429) — MVP4+ only; reserved here
- ``INTERNAL_ERROR`` (500) — unexpected server error; tracebacks logged but never returned
- ``SERVICE_UNAVAILABLE`` (503) — dependency down (used by /healthz in Story 3.2)

The /healthz endpoint (Story 3.2) is the one exception to the envelope shape:
it's an operator probe and returns its own JSON shape per spec §7.3 — when
the overall status is degraded it returns 503 with the same body shape (not
nested under ``detail``). All business endpoints under /api/v1/ follow the
envelope shape.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ErrorEnvelope(BaseModel):
    """Inner ``detail`` body of every non-auth error response."""

    error_code: str = Field(description="Machine-readable error code; never renamed once shipped")
    message: str = Field(description="Human-readable explanation; can change freely")
    retryable: bool = Field(description="True if the same request may succeed if retried")


class ErrorResponse(BaseModel):
    """Top-level response wrapping ``ErrorEnvelope`` under ``detail``."""

    detail: ErrorEnvelope


# --- Default code → HTTP-status + retryability mappings ----------------------

_HTTP_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    status.HTTP_404_NOT_FOUND: ("RESOURCE_NOT_FOUND", False),
    status.HTTP_422_UNPROCESSABLE_CONTENT: ("VALIDATION_ERROR", False),
    status.HTTP_429_TOO_MANY_REQUESTS: ("RATE_LIMITED", True),
    status.HTTP_500_INTERNAL_SERVER_ERROR: ("INTERNAL_ERROR", False),
    status.HTTP_503_SERVICE_UNAVAILABLE: ("SERVICE_UNAVAILABLE", True),
}


def _envelope(error_code: str, message: str, retryable: bool) -> dict[str, Any]:
    """Construct the JSON-serializable envelope dict."""
    return {"detail": {"error_code": error_code, "message": message, "retryable": retryable}}


# --- Exception handlers ------------------------------------------------------


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """Translate FastAPI ``HTTPException`` into the structured envelope.

    Routers can supply a structured detail directly (e.g.
    ``raise HTTPException(status_code=404, detail={"error_code": "CLUSTER_NOT_FOUND",
    "message": "...", "retryable": False})``) and we pass it through. If the
    detail is a plain string, we wrap it with the default code for that status.
    """
    detail: Any = exc.detail  # widened to Any so both the dict-passthrough and
    # str-fallback branches are reachable for type narrowing.

    if isinstance(detail, dict) and "error_code" in detail:
        # Already-structured detail — pass through with the original status code.
        body = {"detail": detail}
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    code, retryable = _HTTP_STATUS_TO_CODE.get(exc.status_code, ("HTTP_ERROR", False))
    message = detail if isinstance(detail, str) else f"HTTP {exc.status_code}"
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, message, retryable),
        headers=exc.headers,
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Translate Pydantic ``RequestValidationError`` (422) into the envelope.

    The per-field errors from ``exc.errors()`` are summarized in the message
    so clients can branch on ``error_code: VALIDATION_ERROR`` and still
    surface specific guidance. (Per-field structured detail arrives at GA v1
    when full RFC 7807 lands.)
    """
    field_errors = [
        f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg', '?')}" for e in exc.errors()
    ]
    message = "Request validation failed: " + "; ".join(field_errors)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=_envelope("VALIDATION_ERROR", message, False),
    )


async def generic_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Catch-all: log the traceback, return a generic INTERNAL_ERROR envelope.

    Critically, the traceback is **never returned** in the response body —
    it goes to structured logs only. The client gets a stable error_code and
    the request_id (echoed in the X-Request-ID header by RequestIDMiddleware)
    so support can correlate.
    """
    logger.exception("Unhandled exception in request handler", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            "INTERNAL_ERROR",
            "An unexpected error occurred. The server team has been notified.",
            False,
        ),
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Register all three handlers on the FastAPI app."""
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)
