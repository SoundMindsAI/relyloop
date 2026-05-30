# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``messages`` ORM model (feat_chat_agent Story 1.2).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"messages" and
the ``0007_conversations_messages`` migration.

``content`` is JSONB to accommodate the variable shapes of user / assistant /
tool payloads (text vs. tool-call delta vs. tool-result JSON):

* ``user`` rows: ``{"text": "tune product_search overnight"}``
* ``assistant`` rows: ``{"text": "..."}`` or ``{"text": "...", "kind": "system_notice"}``
  (degraded-mode notice per spec FR-3)
* ``tool`` rows: ``{"result": ...}`` on success,
  ``{"error": "<code>", "message": "..."}`` on failure

``tool_calls`` is the assistant-turn's ``[{id, type, function: {name, arguments}}]``
array per OpenAI's function-calling protocol — NULL for user + tool rows.

The ``role`` CHECK constraint mirrors the wire-shape Literal
``backend/app/api/v1/schemas.py:MessageRoleWire`` (defense-in-depth — the two
agree at migration time and any future drift is a migration bug).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Message(Base):
    """One persisted message in a conversation (user, assistant, or tool result)."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'tool')",
            name="messages_role_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``user | assistant | tool`` (CHECK enforced)."""
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """Payload shape varies by role — see module docstring."""
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    """OpenAI-shaped ``[{id, type, function: {name, arguments}}]`` array on
    assistant turns that invoked tools; NULL otherwise."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
