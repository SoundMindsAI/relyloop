# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Validation-failure dispatch (feat_chat_agent Story 2.5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from backend.app.agent.events import DoneEvent, ToolResultEvent
from backend.app.agent.orchestrator import run_turn
from backend.app.agent.tools.clusters.get_cluster import GetClusterArgs

from .conftest import capability_ok, make_text_chunks, make_tool_call_chunks


def test_get_cluster_args_rejects_non_uuid_string() -> None:
    """Sanity — Story 2.1's UUID typing rejects invalid strings."""
    with pytest.raises(ValidationError):
        GetClusterArgs.model_validate_json('{"cluster_id": "not-a-uuid"}')


@pytest.mark.asyncio
async def test_invalid_tool_args_produce_validation_failed_event(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """Invalid tool args yield a ToolResultEvent(error='validation_failed')."""
    streams: list[list[Any]] = [
        make_tool_call_chunks(
            call_id="call_bad",
            name="get_cluster",
            arguments='{"cluster_id": "not-a-uuid"}',
        ),
        make_text_chunks("I gave the wrong id; please re-confirm."),
    ]
    stream_iter = iter(streams)

    async def _create(**_: Any) -> AsyncIterator[Any]:
        chunks = next(stream_iter)

        async def _iter() -> AsyncIterator[Any]:
            for c in chunks:
                yield c

        return _iter()

    fake_openai_client.chat.completions.create = _create

    with patch(
        "backend.app.agent.orchestrator.read_capability_result",
        AsyncMock(return_value=capability_ok()),
    ):
        events = []
        async for ev in run_turn(
            conversation_id="conv_1",
            history=[],
            last_user_text="get cluster details",
            last_assistant_text=None,
            degraded_notice_already_sent=False,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            events.append(ev)

    result_events = [e for e in events if isinstance(e, ToolResultEvent)]
    assert any(e.error == "validation_failed" and e.name == "get_cluster" for e in result_events), (
        result_events
    )
    assert any(isinstance(e, DoneEvent) and e.error is None for e in events)
