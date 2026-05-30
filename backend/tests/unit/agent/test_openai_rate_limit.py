# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""OpenAI RateLimitError handling (feat_chat_agent Story 2.5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import openai
import pytest

from backend.app.agent.events import DoneEvent, TokenEvent
from backend.app.agent.orchestrator import run_turn

from .conftest import capability_ok


def _make_rate_limit_error() -> openai.RateLimitError:
    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    return openai.RateLimitError("rate limited", response=response, body={"error": "rate limited"})


@pytest.mark.asyncio
async def test_rate_limit_yields_done_event_and_returns(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """openai.RateLimitError → DoneEvent(error='openai_rate_limited'); no further events."""

    async def _create(**_: Any) -> Any:
        raise _make_rate_limit_error()

    fake_openai_client.chat.completions.create = _create

    with patch(
        "backend.app.agent.orchestrator.read_capability_result",
        AsyncMock(return_value=capability_ok()),
    ):
        events = []
        async for ev in run_turn(
            conversation_id="conv_1",
            history=[],
            last_user_text="hi",
            last_assistant_text=None,
            degraded_notice_already_sent=False,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            events.append(ev)

    done_events = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done_events) == 1
    assert done_events[0].error == "openai_rate_limited"
    # No token events emitted before the rate-limit hit.
    assert not any(isinstance(e, TokenEvent) for e in events)
