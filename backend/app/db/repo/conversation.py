# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Conversation, Message
from backend.app.db.repo._fts import fts_predicate, rank_active, rank_bucket_expr

PREVIEW_MAX_CHARS = 120
"""Cap for ``ConversationSummary.last_message_preview`` (chore_chat_last_message_preview).

Truncated at the repo layer so the wire shape is deterministic — frontend
renders the string verbatim, no per-component truncation drift.
"""


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


async def count_conversations(
    db: AsyncSession,
    *,
    since: datetime | None = None,
    q: str | None = None,
) -> int:
    """COUNT(*) non-soft-deleted conversations (for the ``X-Total-Count`` header).

    ``since`` filters by ``created_at >= since`` (Story 1.5 — closes
    api-conventions.md drift). ``q`` is an optional Postgres FTS match
    against ``search_vector`` (conversations.title).
    """
    stmt = select(func.count(Conversation.id)).where(Conversation.deleted_at.is_(None))
    if since is not None:
        stmt = stmt.where(Conversation.created_at >= since)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
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


async def list_conversations_with_preview_data(
    db: AsyncSession,
    *,
    cursor: tuple[Any, str] | None = None,
    limit: int = 50,
    since: datetime | None = None,
    q: str | None = None,
) -> Sequence[tuple[Conversation, int, str | None, datetime | None]]:
    """Cursor-paginated conversation list with message count + last-message preview.

    Used by ``GET /api/v1/conversations`` to populate
    :class:`backend.app.api.v1.schemas.ConversationSummary` in a single
    round-trip. Three joins against ``messages``:

    * COUNT via LEFT OUTER JOIN + GROUP BY for ``message_count``.
    * LATERAL subquery for the most-recent human-readable message's
      ``content->>'text'`` (the preview) and ``created_at``
      (``last_message_at``).

    The LATERAL subquery filters to user / assistant rows whose JSONB
    content has a ``text`` field and whose ``kind`` is not
    ``system_notice``, so tool-result payloads and degraded-mode banners
    never surface as preview text. The existing
    ``messages_conversation_idx`` on ``(conversation_id, created_at)``
    (migration ``0007_conversations_messages``) covers the ORDER BY ...
    LIMIT 1 lookup; no new index needed.

    The preview is truncated at :data:`PREVIEW_MAX_CHARS` here (single
    truncation site) — the API + frontend render the value verbatim.

    Returns ``[(Conversation, count, preview, last_at), ...]`` in the
    same order as :func:`list_conversations` (newest first;
    soft-deleted filtered). Limit clamped at 200.
    """
    # Pre-aggregate the count in its own subquery so the outer SELECT
    # avoids a GROUP BY over the (potentially large) JSONB-extracted
    # preview_text column. With the count collapsed here, both outer
    # joins are 1:0/1:1 per conversation — no top-level aggregation.
    count_subq = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    # LATERAL subquery: most-recent qualifying message per parent conversation.
    # `correlate_except(Message)` keeps `messages` in the subquery's FROM
    # clause; SQLAlchemy's default auto-correlation would otherwise strip
    # both tables and surface as "Select returned no FROM clauses." Only
    # `Conversation` is the outer correlation reference.
    preview_subq = (
        select(
            Message.content["text"].astext.label("preview_text"),
            Message.created_at.label("last_at"),
        )
        .where(
            Message.conversation_id == Conversation.id,
            Message.role.in_(("user", "assistant")),
            Message.content.has_key("text"),  # noqa: W601 — JSONB ? operator, not Python dict
            func.coalesce(Message.content["kind"].astext, "") != "system_notice",
        )
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate_except(Message)
        .lateral("last_msg")
    )

    # feat_fts_rank_ordering: conversations have no ?sort= param, so when ?q=
    # is present the relevance ordering is always in effect. The rank bucket
    # is added as a 5th selected column and stashed onto the Conversation as
    # `_fts_rank_bucket` for the router's next cursor; the keyset + ORDER BY
    # switch to (rank_bucket DESC, id DESC).
    is_rank = rank_active(q, None)
    rank_col = rank_bucket_expr(q) if (is_rank and q is not None) else None
    base_cols: list[Any] = [
        Conversation,
        func.coalesce(count_subq.c.message_count, 0).label("message_count"),
        preview_subq.c.preview_text,
        preview_subq.c.last_at,
    ]
    if rank_col is not None:
        base_cols.append(rank_col.label("rb"))
    stmt = (
        select(*base_cols)
        .outerjoin(count_subq, count_subq.c.conversation_id == Conversation.id)
        .outerjoin(preview_subq, true())
        .where(Conversation.deleted_at.is_(None))
    )
    if since is not None:
        stmt = stmt.where(Conversation.created_at >= since)
    fts = fts_predicate(q)
    if fts is not None:
        stmt = stmt.where(fts)
    if cursor is not None:
        cursor_at, cursor_id = cursor
        if rank_col is not None:
            stmt = stmt.where(
                or_(
                    rank_col < cursor_at,
                    and_(rank_col == cursor_at, Conversation.id < cursor_id),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    Conversation.created_at < cursor_at,
                    and_(Conversation.created_at == cursor_at, Conversation.id < cursor_id),
                )
            )
    if rank_col is not None:
        stmt = stmt.order_by(rank_col.desc(), Conversation.id.desc()).limit(min(limit, 200))
    else:
        stmt = stmt.order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(
            min(limit, 200)
        )

    def _truncate(text: str | None) -> str | None:
        if text is None:
            return None
        if len(text) <= PREVIEW_MAX_CHARS:
            return text
        return text[: PREVIEW_MAX_CHARS - 1] + "…"

    out: list[tuple[Conversation, int, str | None, datetime | None]] = []
    for row in (await db.execute(stmt)).all():
        conv = row[0]
        if rank_col is not None:
            conv._fts_rank_bucket = row[4]
        out.append((conv, int(row[1]), _truncate(row[2]), row[3]))
    return out


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
