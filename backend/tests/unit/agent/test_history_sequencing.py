# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""OpenAI history sequencing (feat_chat_agent Story 2.5).

After a streamed assistant turn with tool_calls, the orchestrator must append
the assistant-tool-calls message to ``history`` BEFORE any role:tool result
messages. Skipping this yields a 400 from the next chat.completions.create:
"An assistant message with 'tool_calls' must be followed by tool messages
responding to each tool_call_id".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.agent.orchestrator import run_turn

from .conftest import capability_ok, make_text_chunks, make_tool_call_chunks


@pytest.mark.asyncio
async def test_assistant_with_tool_calls_precedes_tool_role_in_history(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """The assistant tool-call message lands in history BEFORE the role:tool entry."""
    captured_messages: list[list[dict[str, Any]]] = []
    streams = [
        make_tool_call_chunks(
            call_id="call_1",
            name="list_clusters",
            arguments="{}",
        ),
        make_text_chunks("done"),
    ]
    stream_iter = iter(streams)

    async def _create(**kwargs: Any) -> AsyncIterator[Any]:
        # Snapshot the messages array on every call so we can inspect ordering.
        captured_messages.append([dict(m) for m in kwargs["messages"]])
        chunks = next(stream_iter)

        async def _iter() -> AsyncIterator[Any]:
            for c in chunks:
                yield c

        return _iter()

    fake_openai_client.chat.completions.create = _create

    with (
        patch(
            "backend.app.agent.orchestrator.read_capability_result",
            AsyncMock(return_value=capability_ok()),
        ),
        patch.dict(
            "backend.app.agent.orchestrator.TOOL_REGISTRY",
            {"list_clusters": AsyncMock(return_value={"clusters": []})},
        ),
    ):
        async for _ in run_turn(
            conversation_id="conv_1",
            history=[],
            last_user_text="show clusters",
            last_assistant_text=None,
            degraded_notice_already_sent=False,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            pass

    # Two OpenAI calls were made; the second should see the assistant-with-
    # tool_calls message PRECEDING the role:tool entry.
    assert len(captured_messages) == 2
    second_call = captured_messages[1]
    assistant_idx = next(
        (i for i, m in enumerate(second_call) if m["role"] == "assistant" and m.get("tool_calls")),
        None,
    )
    tool_idx = next(
        (i for i, m in enumerate(second_call) if m["role"] == "tool"),
        None,
    )
    assert assistant_idx is not None, f"no assistant-with-tool_calls message: {second_call}"
    assert tool_idx is not None, f"no role:tool message: {second_call}"
    assert assistant_idx < tool_idx, (
        f"assistant must precede tool result in history; got {assistant_idx=} {tool_idx=}"
    )
