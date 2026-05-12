"""SSE event-shape contract (feat_chat_agent Story 3.2).

For each of the 4 wire event types the SSE stream emits (``token``,
``tool_call``, ``tool_result``, ``done``), validate the canonical payload
against a Pydantic model. The orchestrator builds these via
``StreamEvent.to_sse_lines()``; tests parse the same JSON the wire would
carry.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.agent.events import (
    DoneEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
)


class TokenEventPayload(BaseModel):
    """``event: token``."""

    text: str


class ToolCallEventPayload(BaseModel):
    """``event: tool_call``."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class ToolResultSuccessPayload(BaseModel):
    """``event: tool_result`` — successful dispatch."""

    id: str
    name: str
    result: dict[str, Any]


class ToolResultErrorPayload(BaseModel):
    """``event: tool_result`` — error envelope."""

    id: str
    name: str
    error: (
        Literal[
            "validation_failed",
            "confirmation_required",
            "internal_error",
            "unknown_tool",
            # Plus any error_code propagated from a tool's HTTPException.detail.
        ]
        | str
    )
    detail: str | None = None


class DoneSuccessPayload(BaseModel):
    """``event: done`` — successful turn."""

    conversation_id: str
    tokens_used: int | None = None
    cost_usd: float | None = None


class DoneErrorPayload(BaseModel):
    """``event: done`` — terminal error."""

    conversation_id: str
    error: Literal[
        "tool_loop_limit_exceeded",
        "openai_rate_limited",
        "internal_error",
    ]


def _payload_from(line: str) -> dict[str, Any]:
    """Parse the SSE ``data:`` line back into JSON for validation."""
    assert line.startswith("event:"), line
    parts = line.strip("\n").split("\n")
    data_line = next(p for p in parts if p.startswith("data:"))
    return json.loads(data_line[len("data: ") :])


def test_token_event_round_trip() -> None:
    payload = _payload_from(TokenEvent(text="hello").to_sse_lines())
    TokenEventPayload.model_validate(payload)


def test_tool_call_event_round_trip() -> None:
    ev = ToolCallEvent(id="call_1", name="get_cluster", arguments={"cluster_id": "01987..."})
    payload = _payload_from(ev.to_sse_lines())
    ToolCallEventPayload.model_validate(payload)


def test_tool_result_success_round_trip() -> None:
    ev = ToolResultEvent(id="call_1", name="get_cluster", result={"id": "01987..."})
    payload = _payload_from(ev.to_sse_lines())
    ToolResultSuccessPayload.model_validate(payload)


def test_tool_result_error_round_trip() -> None:
    ev = ToolResultEvent(
        id="call_1",
        name="create_study",
        error="confirmation_required",
        detail="needs explicit yes",
    )
    payload = _payload_from(ev.to_sse_lines())
    ToolResultErrorPayload.model_validate(payload)


def test_done_success_round_trip() -> None:
    ev = DoneEvent(conversation_id="conv_1", tokens_used=1234, cost_usd=0.0023)
    payload = _payload_from(ev.to_sse_lines())
    DoneSuccessPayload.model_validate(payload)


def test_done_error_round_trip() -> None:
    ev = DoneEvent(conversation_id="conv_1", error="tool_loop_limit_exceeded")
    payload = _payload_from(ev.to_sse_lines())
    DoneErrorPayload.model_validate(payload)
