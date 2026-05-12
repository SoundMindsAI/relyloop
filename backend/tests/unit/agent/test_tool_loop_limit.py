"""Loop-limit termination (feat_chat_agent Story 2.5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.agent.events import DoneEvent
from backend.app.agent.orchestrator import MAX_LOOP_ITERATIONS, run_turn

from .conftest import capability_ok, make_tool_call_chunks


@pytest.mark.asyncio
async def test_runaway_tool_loop_terminates_with_error(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """Mocked OpenAI always returns a tool_call → orchestrator stops after MAX_LOOP_ITERATIONS."""
    # Return a fresh async iterator on each call so the loop can drain N times.
    call_count = {"n": 0}

    async def _create(**_: Any) -> AsyncIterator[Any]:
        call_count["n"] += 1
        chunks = make_tool_call_chunks(
            call_id=f"call_{call_count['n']}",
            name="list_clusters",
            arguments="{}",
        )

        async def _iter() -> AsyncIterator[Any]:
            for c in chunks:
                yield c

        return _iter()

    fake_openai_client.chat.completions.create = _create

    # Mock the tool impl so we don't hit the DB.
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
        events = []
        async for ev in run_turn(
            conversation_id="conv_1",
            history=[],
            last_user_text="list every cluster",
            last_assistant_text=None,
            degraded_notice_already_sent=False,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            events.append(ev)

    done_events = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done_events) == 1
    assert done_events[-1].error == "tool_loop_limit_exceeded"
    assert call_count["n"] == MAX_LOOP_ITERATIONS
