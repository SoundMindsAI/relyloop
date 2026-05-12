"""Capability-cache degraded path (feat_chat_agent Story 2.5).

When ``read_capability_result`` returns a ``CapabilityResult`` with
``function_calling != "ok"`` (or returns None), the orchestrator:

1. Calls OpenAI with ``tools=[]`` (i.e. no ``tools`` kwarg).
2. Emits an ``AssistantMessagePersistEvent`` with
   ``content.kind == "system_notice"`` BEFORE any TokenEvent — but only on the
   first degraded turn (``degraded_notice_already_sent=False``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.agent.events import AssistantMessagePersistEvent, TokenEvent
from backend.app.agent.orchestrator import run_turn

from .conftest import capability_degraded, make_text_chunks


@pytest.mark.asyncio
async def test_first_degraded_turn_emits_system_notice(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """tools=[] AND a system_notice persistence event before any token."""
    captured_kwargs: dict[str, Any] = {}

    async def _create(**kwargs: Any) -> AsyncIterator[Any]:
        captured_kwargs.update(kwargs)
        chunks = make_text_chunks("Cannot dispatch tools right now.")

        async def _iter() -> AsyncIterator[Any]:
            for c in chunks:
                yield c

        return _iter()

    fake_openai_client.chat.completions.create = _create

    with patch(
        "backend.app.agent.orchestrator.read_capability_result",
        AsyncMock(return_value=capability_degraded()),
    ):
        events = []
        async for ev in run_turn(
            conversation_id="conv_1",
            history=[],
            last_user_text="hello",
            last_assistant_text=None,
            degraded_notice_already_sent=False,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            events.append(ev)

    assert "tools" not in captured_kwargs, "OpenAI called with tools=[] not omitted"
    notice_indices = [
        i
        for i, e in enumerate(events)
        if isinstance(e, AssistantMessagePersistEvent) and e.content.get("kind") == "system_notice"
    ]
    assert notice_indices, "no system_notice persist event emitted"
    first_token_idx = next((i for i, e in enumerate(events) if isinstance(e, TokenEvent)), None)
    assert first_token_idx is not None
    assert notice_indices[0] < first_token_idx, "system_notice must precede the first TokenEvent"


@pytest.mark.asyncio
async def test_subsequent_degraded_turns_suppress_notice(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """``degraded_notice_already_sent=True`` → no system_notice on this turn."""

    async def _create(**_: Any) -> AsyncIterator[Any]:
        chunks = make_text_chunks("Still degraded.")

        async def _iter() -> AsyncIterator[Any]:
            for c in chunks:
                yield c

        return _iter()

    fake_openai_client.chat.completions.create = _create

    with patch(
        "backend.app.agent.orchestrator.read_capability_result",
        AsyncMock(return_value=capability_degraded()),
    ):
        events = []
        async for ev in run_turn(
            conversation_id="conv_1",
            history=[],
            last_user_text="any updates?",
            last_assistant_text="Tool dispatch is unavailable.",
            degraded_notice_already_sent=True,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            events.append(ev)

    notice_events = [
        e
        for e in events
        if isinstance(e, AssistantMessagePersistEvent) and e.content.get("kind") == "system_notice"
    ]
    assert not notice_events, "system_notice should NOT repeat on subsequent degraded turns"
