"""UUID serialization in events + Pydantic validation (feat_chat_agent Story 2.5).

Defense-in-depth: ToolCallEvent.arguments comes from json.loads (so it's
JSON-safe by construction), AND the Pydantic args contract guarantees
``model_dump(mode='json')`` returns string UUIDs if any future code serializes
validated args.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from backend.app.agent.events import ToolCallEvent
from backend.app.agent.orchestrator import run_turn
from backend.app.agent.tools.clusters.get_cluster import GetClusterArgs

from .conftest import capability_ok, make_text_chunks, make_tool_call_chunks


@pytest.mark.asyncio
async def test_tool_call_event_arguments_are_json_serializable(
    fake_ctx: Any, fake_openai_client: Any
) -> None:
    """A get_cluster tool_call yields a ToolCallEvent whose arguments json.dumps cleanly."""
    valid_uuid = "01987b78-89ab-7def-8000-000000000000"
    streams = [
        make_tool_call_chunks(
            call_id="call_1",
            name="get_cluster",
            arguments=f'{{"cluster_id": "{valid_uuid}"}}',
        ),
        make_text_chunks("here is the cluster"),
    ]
    stream_iter = iter(streams)

    async def _create(**_: Any) -> AsyncIterator[Any]:
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
            {"get_cluster": AsyncMock(return_value={"id": valid_uuid, "name": "x"})},
        ),
    ):
        events = []
        async for ev in run_turn(
            conversation_id="conv_1",
            history=[],
            last_user_text="get cluster",
            last_assistant_text=None,
            degraded_notice_already_sent=False,
            ctx=fake_ctx,
            openai_client=fake_openai_client,
        ):
            events.append(ev)

    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert tool_calls, "no ToolCallEvent emitted"
    # Round-trip must succeed without TypeError on UUID objects.
    json.dumps(tool_calls[0].arguments)


def test_validated_args_serialize_to_string_uuid_via_model_dump_json() -> None:
    """Defense-in-depth — Pydantic v2 ``mode='json'`` returns string UUIDs."""
    args = GetClusterArgs(cluster_id=UUID("01987b78-89ab-7def-8000-000000000000"))
    serialized = args.model_dump(mode="json")
    assert isinstance(serialized["cluster_id"], str)
    json.dumps(serialized)
