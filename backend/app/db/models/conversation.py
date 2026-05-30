# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``conversations`` ORM model (feat_chat_agent Story 1.2).

Full MVP1 shape per ``docs/01_architecture/data-model.md`` §"conversations" and
the ``0007_conversations_messages`` migration.

Soft-deletable: ``deleted_at`` is populated by
``DELETE /api/v1/conversations/{id}``; list/get queries filter
``deleted_at IS NULL``. The child ``messages`` table cascades on hard purge
(``ON DELETE CASCADE``), but the user-facing default is soft delete —
the messages stay so an admin runbook can recover the conversation if
needed before hard purge.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class Conversation(Base):
    """A chat conversation between the operator and the agent."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Optional human-readable label. ``agent_chat`` auto-derives from the first
    user message when null (per FR-1)."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Soft-delete tombstone. Set by ``DELETE /api/v1/conversations/{id}``."""
