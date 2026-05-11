"""Structured logging configuration (infra_foundation Story 3.1).

Per RelyLoop's logging conventions ([`docs/01_architecture/tech-stack.md`
§"Logging conventions"](../../../docs/01_architecture/tech-stack.md)):

- JSON output to stdout via ``structlog``
- Required fields: ``ts``, ``lvl``, ``msg``, ``service``, ``request_id``
- ISO-8601 timestamps in UTC
- Stdlib ``logging`` is also routed through structlog so third-party libraries
  (uvicorn, sqlalchemy, alembic) emit the same JSON shape

The ``request_id`` field is bound per-request by ``RequestIDMiddleware``
([`backend/app/api/middleware.py`](../api/middleware.py)) using structlog's
contextvars.

MVP2+ adds ``trace_id``, ``span_id``, and a PII-redaction processor — those
fields land with the OpenTelemetry + Langfuse wiring at MVP2.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from backend.app.domain.git.redaction import RedactTokensProcessor

SERVICE_NAME = "relyloop-api"


def _add_service_name(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    """Attach the canonical service name to every record."""
    event_dict["service"] = SERVICE_NAME
    return event_dict


def configure_logging(*, level: int = logging.INFO, json_output: bool = True) -> None:
    """Configure structlog + stdlib logging to emit structured JSON to stdout.

    Args:
        level: Root log level (default INFO).
        json_output: If False, use console renderer (human-readable, dev-only).
            Default True for production-style JSON.

    Idempotent — safe to call multiple times. Tests that need a fresh logger
    can call this with custom args.
    """
    # Shared processors that run for both structlog-native and stdlib-routed records.
    # RedactTokensProcessor sits AFTER format_exc_info so tracebacks (which
    # commonly leak tokens via subprocess argv / shell output) are scrubbed
    # too — and BEFORE the renderer so it's the last semantic transform on
    # the record before serialization (feat_github_pr_worker FR-5,
    # defense-in-depth for every log line system-wide).
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _add_service_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        RedactTokensProcessor(),
    ]

    # The final renderer differs between JSON (production) and console (dev).
    final_processor: Processor
    if json_output:
        final_processor = structlog.processors.JSONRenderer()
    else:
        final_processor = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog itself.
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging through structlog so uvicorn/sqlalchemy/alembic
    # emit the same JSON shape.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            final_processor,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Replace any existing handlers (idempotent).
    root_logger.handlers = [handler]
    root_logger.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound with the canonical service field.

    Convenience wrapper around ``structlog.get_logger()`` for explicit usage.
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
