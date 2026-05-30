# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""conversations_messages.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-12 14:30:00.000000

feat_chat_agent Story 1.1 — creates the ``conversations`` and ``messages``
tables in their full MVP1 shape per
``docs/01_architecture/data-model.md`` §"conversations" + §"messages".

* ``conversations`` is the parent table. Soft-deletable via ``deleted_at``;
  list/get queries filter ``deleted_at IS NULL``.
* ``messages`` is the child. ``ON DELETE CASCADE`` so a hard purge of a
  conversation removes its messages. ``role`` CHECK enforces the wire-shape
  Literal in ``backend/app/api/v1/schemas.py:MessageRoleWire``.
* ``content`` is JSONB to accommodate user (``{"text": ...}``), assistant
  (``{"text": ..., "kind"?: "system_notice"}``), and tool (``{"result": ...}``
  or ``{"error": ..., "message": ...}``) payload shapes.
* ``tool_calls`` is JSONB nullable — populated only on assistant turns that
  invoked one or more tools (OpenAI's
  ``[{id, type, function: {name, arguments}}]`` array). NULL for user + tool
  rows.
* ``messages_conversation_idx`` on ``(conversation_id, created_at)`` keeps
  ``list_messages`` (full history scan) ordered without a sort.

Per CLAUDE.md Absolute Rule #5, this migration ships a ``downgrade()`` and
round-trips cleanly: ``alembic upgrade head && alembic downgrade -1 &&
alembic upgrade head``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``conversations`` then ``messages`` (FK-respecting order)."""
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'tool')",
            name="messages_role_check",
        ),
    )
    op.create_index(
        "messages_conversation_idx",
        "messages",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    """Drop ``messages`` (with its index + FK) then ``conversations``."""
    op.drop_index("messages_conversation_idx", table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversations")
