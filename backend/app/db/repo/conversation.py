"""Conversation + Message repository (feat_chat_agent Story 1.3).

Per CLAUDE.md "Repository Layer": one file per aggregate. ``conversations``
and ``messages`` form a single aggregate (messages have no independent
lifecycle — they're always queried via their conversation parent), so both
live in this module.

Every function takes ``db: AsyncSession`` first, stages via ``db.flush()``,
and lets the caller commit.

Cursor pagination matches the ``backend.app.db.repo.study`` precedent:
``(created_at, id)`` ordering DESC with row-value comparison hand-rolled
for portability.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Conversation, Message


async def create_conversation(
    db: AsyncSession,
    *,
    conversation_id: str,
    title: str | None,
) -> Conversation:
    """Stage a new ``Conversation`` row. Caller commits."""
    conversation = Conversation(id=conversation_id, title=title)
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def get_conversation(db: AsyncSession, conversation_id: str) -> Conversation | None:
    """Return the conversation, or None if missing or soft-deleted."""
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.deleted_at.is_(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_conversations(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
) -> Sequence[Conversation]:
    """Cursor-paginated conversation list, newest first.

    Order: ``created_at DESC, id DESC``. Filters soft-deleted rows
    (``deleted_at IS NULL``). Limit clamped at 200.
    """
    stmt = select(Conversation).where(Conversation.deleted_at.is_(None))
    if cursor is not None:
        cursor_at, cursor_id = cursor
        stmt = stmt.where(
            or_(
                Conversation.created_at < cursor_at,
                and_(Conversation.created_at == cursor_at, Conversation.id < cursor_id),
            )
        )
    stmt = stmt.order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(
        min(limit, 200)
    )
    return list((await db.execute(stmt)).scalars().all())


async def count_conversations(db: AsyncSession) -> int:
    """COUNT(*) non-soft-deleted conversations (for the ``X-Total-Count`` header)."""
    stmt = select(func.count(Conversation.id)).where(Conversation.deleted_at.is_(None))
    return int((await db.execute(stmt)).scalar_one())


async def soft_delete_conversation(db: AsyncSession, conversation_id: str) -> Conversation | None:
    """Set ``deleted_at = now()`` on the row.

    Returns the updated model, or None if the row was missing or already
    soft-deleted. Caller commits.
    """
    stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.deleted_at.is_(None),
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    row.deleted_at = datetime.now(UTC)
    await db.flush()
    return row


async def update_conversation_title(
    db: AsyncSession, conversation_id: str, title: str
) -> Conversation | None:
    """Set ``title`` on the row.

    Used by ``backend.app.services.agent_chat`` to auto-generate the title
    from the first user message when ``title IS NULL`` (FR-1). Caller commits.
    Idempotent — safe to call on a row whose title is already set, though
    ``agent_chat`` only calls it when the current title is None.
    """
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    row.title = title
    await db.flush()
    return row


async def list_conversations_with_message_counts(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
) -> Sequence[tuple[Conversation, int]]:
    """Cursor-paginated conversation list joined with per-conversation message counts.

    Used by ``GET /api/v1/conversations`` to populate
    ``ConversationSummary.message_count`` in a single round-trip
    (LEFT OUTER JOIN ``messages`` + GROUP BY) instead of N+1 queries.

    Returns ``[(Conversation, count), ...]`` in the same order as
    ``list_conversations`` (newest first; soft-deleted filtered). Limit
    clamped at 200.
    """
    count_col = func.count(Message.id).label("message_count")
    stmt = (
        select(Conversation, count_col)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.deleted_at.is_(None))
        .group_by(Conversation.id)
    )
    if cursor is not None:
        cursor_at, cursor_id = cursor
        stmt = stmt.where(
            or_(
                Conversation.created_at < cursor_at,
                and_(Conversation.created_at == cursor_at, Conversation.id < cursor_id),
            )
        )
    stmt = stmt.order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(
        min(limit, 200)
    )
    return [(row[0], int(row[1])) for row in (await db.execute(stmt)).all()]


async def create_message(
    db: AsyncSession,
    *,
    message_id: str,
    conversation_id: str,
    role: str,
    content: dict[str, Any],
    tool_calls: list[dict[str, Any]] | None = None,
) -> Message:
    """Stage a new ``Message`` row. Caller commits.

    ``role`` is validated at the DB level by ``messages_role_check`` (must be
    one of ``user | assistant | tool``). Service-layer code should call this
    only from inside an ``agent_chat`` event-handler loop — see CLAUDE.md
    Absolute Rule for ``feat_chat_agent``: ``agent_chat`` is the sole owner
    of message persistence.
    """
    message = Message(
        id=message_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def list_messages(
    db: AsyncSession,
    conversation_id: str,
) -> Sequence[Message]:
    """All messages for a conversation, ordered by ``created_at ASC, id ASC``.

    No pagination — message counts are bounded by the tool-loop limit
    (10 iterations × at most ~5 messages per iteration = ~50 max per turn).
    Service-layer code (``agent_chat``) applies the defensive 100-message
    cap on the history fed back to OpenAI.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())
