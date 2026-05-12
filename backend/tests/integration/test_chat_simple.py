"""One-turn SSE chat (feat_chat_agent Story 3.2).

Mocks ``AsyncOpenAI()`` at the agent_chat module boundary. The fake
``chat.completions.create`` returns an async iterator emitting a single text
delta + a usage-only chunk. Asserts SSE framing and durable message
persistence.

The full multi-turn / tool-call / confirmation flow (``test_chat_create_study.py``
in the plan) is captured as a follow-up — Story 3.2's contract test
(``test_sse_event_shapes.py``) already validates every event shape; the unit
tests in Story 2.5 already validate orchestrator behavior.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app.llm.capability_models import CapabilityResult

pytestmark = pytest.mark.integration


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class _FakeDelta:
    def __init__(self, content: str | None = None) -> None:
        self.content = content
        self.tool_calls = None


class _FakeChoice:
    def __init__(self, content: str | None = None) -> None:
        self.delta = _FakeDelta(content)


class _FakeChunk:
    def __init__(
        self,
        choices: list[_FakeChoice] | None = None,
        usage: _FakeUsage | None = None,
    ) -> None:
        self.choices = choices or []
        self.usage = usage


async def _fake_text_stream(text: str) -> Any:
    chunks = [
        _FakeChunk(choices=[_FakeChoice(content=text)]),
        _FakeChunk(usage=_FakeUsage()),
    ]
    for c in chunks:
        yield c


def _make_fake_client(text: str) -> Any:
    fake = AsyncMock()
    fake.chat = AsyncMock()
    fake.chat.completions = AsyncMock()

    async def _create(**_: Any) -> Any:
        return _fake_text_stream(text)

    fake.chat.completions.create = _create
    fake.close = AsyncMock()
    return fake


async def test_one_turn_chat_streams_token_and_done(
    async_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /messages → SSE with one token event + one done event; row persisted."""

    # Patch the capability cache so tools_enabled is True.
    cap = CapabilityResult(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini-2024-07-18",
        models_endpoint="ok",
        chat_completion="ok",
        function_calling="ok",
        structured_output="ok",
        tested_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        "backend.app.agent.orchestrator.read_capability_result",
        AsyncMock(return_value=cap),
    )

    # Configure the OpenAI key + budget so preflight passes.
    from backend.app.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setitem(settings.__dict__, "openai_api_key", "test-key")

    # Patch AsyncOpenAI in agent_chat.
    monkeypatch.setattr(
        "backend.app.services.agent_chat.AsyncOpenAI",
        lambda **_: _make_fake_client("Hi there!"),
    )

    # Create the conversation.
    create_resp = await async_client.post("/api/v1/conversations", json={"title": "smoke"})
    conv_id = create_resp.json()["id"]

    # Stream the SSE response and collect events.
    events: list[tuple[str, dict[str, Any]]] = []
    async with async_client.stream(
        "POST",
        f"/api/v1/conversations/{conv_id}/messages",
        json={"role": "user", "content": {"text": "hello"}},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        buffer = ""
        async for chunk in response.aiter_bytes():
            buffer += chunk.decode("utf-8")
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                if not frame.strip():
                    continue
                lines = frame.split("\n")
                event_type = next(
                    line.split(": ", 1)[1] for line in lines if line.startswith("event:")
                )
                data_str = next(
                    line.split(": ", 1)[1] for line in lines if line.startswith("data:")
                )
                events.append((event_type, json.loads(data_str)))

    event_types = [t for t, _ in events]
    assert "token" in event_types
    assert "done" in event_types

    # The persisted history should now contain user + assistant rows.
    detail = (await async_client.get(f"/api/v1/conversations/{conv_id}")).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles[0] == "user"
    assert "assistant" in roles
    # Conversation title was already explicit ("smoke"); auto-gen MUST NOT overwrite.
    assert detail["title"] == "smoke"
