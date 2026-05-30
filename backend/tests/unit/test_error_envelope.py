# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Error envelope tests (infra_foundation Story 3.1).

Verifies that each of the three exception handlers produces the documented
structured envelope shape for the relevant HTTP status code.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

import pytest
from fastapi import Body, FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from backend.app.api.errors import install_exception_handlers


@pytest.fixture
def app() -> FastAPI:
    """Build a fresh FastAPI app with our handlers + a small set of test routes."""
    test_app = FastAPI()
    install_exception_handlers(test_app)

    @test_app.get("/raise-404")
    async def _raise_404() -> None:
        raise HTTPException(status_code=404, detail="Not found")

    @test_app.get("/raise-503-structured")
    async def _raise_503_structured() -> None:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "SERVICE_UNAVAILABLE",
                "message": "Postgres is down",
                "retryable": True,
            },
        )

    @test_app.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("simulated unexpected failure")

    class _Body(BaseModel):
        name: str
        count: int

    @test_app.post("/echo")
    async def _echo(body: Annotated[_Body, Body()]) -> dict[str, object]:
        return body.model_dump()

    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    """httpx AsyncClient bound to the test app via the in-process ASGI transport.

    raise_app_exceptions=False so unhandled exceptions caught by our generic
    Exception handler return a 500 JSON response instead of bubbling up to
    the test client as a Python exception (the default ASGITransport behavior).
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# HTTPException → envelope
# ---------------------------------------------------------------------------


class TestHttpExceptionHandler:
    async def test_404_uses_resource_not_found_code(self, client: AsyncClient) -> None:
        resp = await client.get("/raise-404")
        assert resp.status_code == 404
        body = resp.json()
        assert body == {
            "detail": {
                "error_code": "RESOURCE_NOT_FOUND",
                "message": "Not found",
                "retryable": False,
            }
        }

    async def test_structured_detail_passes_through(self, client: AsyncClient) -> None:
        resp = await client.get("/raise-503-structured")
        assert resp.status_code == 503
        assert resp.json() == {
            "detail": {
                "error_code": "SERVICE_UNAVAILABLE",
                "message": "Postgres is down",
                "retryable": True,
            }
        }


# ---------------------------------------------------------------------------
# RequestValidationError → VALIDATION_ERROR (422)
# ---------------------------------------------------------------------------


class TestValidationExceptionHandler:
    async def test_pydantic_validation_failure_returns_422(self, client: AsyncClient) -> None:
        # Empty body triggers per-field validation; the exact loc-format depends
        # on FastAPI/Pydantic versions, but the envelope shape and error code
        # are stable contracts we own.
        resp = await client.post("/echo", json={})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        body = resp.json()
        assert body["detail"]["error_code"] == "VALIDATION_ERROR"
        assert body["detail"]["retryable"] is False
        # Sanity-check that the message conveys WHY validation failed
        # (don't pin to specific field names — FastAPI/Pydantic loc format
        # has changed across versions and isn't part of our public contract).
        assert "Request validation failed" in body["detail"]["message"]

    async def test_pydantic_type_mismatch_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post("/echo", json={"name": "x", "count": "not an int"})
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"]["error_code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Generic Exception → INTERNAL_ERROR (500), traceback NOT in body
# ---------------------------------------------------------------------------


class TestGenericExceptionHandler:
    async def test_unhandled_exception_returns_500_envelope(self, client: AsyncClient) -> None:
        resp = await client.get("/boom")
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"]["error_code"] == "INTERNAL_ERROR"
        assert body["detail"]["retryable"] is False

    async def test_500_response_does_not_leak_traceback(self, client: AsyncClient) -> None:
        resp = await client.get("/boom")
        # The exception message ("simulated unexpected failure") and any "Traceback"
        # text must not be in the response body — those go to logs only.
        body_text = resp.text
        assert "simulated unexpected failure" not in body_text
        assert "Traceback" not in body_text
        assert "RuntimeError" not in body_text
