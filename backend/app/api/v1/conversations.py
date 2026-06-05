# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Conversation CRUD + SSE messages router (feat_chat_agent Epic 3).

Five endpoints under ``/api/v1`` (Stories 3.1 + 3.2):

* ``POST   /api/v1/conversations`` — create a conversation.
* ``GET    /api/v1/conversations`` — cursor-paginated list with message_count.
* ``GET    /api/v1/conversations/{id}`` — detail with full message history.
* ``DELETE /api/v1/conversations/{id}`` — soft-delete.
* ``POST   /api/v1/conversations/{id}/messages`` — send a user message;
  returns ``text/event-stream`` driven by :func:`agent_chat.send_user_message`.

Helpers (``_err``, ``_encode_cursor``, ``_decode_cursor``) mirror the existing
copies in :mod:`backend.app.api.v1.proposals` / :mod:`backend.app.api.v1.studies`;
the shared-helper hoist is the standing ``chore_router_helpers_hoist`` follow-up.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated

import uuid_utils
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.health import get_redis_client
from backend.app.api.v1.schemas import (
    ConversationDetail,
    ConversationsListResponse,
    ConversationSummary,
    CreateConversationRequest,
    MessageWire,
    SendMessageRequest,
)
from backend.app.core.logging import get_logger
from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.repo._fts import rank_active, rank_bucket_of
from backend.app.db.repo._sort import (
    decode_cursor as _sort_decode_cursor,
)
from backend.app.db.repo._sort import (
    encode_cursor as _sort_encode_cursor,
)
from backend.app.db.session import get_db
from backend.app.llm.budget_gate import peek_daily_total
from backend.app.services import agent_chat

router = APIRouter()
logger = get_logger(__name__)

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


def _err(status_code: int, code: str, message: str, retryable: bool) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error_code": code, "message": message, "retryable": retryable},
    )


def _encode_cursor(created_at: datetime, row_id: str) -> str:
    payload = json.dumps([created_at.isoformat(), row_id]).encode()
    return base64.urlsafe_b64encode(payload).decode()


def _decode_cursor(raw: str) -> tuple[datetime, str]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        return datetime.fromisoformat(decoded[0]), str(decoded[1])
    except Exception as exc:  # noqa: BLE001
        raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc


@router.post(
    "/conversations",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
    tags=["conversations"],
)
async def create_conversation_endpoint(
    body: CreateConversationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationSummary:
    """Create a new conversation. Title is optional (FR-1 auto-generates from first message)."""
    conversation_id = str(uuid_utils.uuid7())
    row = await repo.create_conversation(
        db,
        conversation_id=conversation_id,
        title=body.title,
    )
    await db.commit()
    return ConversationSummary(
        id=row.id,
        title=row.title,
        created_at=row.created_at,
        message_count=0,
        last_message_preview=None,
        last_message_at=None,
    )


@router.get(
    "/conversations",
    response_model=ConversationsListResponse,
    tags=["conversations"],
)
async def list_conversations_endpoint(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    since: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=2, max_length=200)] = None,
) -> ConversationsListResponse:
    """List conversations newest-first with per-row message_count + X-Total-Count header.

    ``?since=`` (Story 1.5 — closes api-conventions.md drift) filters by
    ``created_at >= since``. ``?q=`` (Story 1.2) is a Postgres FTS match
    against ``search_vector`` (coalesce(title, '')); 2-200 chars.
    """
    # feat_fts_rank_ordering: conversations have no ?sort=, so when ?q= is
    # present the relevance ordering is active and the cursor value-half is the
    # int rank_bucket (decoded via the shared _sort helper) rather than a
    # datetime (the local _decode_cursor).
    is_rank = rank_active(q, None)
    parsed_cursor: tuple[object, str] | None = None
    if cursor:
        if is_rank:
            try:
                parsed_cursor = _sort_decode_cursor(cursor, value_is_datetime=False)
            except Exception as exc:
                raise _err(422, "VALIDATION_ERROR", f"invalid cursor: {exc}", False) from exc
        else:
            parsed_cursor = _decode_cursor(cursor)
    rows = list(
        await repo.list_conversations_with_preview_data(
            db,
            cursor=parsed_cursor,
            limit=limit + 1,
            since=since,
            q=q,
        )
    )
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    total = await repo.count_conversations(db, since=since, q=q)
    response.headers["X-Total-Count"] = str(total)
    next_cursor: str | None = None
    if has_more and rows:
        last_row = rows[-1][0]
        if is_rank:
            next_cursor = _sort_encode_cursor(rank_bucket_of(last_row), last_row.id)
        else:
            next_cursor = _encode_cursor(last_row.created_at, last_row.id)
    return ConversationsListResponse(
        data=[
            ConversationSummary(
                id=row.id,
                title=row.title,
                created_at=row.created_at,
                message_count=count,
                last_message_preview=preview,
                last_message_at=last_at,
            )
            for row, count, preview, last_at in rows
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    tags=["conversations"],
)
async def get_conversation_endpoint(
    conversation_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationDetail:
    """Return the conversation's full message history."""
    conversation = await repo.get_conversation(db, conversation_id)
    if conversation is None:
        raise _err(
            404,
            "CONVERSATION_NOT_FOUND",
            f"conversation {conversation_id} not found",
            False,
        )
    messages = await repo.list_messages(db, conversation_id)
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=[
            MessageWire(
                id=m.id,
                role=m.role,  # validated by DB CHECK
                content=m.content or {},
                tool_calls=m.tool_calls,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["conversations"],
)
async def delete_conversation_endpoint(
    conversation_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Soft-delete the conversation; subsequent reads return 404."""
    row = await repo.soft_delete_conversation(db, conversation_id)
    if row is None:
        raise _err(
            404,
            "CONVERSATION_NOT_FOUND",
            f"conversation {conversation_id} not found",
            False,
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# POST /api/v1/conversations/{id}/messages — SSE (Story 3.2)
# ---------------------------------------------------------------------------


@router.post(
    "/conversations/{conversation_id}/messages",
    tags=["conversations"],
)
async def post_message_endpoint(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> StreamingResponse:
    """Send a user message and stream the assistant turn as SSE.

    Preflight (in order; returns plain JSON envelope, NOT a partial stream):
      A. Conversation exists → else 404 ``CONVERSATION_NOT_FOUND``.
      B. ``Settings.openai_api_key`` populated → else 503 ``OPENAI_NOT_CONFIGURED``.
      C. Daily budget peek under cap → else 503 ``OPENAI_BUDGET_EXCEEDED``.

    Successful preflight returns a ``StreamingResponse(text/event-stream)``
    driven by :func:`agent_chat.send_user_message`.
    """
    conversation = await repo.get_conversation(db, conversation_id)
    if conversation is None:
        raise _err(
            404,
            "CONVERSATION_NOT_FOUND",
            f"conversation {conversation_id} not found",
            False,
        )

    settings = get_settings()
    if not settings.openai_api_key:
        raise _err(
            503,
            "OPENAI_NOT_CONFIGURED",
            "OPENAI_API_KEY_FILE is empty; cannot dispatch chat turn",
            False,
        )

    if settings.openai_daily_budget_usd > 0:
        current = await peek_daily_total(redis)
        if current >= settings.openai_daily_budget_usd:
            raise _err(
                503,
                "OPENAI_BUDGET_EXCEEDED",
                f"daily total ${current:.2f} >= budget ${settings.openai_daily_budget_usd:.2f}",
                True,
            )

    arq_pool = getattr(request.app.state, "arq_pool", None)

    return StreamingResponse(
        agent_chat.send_user_message(
            db,
            redis,
            arq_pool,
            settings,
            conversation_id=conversation_id,
            user_text=body.content.text,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
