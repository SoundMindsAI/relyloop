# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Chat-agent service layer (feat_chat_agent Story 2.6).

This module is the **sole owner** of chat-feature message persistence.
The orchestrator (Story 2.5) is a pure generator; this service consumes its
events, mirrors the 4 wire events to SSE, writes rows in response to the 2
persistence events, and implements FR-1 title auto-generation.

Per CLAUDE.md feat_chat_agent invariant: a grep across ``backend/app/agent/``
+ ``backend/app/api/v1/conversations.py`` for ``create_message`` finds zero
hits. The router calls into ``send_user_message``; the orchestrator yields
:class:`AssistantMessagePersistEvent` / :class:`ToolMessagePersistEvent`
markers; we are the only writer.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import uuid_utils
from arq.connections import ArqRedis
from fastapi import HTTPException
from openai import AsyncOpenAI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agent.context import ToolContext
from backend.app.agent.events import (
    AssistantMessagePersistEvent,
    DoneEvent,
    ToolCallEvent,
    ToolMessagePersistEvent,
)
from backend.app.agent.orchestrator import SYSTEM_PROMPT, run_turn
from backend.app.core.logging import get_logger
from backend.app.core.settings import Settings
from backend.app.db import repo
from backend.app.db.models import Message

logger = get_logger(__name__)

TITLE_MAX_LENGTH = 80
"""Truncation cap for auto-generated titles (FR-1)."""

HISTORY_MAX_MESSAGES = 100
"""Defensive cap on messages fed back to OpenAI per cycle-2 F14.

A full context-window-management strategy (summarization, smart truncation) is
deferred to MVP2 — see ``bug_chat_long_conversation_truncation_mvp2`` idea file.
"""


def _derive_title(user_text: str) -> str | None:
    """Derive an auto-title from the first user message (FR-1).

    ``title = user_text[:80].strip()`` if length ≤ 80 else
    ``user_text[:77].strip() + "..."``. Returns None for empty input
    (defensive — the API layer should reject empty messages, but we don't
    want to crash if it doesn't).
    """
    cleaned = user_text.strip()
    if not cleaned:
        return None
    if len(cleaned) <= TITLE_MAX_LENGTH:
        return cleaned
    return cleaned[: TITLE_MAX_LENGTH - 3].rstrip() + "..."


def _row_to_openai_message(message: Message) -> dict[str, Any]:
    """Convert a persisted ``Message`` row into the OpenAI chat-history shape."""
    if message.role == "tool":
        # ``tool_calls`` field on a tool-role row carries the tool_call_id (we
        # stored it via the ToolMessagePersistEvent flow). Tool results are
        # re-wrapped in <tool_result>...</tool_result> delimiters on every
        # replay so the prompt-injection invariant holds across turns
        # (per GPT-5.5 final-review F1 — without this, hostile content from
        # a tool's first-turn output would influence the LLM in subsequent
        # turns of the same conversation).
        from backend.app.agent.orchestrator import _wrap_tool_result_for_llm

        content_field = message.content or {}
        return {
            "role": "tool",
            "tool_call_id": _extract_tool_call_id(message),
            "content": _wrap_tool_result_for_llm(content_field),
        }
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": (message.content or {}).get("text") or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": tc.get("arguments", ""),
                    },
                }
                for tc in message.tool_calls
            ],
        }
    # Plain user / assistant text message.
    return {
        "role": message.role,
        "content": (message.content or {}).get("text", ""),
    }


def _truncate_preserving_tool_groups(messages: list[Message], max_kept: int) -> list[Message]:
    """Tail-truncate ``messages`` without cutting a tool-call group in half.

    OpenAI's protocol requires every assistant-tool_calls message to be
    immediately followed by its corresponding ``role="tool"`` results, AND
    every ``role="tool"`` row to be preceded by an assistant-tool_calls
    message that referenced the same tool_call_id. A naive ``messages[-N:]``
    risks landing the cut mid-group → 400 from the next chat.completions.create.

    Strategy: take the naive tail slice, then advance the cut point forward
    until we land on a clean boundary — either a user message or a plain
    assistant text message. This drops at most one extra group worth of rows
    (per GPT-5.5 final-review F4).
    """
    if len(messages) <= max_kept:
        return messages
    cut = len(messages) - max_kept
    while cut < len(messages):
        m = messages[cut]
        if m.role == "user":
            break
        if m.role == "assistant" and not m.tool_calls:
            break
        cut += 1
    return messages[cut:]


def _extract_tool_call_id(message: Message) -> str:
    """Pull the tool_call_id off a tool-role message.

    We persist tool messages with ``content={"result": ...}`` or
    ``{"error": ..., "message": ...}``; the tool_call_id is stored separately
    in the ``Message.tool_calls`` JSONB by convention. We use a simple
    convention: tool-role rows carry ``tool_calls=[{"id": "<id>"}]`` set by
    ``send_user_message`` when persisting the ``ToolMessagePersistEvent``.
    """
    if message.tool_calls and isinstance(message.tool_calls, list) and message.tool_calls:
        tc = message.tool_calls[0]
        if isinstance(tc, dict) and "id" in tc:
            return str(tc["id"])
    return ""


async def send_user_message(
    db: AsyncSession,
    redis: Redis,
    arq_pool: ArqRedis | None,
    settings: Settings,
    *,
    conversation_id: str,
    user_text: str,
) -> AsyncIterator[bytes]:
    """Process one user message, drive the orchestrator, persist + stream SSE bytes.

    Sole owner of chat-feature message persistence (CLAUDE.md feat_chat_agent
    invariant). The orchestrator yields events; this service writes rows.

    1. Verify the conversation exists and is not soft-deleted.
    2. Persist the user message (and auto-generate the conversation title if
       it's still NULL); commit so the history is durable before SSE opens.
    3. Build the OpenAI message history from ``list_messages`` (capped at
       ``HISTORY_MAX_MESSAGES`` for defense-in-depth).
    4. Run :func:`run_turn` with a fresh AsyncOpenAI client. For each event:
       - 4 wire events → forward to SSE
       - ``AssistantMessagePersistEvent`` / ``ToolMessagePersistEvent`` →
         persist via ``repo.create_message`` + commit, NOT forwarded to SSE
    5. On unhandled exception, emit a final ``done`` SSE with
       ``error="internal_error"`` so the client doesn't hang.
    6. Emit a structured INFO log per turn (spec §13 NFR-Operability).
    """
    # 1. Conversation existence (defensive double-check; API preflight already ran).
    conversation = await repo.get_conversation(db, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "CONVERSATION_NOT_FOUND",
                "message": f"conversation {conversation_id} not found",
                "retryable": False,
            },
        )

    started_at = time.perf_counter()
    tool_calls_count = 0
    tokens_used: int | None = None
    cost_usd: float | None = None
    loop_iterations: int | None = None

    # 2. Persist the user message + (optionally) auto-generate the title.
    user_message_id = str(uuid_utils.uuid7())
    await repo.create_message(
        db,
        message_id=user_message_id,
        conversation_id=conversation_id,
        role="user",
        content={"text": user_text},
        tool_calls=None,
    )
    if conversation.title is None:
        derived = _derive_title(user_text)
        if derived:
            await repo.update_conversation_title(db, conversation_id, derived)
    await db.commit()

    # 3. Build OpenAI message history.
    all_messages = list(await repo.list_messages(db, conversation_id))
    if len(all_messages) > HISTORY_MAX_MESSAGES:
        logger.warning(
            "chat_history_truncated",
            event_type="chat_history_truncated",
            conversation_id=conversation_id,
            total_messages=len(all_messages),
            kept_messages=HISTORY_MAX_MESSAGES,
        )
        all_messages = _truncate_preserving_tool_groups(all_messages, HISTORY_MAX_MESSAGES)
    history: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    history.extend(_row_to_openai_message(m) for m in all_messages)

    # Compute confirmation-guard inputs from the persisted history (BEFORE the
    # just-inserted user message — the orchestrator gets the user_text as a
    # parameter separately).
    last_assistant_text: str | None = None
    degraded_notice_already_sent = False
    for m in all_messages[:-1]:  # exclude the user message we just inserted
        if m.role == "assistant":
            content_field = m.content or {}
            text = content_field.get("text")
            if isinstance(text, str) and text.strip():
                last_assistant_text = text
            if content_field.get("kind") == "system_notice":
                degraded_notice_already_sent = True

    # 4. Build orchestrator deps + run the turn.
    ctx = ToolContext(
        db=db,
        conversation_id=conversation_id,
        redis=redis,
        arq_pool=arq_pool,
        settings=settings,
    )
    openai_client = AsyncOpenAI(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key or "",
    )

    try:
        async for event in run_turn(
            conversation_id=conversation_id,
            history=history,
            last_user_text=user_text,
            last_assistant_text=last_assistant_text,
            degraded_notice_already_sent=degraded_notice_already_sent,
            ctx=ctx,
            openai_client=openai_client,
        ):
            if isinstance(event, AssistantMessagePersistEvent):
                tool_calls_payload: list[dict[str, Any]] | None = None
                if event.tool_calls:
                    tool_calls_payload = [
                        {
                            "id": tc.get("id"),
                            "name": tc.get("name"),
                            "arguments": tc.get("arguments"),
                        }
                        for tc in event.tool_calls
                    ]
                await repo.create_message(
                    db,
                    message_id=str(uuid_utils.uuid7()),
                    conversation_id=conversation_id,
                    role="assistant",
                    content=event.content,
                    tool_calls=tool_calls_payload,
                )
                if event.usage is not None:
                    tokens_used = (tokens_used or 0) + int(event.usage.get("total_tokens", 0))
                if event.cost_usd is not None:
                    cost_usd = (cost_usd or 0.0) + float(event.cost_usd)
                await db.commit()
                continue
            if isinstance(event, ToolMessagePersistEvent):
                await repo.create_message(
                    db,
                    message_id=str(uuid_utils.uuid7()),
                    conversation_id=conversation_id,
                    role="tool",
                    content=event.content,
                    tool_calls=[{"id": event.tool_call_id}],
                )
                await db.commit()
                continue
            if isinstance(event, ToolCallEvent):
                tool_calls_count += 1
            if isinstance(event, DoneEvent) and event.iterations is not None:
                loop_iterations = event.iterations
            yield event.to_sse_lines().encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "agent_chat: unhandled error in send_user_message",
            conversation_id=conversation_id,
            error_type=type(exc).__name__,
        )
        # Emit a terminal SSE event so the client doesn't hang. The user message
        # is already persisted; this is a recoverable state.
        done = DoneEvent(conversation_id=conversation_id, error="internal_error")
        yield done.to_sse_lines().encode("utf-8")
    finally:
        await openai_client.close()
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "chat_turn_complete",
            event_type="chat_turn_complete",
            conversation_id=conversation_id,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            tool_calls_count=tool_calls_count,
            loop_iterations=loop_iterations,
            duration_ms=duration_ms,
        )


__all__ = [
    "HISTORY_MAX_MESSAGES",
    "TITLE_MAX_LENGTH",
    "send_user_message",
]
