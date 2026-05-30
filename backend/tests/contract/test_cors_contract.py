# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""CORS contract — the browser UI on :3000 calls the API on :8000.

Verifies the API responds to OPTIONS preflights with the required
Access-Control-Allow-* headers. Builds a minimal FastAPI app that wires the
same middleware configuration as ``backend.app.main`` (which can't be loaded
in tests without stubbed secret files); the contract under test is the
middleware setup, not main's startup probes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient


def _build_test_app(allow_origins: list[str]) -> FastAPI:
    """Mirror the CORS middleware setup from ``backend.app.main``."""
    app = FastAPI()
    if allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Accept", "X-Request-ID"],
            expose_headers=["X-Request-ID", "X-Total-Count"],
        )

    @app.get("/api/v1/clusters")
    async def list_clusters() -> dict[str, list[object]]:
        return {"data": []}

    return app


@pytest.fixture
async def cors_client() -> AsyncGenerator[AsyncClient]:
    app = _build_test_app(["http://localhost:3000", "http://127.0.0.1:3000"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_preflight_returns_allow_origin_for_allowed_origin(
    cors_client: AsyncClient,
) -> None:
    response = await cors_client.options(
        "/api/v1/clusters",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-request-id",
        },
    )
    assert response.status_code == httpx.codes.OK
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    allow_headers = response.headers.get("access-control-allow-headers", "").lower()
    assert "x-request-id" in allow_headers


async def test_preflight_exposes_xtotalcount_and_xrequestid_on_actual_response(
    cors_client: AsyncClient,
) -> None:
    # `expose-headers` is returned on the actual response, not the preflight.
    response = await cors_client.get(
        "/api/v1/clusters",
        headers={"Origin": "http://localhost:3000"},
    )
    expose = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-total-count" in expose
    assert "x-request-id" in expose


async def test_preflight_rejected_for_disallowed_origin(cors_client: AsyncClient) -> None:
    # Starlette's CORS middleware omits the Allow-Origin header (rather than
    # returning a 4xx) when the origin doesn't match the allowlist; the browser
    # then rejects the response.
    response = await cors_client.options(
        "/api/v1/clusters",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


async def test_empty_allow_origins_disables_cors() -> None:
    app = _build_test_app([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/clusters",
            headers={"Origin": "http://localhost:3000"},
        )
    assert response.status_code == httpx.codes.OK
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}
