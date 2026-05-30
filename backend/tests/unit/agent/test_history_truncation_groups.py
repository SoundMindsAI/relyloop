# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Tail-truncation preserves tool-message-group integrity (GPT-5.5 final-review F4)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from backend.app.services.agent_chat import _truncate_preserving_tool_groups


def _msg(role: str, *, tool_calls: Any = None) -> Any:
    m = MagicMock()
    m.role = role
    m.tool_calls = tool_calls
    return m


def test_no_truncation_when_under_cap() -> None:
    msgs = [_msg("user"), _msg("assistant"), _msg("user")]
    assert _truncate_preserving_tool_groups(msgs, 10) is msgs


def test_naive_cut_in_middle_of_tool_group_advances_past_group() -> None:
    """A cut that lands on assistant-with-tool_calls advances forward past the
    tool group to the next clean boundary (a bare assistant or user message).
    """
    msgs = [
        _msg("user"),
        _msg("assistant", tool_calls=[{"id": "c1"}]),  # cut starts here at max_kept=5 → cut=1
        _msg("tool"),
        _msg("assistant"),  # next clean boundary (bare assistant)
        _msg("user"),
        _msg("assistant"),
    ]
    truncated = _truncate_preserving_tool_groups(msgs, 5)
    # Cut advances past assistant-tc + tool to land on the bare assistant.
    assert truncated[0].role == "assistant"
    assert truncated[0].tool_calls is None


def test_naive_cut_landing_on_tool_role_advances_past_orphan() -> None:
    """A cut that lands on a role:tool row (orphan — no preceding assistant in
    the kept slice) advances forward to drop the orphan tool message."""
    msgs = [
        _msg("user"),
        _msg("assistant", tool_calls=[{"id": "c1"}]),
        _msg("tool"),  # cut starts here at max_kept=4 → cut=2
        _msg("assistant"),
        _msg("user"),
        _msg("assistant"),
    ]
    truncated = _truncate_preserving_tool_groups(msgs, 4)
    # Cut starts at index 2 (role=tool), advances to index 3 (bare assistant).
    assert truncated[0].role == "assistant"
    assert truncated[0].tool_calls is None


def test_cut_already_on_clean_boundary_kept_as_is() -> None:
    """A cut that already lands on a user message keeps its position."""
    msgs = [
        _msg("assistant"),
        _msg("user"),  # cut here is fine
        _msg("assistant"),
        _msg("user"),
        _msg("assistant"),
    ]
    truncated = _truncate_preserving_tool_groups(msgs, 4)
    assert truncated[0].role == "user"
    assert len(truncated) == 4
