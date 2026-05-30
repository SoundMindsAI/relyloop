# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit test: ToolContext exposes conversation_id; agent_chat plumbs it through.

feat_agent_propose_search_space Story 3.1 — the adherence-telemetry events
(spec FR-6) need a stable per-conversation identifier on ToolContext so
``propose_search_space_impl`` and ``create_study_impl`` can tag their
structlog events with it, enabling offline correlation of propose→create
chain adherence.
"""

from __future__ import annotations

import dataclasses
import inspect

from backend.app.agent.context import ToolContext
from backend.app.services import agent_chat


def test_tool_context_has_conversation_id_str_field() -> None:
    """ToolContext exposes ``conversation_id: str`` as a required field."""
    fields = {f.name: f for f in dataclasses.fields(ToolContext)}
    assert "conversation_id" in fields, "ToolContext must expose conversation_id"
    # Annotation is captured as the string "str" under `from __future__ import annotations`.
    assert fields["conversation_id"].type == "str"
    # No default — required positional/keyword arg.
    assert fields["conversation_id"].default is dataclasses.MISSING
    assert fields["conversation_id"].default_factory is dataclasses.MISSING


def test_tool_context_is_frozen() -> None:
    """ToolContext remains frozen so impls can't accidentally mutate the conversation_id."""
    params = dataclasses.fields(ToolContext)
    # ``frozen=True`` is verified indirectly: a frozen dataclass exposes __setattr__
    # raising dataclasses.FrozenInstanceError. Direct attribute write asserts the
    # invariant without relying on hidden meta attributes.
    ctx = ToolContext(
        db=object(),  # type: ignore[arg-type]
        conversation_id="conv-xyz",
        redis=object(),  # type: ignore[arg-type]
        arq_pool=None,
        settings=object(),  # type: ignore[arg-type]
    )
    try:
        ctx.conversation_id = "different"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("ToolContext must remain frozen")
    assert ctx.conversation_id == "conv-xyz"
    # Touch params so the field count remains stable (one more line of defense
    # against accidental ToolContext bloat).
    assert len(params) == 5


def test_agent_chat_passes_conversation_id_to_tool_context() -> None:
    """``agent_chat.handle_user_turn`` constructs ToolContext with the conversation_id arg.

    Static-source assertion (not a runtime call) — the alternative is a full
    integration test against Postgres, which is overkill for verifying that a
    single kwarg is plumbed. The grep is precise: the only ToolContext
    construction in ``backend/app/`` lives in ``agent_chat.py`` per
    Story 3.1's grep audit.
    """
    source = inspect.getsource(agent_chat)
    assert "ToolContext(" in source, "agent_chat must instantiate ToolContext"
    # The construction must include conversation_id=conversation_id (kwarg pass-through).
    assert "conversation_id=conversation_id" in source, (
        "agent_chat must plumb conversation_id into ToolContext per Story 3.1"
    )
