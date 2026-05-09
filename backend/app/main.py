"""RelyLoop API entry point.

This module is intentionally minimal — Story 3.1 wires structlog, X-Request-ID
middleware, and the error envelope; Story 3.2 adds the /healthz router; Story 3.3
adds the OpenAI capability check at startup. For now, this is the scaffold that
proves the FastAPI dependency installed cleanly via `uv sync`.
"""

from fastapi import FastAPI

app = FastAPI(
    title="RelyLoop",
    version="0.1.0",
    description="Open-source automated relevance tuning for enterprise search platforms",
)
