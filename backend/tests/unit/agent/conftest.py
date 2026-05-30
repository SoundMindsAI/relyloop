# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for orchestrator unit tests (feat_chat_agent Story 2.5).

Provides:

* :func:`make_stream` — builds a fake ``chat.completions.create`` stream from a
  declarative list of chunk specs.
* :func:`make_ctx` — minimal :class:`ToolContext` with stub redis + settings so
  tests don't need a live DB / Redis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.agent.context import ToolContext
from backend.app.llm.capability_models import CapabilityResult


@dataclass
class FakeUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5
    total_tokens: int = 15


@dataclass
class FakeFuncDelta:
    name: str | None = None
    arguments: str | None = None


@dataclass
class FakeToolCallDelta:
    index: int = 0
    id: str | None = None
    function: FakeFuncDelta | None = None
    type: str = "function"


@dataclass
class FakeDelta:
    content: str | None = None
    tool_calls: list[FakeToolCallDelta] | None = None


@dataclass
class FakeChoice:
    delta: FakeDelta


@dataclass
class FakeChunk:
    choices: list[FakeChoice]
    usage: FakeUsage | None = None


async def _aiter_chunks(chunks: list[FakeChunk]) -> Any:
    for c in chunks:
        yield c


def make_stream(chunks: list[FakeChunk]) -> Any:
    """Return an awaitable that yields an async iterator over ``chunks``.

    Mirrors the shape of ``await openai_client.chat.completions.create(...)``
    — the awaited result is itself an async iterable.
    """

    async def _create(**_: Any) -> Any:
        return _aiter_chunks(chunks)

    return _create


def make_text_chunks(text: str, usage: FakeUsage | None = None) -> list[FakeChunk]:
    """Build a 2-chunk stream: one text delta + one usage-only chunk."""
    return [
        FakeChunk(choices=[FakeChoice(delta=FakeDelta(content=text))]),
        FakeChunk(choices=[], usage=usage or FakeUsage()),
    ]


def make_tool_call_chunks(
    *,
    call_id: str,
    name: str,
    arguments: str,
    usage: FakeUsage | None = None,
) -> list[FakeChunk]:
    """Build a tool-call stream: one delta carrying the tool_call + usage-only chunk."""
    return [
        FakeChunk(
            choices=[
                FakeChoice(
                    delta=FakeDelta(
                        tool_calls=[
                            FakeToolCallDelta(
                                index=0,
                                id=call_id,
                                function=FakeFuncDelta(name=name, arguments=arguments),
                            )
                        ]
                    )
                )
            ]
        ),
        FakeChunk(choices=[], usage=usage or FakeUsage()),
    ]


@pytest.fixture
def fake_settings() -> Any:
    """Minimal settings stub the orchestrator reads."""
    settings = MagicMock()
    settings.openai_model_chat = "gpt-4o-mini-2024-07-18"
    settings.openai_base_url = "https://api.openai.com/v1"
    return settings


@pytest.fixture
def fake_redis() -> Any:
    """AsyncMock redis with no cached capability by default."""
    return AsyncMock()


@pytest.fixture
def fake_db() -> Any:
    """AsyncMock async session — never actually called by orchestrator code."""
    return AsyncMock()


@pytest.fixture
def fake_ctx(fake_db: Any, fake_redis: Any, fake_settings: Any) -> ToolContext:
    """ToolContext with all dependencies stubbed.

    ``conversation_id`` defaults to a stable fixture value so telemetry
    assertions can match against it. Tests that need a different value can
    override by constructing a fresh ToolContext inline.
    """
    return ToolContext(
        db=fake_db,
        conversation_id="test-conversation-fixture",
        redis=fake_redis,
        arq_pool=None,
        settings=fake_settings,
    )


@pytest.fixture
def fake_openai_client() -> Any:
    """AsyncMock OpenAI client; tests assign ``.chat.completions.create`` per case."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    return client


def capability_ok(model: str = "gpt-4o-mini-2024-07-18") -> CapabilityResult:
    """CapabilityResult with both probes ok (tool dispatch enabled)."""
    from datetime import UTC, datetime

    return CapabilityResult(
        base_url="https://api.openai.com/v1",
        model=model,
        models_endpoint="ok",
        chat_completion="ok",
        function_calling="ok",
        structured_output="ok",
        tested_at=datetime.now(UTC),
    )


def capability_degraded(model: str = "gpt-4o-mini-2024-07-18") -> CapabilityResult:
    """CapabilityResult with function_calling failed (tool dispatch disabled)."""
    from datetime import UTC, datetime

    return CapabilityResult(
        base_url="https://api.openai.com/v1",
        model=model,
        models_endpoint="ok",
        chat_completion="ok",
        function_calling="fail",
        structured_output="ok",
        tested_at=datetime.now(UTC),
    )
