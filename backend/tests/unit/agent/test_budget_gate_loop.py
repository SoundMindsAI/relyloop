# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Security audit 2026-07-11 finding #8 — the chat tool loop enforces the daily
budget before EACH completion, not only once per turn."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.agent.events import DoneEvent, TokenEvent
from backend.app.agent.orchestrator import run_turn

from .conftest import capability_ok


@pytest.mark.asyncio
async def test_budget_exceeded_before_first_call_yields_done(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """When the running daily total already breaches the cap, the loop yields
    DoneEvent(error='openai_budget_exceeded') and never calls OpenAI."""
    fake_ctx.settings.openai_daily_budget_usd = 5.0

    async def _must_not_call(**_: Any) -> Any:
        pytest.fail("OpenAI MUST NOT be called once the budget is exceeded")

    fake_openai_client.chat.completions.create = _must_not_call

    with (
        patch(
            "backend.app.agent.orchestrator.read_capability_result",
            AsyncMock(return_value=capability_ok()),
        ),
        patch(
            "backend.app.agent.orchestrator.peek_daily_total",
            AsyncMock(return_value=9.99),  # already over the 5.0 cap
        ),
    ):
        events = [
            ev
            async for ev in run_turn(
                conversation_id="conv_1",
                history=[],
                last_user_text="hi",
                last_assistant_text=None,
                degraded_notice_already_sent=False,
                ctx=fake_ctx,
                openai_client=fake_openai_client,
            )
        ]

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert done[0].error == "openai_budget_exceeded"
    assert not [e for e in events if isinstance(e, TokenEvent)]
