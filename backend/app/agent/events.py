r"""Stream events emitted by the orchestrator (feat_chat_agent Story 2.5).

The orchestrator is a pure async generator — it does not write to the DB.
Six event types flow through ``run_turn``:

* **Wire events** forwarded to SSE (4): :class:`TokenEvent`, :class:`ToolCallEvent`,
  :class:`ToolResultEvent`, :class:`DoneEvent`. Each carries an
  ``.to_sse_lines()`` method that produces the canonical
  ``event: <type>\ndata: <json>\n\n`` framing.
* **Persistence events** consumed internally by :func:`agent_chat.send_user_message`
  to call ``repo.create_message`` (2): :class:`AssistantMessagePersistEvent`,
  :class:`ToolMessagePersistEvent`. NOT forwarded to SSE — the visible content
  already streamed via ``TokenEvent`` / ``ToolCallEvent`` / ``ToolResultEvent``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Wire events (forwarded to SSE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenEvent:
    """One streamed text delta."""

    text: str

    def to_sse_lines(self) -> str:
        """Render as canonical SSE framing."""
        return f"event: token\ndata: {json.dumps({'text': self.text})}\n\n"


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    """The LLM emitted a tool_call. Arguments are the JSON-parsed dict.

    Emitted BEFORE Pydantic validation runs, so the UI's ``<ToolCallCard>``
    renders even when the args fail validation. ``arguments`` is always a
    ``dict`` coming from ``json.loads`` of the OpenAI-supplied arguments
    string (or ``{"_raw": "<raw>"}`` if the raw string itself isn't valid
    JSON). No Python ``UUID`` objects ever enter this field, so
    ``json.dumps`` round-trips cleanly.
    """

    id: str
    name: str
    arguments: dict[str, Any]

    def to_sse_lines(self) -> str:
        """Render as canonical SSE framing."""
        payload = {"id": self.id, "name": self.name, "arguments": self.arguments}
        return f"event: tool_call\ndata: {json.dumps(payload, default=str)}\n\n"


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    """A tool dispatch terminated — either with a result or an error code."""

    id: str
    name: str
    result: dict[str, Any] | None = None
    error: str | None = None
    detail: str | None = None

    def to_sse_lines(self) -> str:
        """Render as canonical SSE framing."""
        payload: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.error is not None:
            payload["error"] = self.error
            if self.detail is not None:
                payload["detail"] = self.detail
        else:
            payload["result"] = self.result
        return f"event: tool_result\ndata: {json.dumps(payload, default=str)}\n\n"


@dataclass(frozen=True, slots=True)
class DoneEvent:
    """Terminal event for a turn. Carries usage + cost on success, error code on failure."""

    conversation_id: str
    tokens_used: int | None = None
    cost_usd: float | None = None
    error: str | None = None
    iterations: int | None = None

    def to_sse_lines(self) -> str:
        """Render as canonical SSE framing."""
        payload: dict[str, Any] = {"conversation_id": self.conversation_id}
        if self.error is not None:
            payload["error"] = self.error
        else:
            if self.tokens_used is not None:
                payload["tokens_used"] = self.tokens_used
            if self.cost_usd is not None:
                payload["cost_usd"] = self.cost_usd
        return f"event: done\ndata: {json.dumps(payload, default=str)}\n\n"


# ---------------------------------------------------------------------------
# Persistence events (consumed by agent_chat, NOT forwarded to SSE)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssistantMessagePersistEvent:
    """Internal marker: agent_chat should INSERT an ``assistant``-role message.

    ``tool_calls`` is the structured list captured from the OpenAI stream
    (each item is ``{id, type, function: {name, arguments}}``) or None for
    plain text replies. ``usage`` carries the OpenAI token usage when present
    (None for the degraded-mode ``system_notice``). ``cost_usd`` is the
    computed cost from ``compute_call_cost``.
    """

    content: dict[str, Any]
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ToolMessagePersistEvent:
    """Internal marker: agent_chat should INSERT a ``tool``-role message."""

    tool_call_id: str
    content: dict[str, Any] = field(default_factory=dict)


StreamEvent = (
    TokenEvent
    | ToolCallEvent
    | ToolResultEvent
    | DoneEvent
    | AssistantMessagePersistEvent
    | ToolMessagePersistEvent
)
"""Union of every event the orchestrator can yield."""


__all__ = [
    "AssistantMessagePersistEvent",
    "DoneEvent",
    "StreamEvent",
    "TokenEvent",
    "ToolCallEvent",
    "ToolMessagePersistEvent",
    "ToolResultEvent",
]
