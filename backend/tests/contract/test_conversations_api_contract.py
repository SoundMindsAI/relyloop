# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract assertions for the Epic 3 conversations API (feat_chat_agent)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.tests.conftest import postgres_reachable

_skip_if_no_pg = pytest.mark.skipif(
    not postgres_reachable(),
    reason="Postgres not reachable — error-code paths flow through get_db dependency",
)


EXPECTED_ENDPOINTS = {
    ("post", "/api/v1/conversations"),
    ("get", "/api/v1/conversations"),
    ("get", "/api/v1/conversations/{conversation_id}"),
    ("delete", "/api/v1/conversations/{conversation_id}"),
    ("post", "/api/v1/conversations/{conversation_id}/messages"),
}


SPEC_ERROR_CODES = frozenset(
    {
        "CONVERSATION_NOT_FOUND",
        "OPENAI_NOT_CONFIGURED",
        "OPENAI_BUDGET_EXCEEDED",
    }
)


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


@_skip_if_no_pg
async def test_openapi_registers_all_five_endpoints(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema.get("paths", {})
    found = {
        (method.lower(), path)
        for path, ops in paths.items()
        for method in ops
        if (method.lower(), path) in EXPECTED_ENDPOINTS
    }
    assert found == EXPECTED_ENDPOINTS, EXPECTED_ENDPOINTS - found


def test_router_source_contains_spec_error_codes() -> None:
    """The 3 spec error codes appear as literals in the router source."""
    src = Path("backend/app/api/v1/conversations.py").read_text(encoding="utf-8")
    missing = [c for c in SPEC_ERROR_CODES if c not in src]
    assert not missing, f"router does not raise: {missing}"


def test_request_response_models_importable() -> None:
    """The new Pydantic types are importable from schemas.py."""
    from backend.app.api.v1.schemas import (
        ConversationDetail,
        ConversationsListResponse,
        ConversationSummary,
        CreateConversationRequest,
        MessageWire,
        SendMessageRequest,
    )

    assert CreateConversationRequest.model_fields["title"].is_required() is False
    assert "id" in ConversationSummary.model_fields
    # chore_chat_last_message_preview — both fields nullable (None for empty rows).
    assert "last_message_preview" in ConversationSummary.model_fields
    assert "last_message_at" in ConversationSummary.model_fields
    assert "messages" in ConversationDetail.model_fields
    assert "data" in ConversationsListResponse.model_fields
    assert "role" in MessageWire.model_fields
    assert "content" in SendMessageRequest.model_fields


def test_message_role_and_sse_event_type_constants_align_with_db_check() -> None:
    """Wire constants enumerate exactly the values DB CHECK accepts.

    Source of truth — DB CHECK in migrations/versions/0007_conversations_messages.py
    constraint ``messages_role_check`` (user / assistant / tool). Drift here would
    silently break enums.ts (Story 4.4) or violate the FE/BE source-of-truth gate.
    """
    from backend.app.api.v1.schemas import (
        MESSAGE_ROLE_VALUES,
        SSE_EVENT_TYPE_VALUES,
    )

    assert set(MESSAGE_ROLE_VALUES) == {"user", "assistant", "tool"}
    assert set(SSE_EVENT_TYPE_VALUES) == {"token", "tool_call", "tool_result", "done"}
