"""RequestIDMiddleware tests (infra_foundation Story 3.1).

Verifies the X-Request-ID handshake per api-conventions.md §"Trace / request
correlation":

- Client-supplied X-Request-ID is adopted and echoed back in the response
- Missing X-Request-ID is replaced by a server-minted UUIDv7 echoed in the response
- The bound request_id is available to log records emitted during the request
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator

import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.app.api.middleware import REQUEST_ID_HEADER, RequestIDMiddleware

# UUIDv7 regex: 8-4-4-4-12 hex digits with the 7 nibble in version position
UUID_V7_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@pytest.fixture
def app_with_middleware() -> FastAPI:
    """Build a FastAPI app with only RequestIDMiddleware + a tiny route."""
    test_app = FastAPI()
    test_app.add_middleware(RequestIDMiddleware)
    captured_request_ids: list[str | None] = []

    @test_app.get("/ping")
    async def _ping() -> dict[str, str]:
        # Read the request_id from structlog's contextvars to confirm binding.
        ctx = structlog.contextvars.get_contextvars()
        captured_request_ids.append(ctx.get("request_id"))
        return {"pong": "true"}

    test_app.state.captured_request_ids = captured_request_ids
    return test_app


@pytest.fixture
async def client(app_with_middleware: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestRequestIDMiddleware:
    async def test_missing_header_mints_uuidv7(
        self, client: AsyncClient, app_with_middleware: FastAPI
    ) -> None:
        resp = await client.get("/ping")
        assert resp.status_code == 200
        request_id = resp.headers.get(REQUEST_ID_HEADER)
        assert request_id is not None, "X-Request-ID not set on response"
        assert UUID_V7_RE.match(request_id), f"not a UUIDv7: {request_id}"

    async def test_client_supplied_header_is_adopted(self, client: AsyncClient) -> None:
        client_id = "test-correlation-12345"
        resp = await client.get("/ping", headers={REQUEST_ID_HEADER: client_id})
        assert resp.headers.get(REQUEST_ID_HEADER) == client_id

    async def test_request_id_bound_to_structlog_context(
        self, client: AsyncClient, app_with_middleware: FastAPI
    ) -> None:
        captured: list[str | None] = app_with_middleware.state.captured_request_ids
        captured.clear()

        client_id = "ctx-binding-check"
        await client.get("/ping", headers={REQUEST_ID_HEADER: client_id})

        assert captured == [client_id], f"request_id not bound to contextvars: {captured!r}"

    async def test_each_request_gets_distinct_id_when_unset(self, client: AsyncClient) -> None:
        ids: set[str] = set()
        for _ in range(5):
            resp = await client.get("/ping")
            ids.add(resp.headers[REQUEST_ID_HEADER])
        assert len(ids) == 5, f"requests received duplicate UUIDv7s: {ids}"

    async def test_contextvars_cleared_between_requests(
        self, client: AsyncClient, app_with_middleware: FastAPI
    ) -> None:
        captured: list[str | None] = app_with_middleware.state.captured_request_ids
        captured.clear()

        # Two requests with distinct supplied IDs — each handler should see only its own.
        await client.get("/ping", headers={REQUEST_ID_HEADER: "id-a"})
        await client.get("/ping", headers={REQUEST_ID_HEADER: "id-b"})

        assert captured == ["id-a", "id-b"], f"context bled across requests: {captured!r}"
