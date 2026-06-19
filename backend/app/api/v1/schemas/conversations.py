# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Chat-agent conversation / message / send-message models (feat_chat_agent)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.api.v1._wire_types import (
    MessageRoleWire,
)

# ---------------------------------------------------------------------------
# feat_chat_agent (Stories 3.1 + 3.2)
# ---------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    """``POST /api/v1/conversations`` body."""

    title: str | None = Field(default=None, max_length=200)


class MessageWire(BaseModel):
    """One row of ``GET /api/v1/conversations/{id}.messages``."""

    id: str
    role: MessageRoleWire
    content: dict[str, Any]
    tool_calls: list[dict[str, Any]] | None = None
    created_at: datetime


class ConversationSummary(BaseModel):
    """``GET /api/v1/conversations`` row + ``POST`` 201 body.

    ``last_message_preview`` is the most recent user / assistant message's
    ``content.text``, truncated at the repo layer to 120 chars (with ``…``
    suffix when cut). Tool-role rows and assistant rows whose ``content.kind``
    is ``system_notice`` are skipped. ``None`` for brand-new conversations
    with no qualifying messages — see ``chore_chat_last_message_preview``.

    ``last_message_at`` is the ``created_at`` of that same row, or ``None``
    for empty conversations. The list page uses it to render "when did
    anyone last touch this thread" instead of the conversation's
    ``created_at``.
    """

    id: str
    title: str | None
    created_at: datetime
    message_count: int
    last_message_preview: str | None = None
    last_message_at: datetime | None = None


class ConversationDetail(BaseModel):
    """``GET /api/v1/conversations/{id}`` response."""

    id: str
    title: str | None
    created_at: datetime
    messages: list[MessageWire]


class ConversationsListResponse(BaseModel):
    """``GET /api/v1/conversations`` response."""

    data: list[ConversationSummary]
    next_cursor: str | None
    has_more: bool


class SendMessageRequestContent(BaseModel):
    """Sub-shape inside :class:`SendMessageRequest`."""

    text: str = Field(min_length=1, max_length=20_000)


class SendMessageRequest(BaseModel):
    """``POST /api/v1/conversations/{id}/messages`` body (Story 3.2)."""

    role: Literal["user"] = "user"
    content: SendMessageRequestContent
